"""RF-DETR 转换 worker 接口与 ONNX/OpenVINO/TensorRT 实现。"""

from __future__ import annotations

from typing import Any

import torch

from backend.service.application.backends import (
    ConversionBackend,
    ConversionBackendOutput,
    ConversionBackendRunRequest,
    ConversionBackendRunResult,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
    ServiceError,
)
from backend.service.application.models.rfdetr_model import build_rfdetr_model
from backend.service.application.models.rfdetr_model_service import (
    RFDETR_DETECTION_FILE_TYPES,
)
from backend.service.application.models.rfdetr_segmentation_model import (
    build_rfdetr_segmentation_model,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.workers.conversion.yolo_conversion_common import (
    build_conversion_options_metadata,
    build_output_base_name,
    import_onnx_conversion_dependencies,
    resolve_conversion_phase,
    resolve_openvino_ir_build_precision,
    resolve_tensorrt_engine_build_precision,
    summarize_numeric_validation,
)
from backend.workers.conversion.yolox_conversion_runner import (
    LocalYoloXConversionRunner,
)


RfdetrConversionRunRequest = ConversionBackendRunRequest
RfdetrConversionOutput = ConversionBackendOutput
RfdetrConversionRunResult = ConversionBackendRunResult
RfdetrConversionRunner = ConversionBackend

RFDETR_ONNX_FILE = RFDETR_DETECTION_FILE_TYPES.onnx_file_type
RFDETR_ONNX_OPTIMIZED_FILE = RFDETR_DETECTION_FILE_TYPES.onnx_optimized_file_type
RFDETR_OPENVINO_IR_FILE = RFDETR_DETECTION_FILE_TYPES.openvino_ir_file_type
RFDETR_TENSORRT_ENGINE_FILE = RFDETR_DETECTION_FILE_TYPES.tensorrt_engine_file_type


class LocalRfdetrConversionRunner(LocalYoloXConversionRunner, ConversionBackend):
    """本地 RF-DETR 转换执行器。"""

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化 RF-DETR 转换执行器。"""

        super().__init__(dataset_storage=dataset_storage)

    def run_conversion(
        self,
        request: RfdetrConversionRunRequest,
    ) -> RfdetrConversionRunResult:
        """执行 RF-DETR ONNX/OpenVINO/TensorRT 转换链。"""

        if not request.plan_steps:
            raise InvalidRequestError("转换计划 steps 不能为空")
        metadata = dict(request.metadata or {})
        task_type = str(
            metadata.get("task_type") or request.task_type or "detection"
        ).strip().lower()
        if task_type not in {"detection", "segmentation"}:
            raise InvalidRequestError(
                "RF-DETR 当前不支持指定任务分类的转换执行",
                details={"task_type": task_type},
            )

        runtime_target = request.source_runtime_target
        checkpoint_path = runtime_target.checkpoint_path
        if checkpoint_path is None or not checkpoint_path.is_file():
            raise ServiceError("RF-DETR 转换缺少可读取的 checkpoint 文件")

        checkpoint = torch.load(
            str(checkpoint_path),
            map_location="cpu",
            weights_only=False,
        )
        state_dict = checkpoint.get("model_state_dict", checkpoint)
        num_classes = len(runtime_target.labels)
        model_scale = runtime_target.model_scale or "nano"
        model = _build_rfdetr_model(task_type=task_type, model_scale=model_scale, num_classes=num_classes)
        model.load_state_dict(state_dict, strict=False)
        model.to("cpu")
        model.eval()

        input_height, input_width = _resolve_input_size(runtime_target.input_size)
        dummy_input = torch.randn(1, 3, input_height, input_width, dtype=torch.float32)
        onnx_module, onnxruntime_module, onnx_simplify = import_onnx_conversion_dependencies()
        base_name = build_output_base_name(runtime_target)
        onnx_object_key = (
            f"{request.output_object_prefix}/artifacts/builds/{base_name}.onnx"
        )
        optimized_object_key = (
            f"{request.output_object_prefix}/artifacts/builds/{base_name}.optimized.onnx"
        )
        openvino_object_key = (
            f"{request.output_object_prefix}/artifacts/builds/{base_name}.openvino.xml"
        )
        tensorrt_object_key = (
            f"{request.output_object_prefix}/artifacts/builds/{base_name}.tensorrt.engine"
        )
        openvino_ir_build_precision = resolve_openvino_ir_build_precision(metadata)
        tensorrt_engine_build_precision = resolve_tensorrt_engine_build_precision(
            metadata
        )
        output_names = _resolve_export_output_names(task_type)
        executed_step_kinds: list[str] = []
        validation_summary: dict[str, object] = {}
        onnx_output: RfdetrConversionOutput | None = None
        optimized_output: RfdetrConversionOutput | None = None
        openvino_output: RfdetrConversionOutput | None = None
        tensorrt_output: RfdetrConversionOutput | None = None

        for step in request.plan_steps:
            executed_step_kinds.append(step.kind)
            if step.kind == "export-onnx":
                export_summary = self._export_onnx(
                    model=model,
                    dummy_input=dummy_input,
                    output_object_key=onnx_object_key,
                    output_names=output_names,
                )
                onnx_output = RfdetrConversionOutput(
                    target_format="onnx",
                    object_uri=onnx_object_key,
                    file_type=RFDETR_ONNX_FILE,
                    metadata=export_summary,
                )
                continue
            if step.kind == "validate-onnx":
                validation_summary = self._validate_onnx(
                    model=model,
                    dummy_input=dummy_input,
                    onnx_object_key=onnx_object_key,
                    onnx_module=onnx_module,
                    onnxruntime_module=onnxruntime_module,
                    output_names=output_names,
                )
                if onnx_output is not None:
                    onnx_output = RfdetrConversionOutput(
                        target_format=onnx_output.target_format,
                        object_uri=onnx_output.object_uri,
                        file_type=onnx_output.file_type,
                        metadata={
                            **onnx_output.metadata,
                            "validation_summary": validation_summary,
                        },
                    )
                continue
            if step.kind == "optimize-onnx":
                if onnx_output is None:
                    raise ServiceConfigurationError("optimize-onnx 缺少 export-onnx 输出")
                optimize_summary = self._optimize_onnx(
                    source_object_key=onnx_object_key,
                    output_object_key=optimized_object_key,
                    onnx_module=onnx_module,
                    onnx_simplify=onnx_simplify,
                )
                optimized_output = RfdetrConversionOutput(
                    target_format="onnx-optimized",
                    object_uri=optimized_object_key,
                    file_type=RFDETR_ONNX_OPTIMIZED_FILE,
                    metadata={
                        **optimize_summary,
                        "validation_summary": validation_summary,
                        "source_object_uri": onnx_object_key,
                    },
                )
                continue
            if step.kind == "build-openvino-ir":
                if optimized_output is None:
                    raise ServiceConfigurationError(
                        "build-openvino-ir 缺少 optimize-onnx 输出"
                    )
                build_summary = self._build_openvino_ir(
                    source_object_key=optimized_object_key,
                    output_object_key=openvino_object_key,
                    build_precision=openvino_ir_build_precision,
                )
                openvino_output = RfdetrConversionOutput(
                    target_format="openvino-ir",
                    object_uri=openvino_object_key,
                    file_type=RFDETR_OPENVINO_IR_FILE,
                    metadata={
                        **build_summary,
                        "validation_summary": validation_summary,
                        "source_object_uri": optimized_object_key,
                    },
                )
                continue
            if step.kind == "build-tensorrt-engine":
                if optimized_output is None:
                    raise ServiceConfigurationError(
                        "build-tensorrt-engine 缺少 optimize-onnx 输出"
                    )
                build_summary = self._build_tensorrt_engine(
                    source_object_key=optimized_object_key,
                    output_object_key=tensorrt_object_key,
                    build_precision=tensorrt_engine_build_precision,
                )
                tensorrt_output = RfdetrConversionOutput(
                    target_format="tensorrt-engine",
                    object_uri=tensorrt_object_key,
                    file_type=RFDETR_TENSORRT_ENGINE_FILE,
                    metadata={
                        **build_summary,
                        "validation_summary": validation_summary,
                        "source_object_uri": optimized_object_key,
                    },
                )
                continue
            raise InvalidRequestError(
                "当前 RF-DETR conversion runner 不支持指定步骤",
                details={"step_kind": step.kind, "task_type": task_type},
            )

        outputs: list[RfdetrConversionOutput] = []
        if onnx_output is not None:
            outputs.append(onnx_output)
        if optimized_output is not None:
            outputs.append(optimized_output)
        if openvino_output is not None:
            outputs.append(openvino_output)
        if tensorrt_output is not None:
            outputs.append(tensorrt_output)
        return RfdetrConversionRunResult(
            conversion_task_id=request.conversion_task_id,
            outputs=tuple(outputs),
            metadata={
                "phase": resolve_conversion_phase(request.target_formats),
                "executed_step_kinds": executed_step_kinds,
                "validation_summary": validation_summary,
                "conversion_options": build_conversion_options_metadata(
                    target_formats=request.target_formats,
                    openvino_ir_build_precision=openvino_ir_build_precision,
                    tensorrt_engine_build_precision=tensorrt_engine_build_precision,
                ),
            },
        )

    def _export_onnx(
        self,
        *,
        model: Any,
        dummy_input: torch.Tensor,
        output_object_key: str,
        output_names: tuple[str, ...],
    ) -> dict[str, object]:
        """把 RF-DETR checkpoint 导出为 ONNX。"""

        output_path = self.dataset_storage.resolve(output_object_key)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with torch.no_grad():
            torch.onnx.export(
                model,
                dummy_input,
                str(output_path),
                export_params=True,
                opset_version=17,
                do_constant_folding=True,
                input_names=["image"],
                output_names=list(output_names),
            )
        return {
            "stage": "export-onnx",
            "object_uri": output_object_key,
            "opset_version": 17,
            "input_size": [int(dummy_input.shape[-2]), int(dummy_input.shape[-1])],
            "exporter_mode": "legacy-torch-onnx-export",
            "output_names": list(output_names),
        }

    def _validate_onnx(
        self,
        *,
        model: Any,
        dummy_input: torch.Tensor,
        onnx_object_key: str,
        onnx_module: object,
        onnxruntime_module: object,
        output_names: tuple[str, ...],
    ) -> dict[str, object]:
        """执行 RF-DETR ONNX 合法性与数值校验。"""

        onnx_path = self.dataset_storage.resolve(onnx_object_key)
        onnx_model = onnx_module.load(str(onnx_path))
        onnx_module.checker.check_model(onnx_model)

        with torch.no_grad():
            torch_outputs = _extract_torch_outputs(
                model_outputs=model(dummy_input),
                output_names=output_names,
            )
        ort_session = onnxruntime_module.InferenceSession(
            str(onnx_path),
            providers=["CPUExecutionProvider"],
        )
        ort_outputs = ort_session.run(
            list(output_names),
            {ort_session.get_inputs()[0].name: dummy_input.detach().cpu().numpy()},
        )
        summary = summarize_numeric_validation(
            np_module=__import__("numpy"),
            torch_outputs=torch_outputs,
            ort_outputs=ort_outputs,
        )
        if not bool(summary["allclose"]):
            raise ServiceConfigurationError(
                "RF-DETR ONNX 数值校验失败",
                details=dict(summary),
            )
        return summary


def _build_rfdetr_model(
    *,
    task_type: str,
    model_scale: str,
    num_classes: int,
) -> Any:
    """按任务分类构建 RF-DETR project-native 模型。"""

    if task_type == "segmentation":
        return build_rfdetr_segmentation_model(
            model_scale=model_scale,
            num_classes=num_classes,
        )
    return build_rfdetr_model(model_scale=model_scale, num_classes=num_classes)


def _resolve_input_size(input_size: tuple[int, int]) -> tuple[int, int]:
    """把 runtime target 的输入尺寸规整为稳定二元组。"""

    if len(input_size) == 2:
        return int(input_size[0]), int(input_size[1])
    return 384, 384


def _resolve_export_output_names(task_type: str) -> tuple[str, ...]:
    """按任务分类返回 RF-DETR 导出输出名。"""

    if task_type == "segmentation":
        return ("pred_logits", "pred_boxes", "pred_masks")
    return ("pred_logits", "pred_boxes")


def _extract_torch_outputs(
    *,
    model_outputs: object,
    output_names: tuple[str, ...],
) -> list[object]:
    """按导出输出名顺序提取 PyTorch 原始输出。"""

    if isinstance(model_outputs, dict):
        normalized_outputs: list[object] = []
        for output_name in output_names:
            output_tensor = model_outputs.get(output_name)
            if output_tensor is None or not hasattr(output_tensor, "detach"):
                raise ServiceConfigurationError(
                    "RF-DETR 模型输出缺少 ONNX 校验所需字段",
                    details={
                        "output_name": output_name,
                        "available_output_names": sorted(model_outputs.keys()),
                    },
                )
            normalized_outputs.append(output_tensor.detach().cpu().numpy())
        return normalized_outputs
    if isinstance(model_outputs, (list, tuple)):
        normalized_outputs: list[object] = []
        for output_tensor in model_outputs:
            if hasattr(output_tensor, "detach"):
                normalized_outputs.append(output_tensor.detach().cpu().numpy())
        if len(normalized_outputs) == len(output_names):
            return normalized_outputs
    if hasattr(model_outputs, "detach") and len(output_names) == 1:
        return [model_outputs.detach().cpu().numpy()]
    raise ServiceConfigurationError(
        "当前 RF-DETR 模型输出格式不受支持",
        details={
            "output_type": model_outputs.__class__.__name__,
            "expected_output_names": list(output_names),
        },
    )
