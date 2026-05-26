"""YOLOv8 转换 worker 接口与 ONNX phase-1 实现。"""

from __future__ import annotations

from backend.service.application.backends import (
    ConversionBackend,
    ConversionBackendOutput,
    ConversionBackendRunRequest,
    ConversionBackendRunResult,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.runtime.yolov8_predictor import PyTorchYoloV8RuntimeSession
from backend.service.domain.files.yolov8_file_types import (
    YOLOV8_ONNX_FILE,
    YOLOV8_ONNX_OPTIMIZED_FILE,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.yolox_conversion_runner import (
    LocalYoloXConversionRunner,
    _build_conversion_options_metadata,
    _build_output_base_name,
    _import_onnx_dependencies,
    _resolve_conversion_phase,
)


YoloV8ConversionRunRequest = ConversionBackendRunRequest
YoloV8ConversionOutput = ConversionBackendOutput
YoloV8ConversionRunResult = ConversionBackendRunResult
YoloV8ConversionRunner = ConversionBackend


class LocalYoloV8ConversionRunner(LocalYoloXConversionRunner):
    """使用本地文件存储执行 YOLOv8 ONNX 转换链。"""

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化本地 YOLOv8 转换 runner。"""

        super().__init__(dataset_storage=dataset_storage)

    def run_conversion(self, request: YoloV8ConversionRunRequest) -> YoloV8ConversionRunResult:
        """执行当前已接通的 YOLOv8 ONNX 转换链。"""

        if not request.plan_steps:
            raise InvalidRequestError("转换计划 steps 不能为空")
        session = PyTorchYoloV8RuntimeSession.load(
            dataset_storage=self.dataset_storage,
            runtime_target=request.source_runtime_target,
        )
        onnx_module, onnxruntime_module, onnx_simplify = _import_onnx_dependencies()
        base_name = _build_output_base_name(request.source_runtime_target)
        onnx_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.onnx"
        optimized_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.optimized.onnx"
        executed_step_kinds: list[str] = []
        validation_summary: dict[str, object] = {}
        onnx_output: YoloV8ConversionOutput | None = None
        optimized_output: YoloV8ConversionOutput | None = None

        for step in request.plan_steps:
            executed_step_kinds.append(step.kind)
            if step.kind == "export-onnx":
                export_summary = self._export_onnx(
                    session=session,
                    output_object_key=onnx_object_key,
                    onnx_module=onnx_module,
                )
                onnx_output = YoloV8ConversionOutput(
                    target_format="onnx",
                    object_uri=onnx_object_key,
                    file_type=YOLOV8_ONNX_FILE,
                    metadata=export_summary,
                )
                continue
            if step.kind == "validate-onnx":
                validation_summary = self._validate_onnx(
                    session=session,
                    onnx_object_key=onnx_object_key,
                    onnx_module=onnx_module,
                    onnxruntime_module=onnxruntime_module,
                )
                if onnx_output is not None:
                    onnx_output = YoloV8ConversionOutput(
                        target_format=onnx_output.target_format,
                        object_uri=onnx_output.object_uri,
                        file_type=onnx_output.file_type,
                        metadata={**onnx_output.metadata, "validation_summary": validation_summary},
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
                optimized_output = YoloV8ConversionOutput(
                    target_format="onnx-optimized",
                    object_uri=optimized_object_key,
                    file_type=YOLOV8_ONNX_OPTIMIZED_FILE,
                    metadata={
                        **optimize_summary,
                        "validation_summary": validation_summary,
                        "source_object_uri": onnx_object_key,
                    },
                )
                continue
            raise InvalidRequestError(
                "当前 YOLOv8 conversion runner 不支持指定步骤",
                details={"step_kind": step.kind},
            )

        outputs: list[YoloV8ConversionOutput] = []
        if onnx_output is not None:
            outputs.append(onnx_output)
        if optimized_output is not None:
            outputs.append(optimized_output)
        return YoloV8ConversionRunResult(
            conversion_task_id=request.conversion_task_id,
            outputs=tuple(outputs),
            metadata={
                "phase": _resolve_conversion_phase(request.target_formats),
                "executed_step_kinds": executed_step_kinds,
                "validation_summary": validation_summary,
                "conversion_options": _build_conversion_options_metadata(
                    target_formats=request.target_formats,
                    openvino_ir_build_precision="fp32",
                    tensorrt_engine_build_precision="fp32",
                ),
            },
        )
