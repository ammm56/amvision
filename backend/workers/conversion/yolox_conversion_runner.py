"""YOLOX 转换 worker 接口与 ONNX/OpenVINO/TensorRT 实现。"""

from __future__ import annotations

import json
from pathlib import PurePosixPath

from backend.service.application.backends import (
    ConversionBackend,
    ConversionBackendOutput,
    ConversionBackendRunRequest,
    ConversionBackendRunResult,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.runtime.yolox_detection_runtime import PyTorchYoloXRuntimeSession
from backend.service.domain.files.yolox_file_types import (
    YOLOX_ONNX_FILE,
    YOLOX_ONNX_OPTIMIZED_FILE,
    YOLOX_OPENVINO_IR_FILE,
    YOLOX_TENSORRT_ENGINE_FILE,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.yolo_conversion_common import (
    build_conversion_options_metadata,
    build_output_base_name,
    import_onnx_conversion_dependencies,
    normalize_model_outputs,
    optimize_onnx_model,
    resolve_conversion_phase,
    resolve_openvino_ir_build_precision,
    resolve_tensorrt_engine_build_precision,
    run_conversion_script,
    summarize_numeric_validation,
)


_OPENVINO_IR_BUILD_SCRIPT_FILE = "build_openvino_ir.py"
_TENSORRT_ENGINE_BUILD_SCRIPT_FILE = "build_tensorrt_engine.py"


# 沿用统一转换执行规则的 YOLOX 命名导出。
YoloXConversionRunRequest = ConversionBackendRunRequest
YoloXConversionOutput = ConversionBackendOutput
YoloXConversionRunResult = ConversionBackendRunResult
YoloXConversionRunner = ConversionBackend


class LocalYoloXConversionRunner:
    """使用本地文件存储执行 YOLOX ONNX/OpenVINO 转换链。"""

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化本地转换 runner。

        参数：
        - dataset_storage：本地文件存储服务。
        """

        self.dataset_storage = dataset_storage

    def run_conversion(self, request: YoloXConversionRunRequest) -> YoloXConversionRunResult:
        """执行当前已接通的 ONNX/OpenVINO 转换链并返回结果。

        参数：
        - request：转换执行请求。

        返回：
        - YoloXConversionRunResult：转换执行结果。
        """

        if not request.plan_steps:
            raise InvalidRequestError("转换计划 steps 不能为空")
        session = PyTorchYoloXRuntimeSession.load(
            dataset_storage=self.dataset_storage,
            runtime_target=request.source_runtime_target,
        )
        onnx_module, onnxruntime_module, onnx_simplify = import_onnx_conversion_dependencies()
        base_name = build_output_base_name(request.source_runtime_target)
        onnx_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.onnx"
        optimized_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.optimized.onnx"
        openvino_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.openvino.xml"
        tensorrt_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.tensorrt.engine"
        openvino_ir_build_precision = resolve_openvino_ir_build_precision(request.metadata)
        tensorrt_engine_build_precision = resolve_tensorrt_engine_build_precision(request.metadata)
        executed_step_kinds: list[str] = []
        validation_summary: dict[str, object] = {}
        onnx_output: YoloXConversionOutput | None = None
        optimized_output: YoloXConversionOutput | None = None
        openvino_output: YoloXConversionOutput | None = None
        tensorrt_output: YoloXConversionOutput | None = None

        for step in request.plan_steps:
            executed_step_kinds.append(step.kind)
            if step.kind == "export-onnx":
                export_summary = self._export_onnx(
                    session=session,
                    output_object_key=onnx_object_key,
                    onnx_module=onnx_module,
                )
                onnx_output = YoloXConversionOutput(
                    target_format="onnx",
                    object_uri=onnx_object_key,
                    file_type=YOLOX_ONNX_FILE,
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
                    onnx_output = YoloXConversionOutput(
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
                optimized_output = YoloXConversionOutput(
                    target_format="onnx-optimized",
                    object_uri=optimized_object_key,
                    file_type=YOLOX_ONNX_OPTIMIZED_FILE,
                    metadata={
                        **optimize_summary,
                        "validation_summary": validation_summary,
                        "source_object_uri": onnx_object_key,
                    },
                )
                continue
            if step.kind == "build-openvino-ir":
                if optimized_output is None:
                    raise ServiceConfigurationError("build-openvino-ir 缺少 optimize-onnx 输出")
                build_summary = self._build_openvino_ir(
                    source_object_key=optimized_object_key,
                    output_object_key=openvino_object_key,
                    build_precision=openvino_ir_build_precision,
                )
                openvino_output = YoloXConversionOutput(
                    target_format="openvino-ir",
                    object_uri=openvino_object_key,
                    file_type=YOLOX_OPENVINO_IR_FILE,
                    metadata={
                        **build_summary,
                        "validation_summary": validation_summary,
                        "source_object_uri": optimized_object_key,
                    },
                )
                continue
            if step.kind == "build-tensorrt-engine":
                if optimized_output is None:
                    raise ServiceConfigurationError("build-tensorrt-engine 缺少 optimize-onnx 输出")
                build_summary = self._build_tensorrt_engine(
                    source_object_key=optimized_object_key,
                    output_object_key=tensorrt_object_key,
                    build_precision=tensorrt_engine_build_precision,
                )
                tensorrt_output = YoloXConversionOutput(
                    target_format="tensorrt-engine",
                    object_uri=tensorrt_object_key,
                    file_type=YOLOX_TENSORRT_ENGINE_FILE,
                    metadata={
                        **build_summary,
                        "validation_summary": validation_summary,
                        "source_object_uri": optimized_object_key,
                    },
                )
                continue
            raise InvalidRequestError(
                "当前 conversion runner 不支持指定步骤",
                details={"step_kind": step.kind},
            )

        outputs: list[YoloXConversionOutput] = []
        if onnx_output is not None:
            outputs.append(onnx_output)
        if optimized_output is not None:
            outputs.append(optimized_output)
        if openvino_output is not None:
            outputs.append(openvino_output)
        if tensorrt_output is not None:
            outputs.append(tensorrt_output)
        return YoloXConversionRunResult(
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
        session: PyTorchYoloXRuntimeSession,
        output_object_key: str,
        onnx_module: object,
    ) -> dict[str, object]:
        """把 PyTorch checkpoint 导出为 ONNX。"""

        del onnx_module
        output_path = self.dataset_storage.resolve(output_object_key)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        dummy_input = session.imports.torch.randn(
            1,
            3,
            session.runtime_target.input_size[0],
            session.runtime_target.input_size[1],
            device=session.device_name,
            dtype=session.imports.torch.float32,
        )
        with session.imports.torch.no_grad():
            session.imports.torch.onnx.export(
                session.model,
                dummy_input,
                str(output_path),
                export_params=True,
                opset_version=17,
                do_constant_folding=True,
                input_names=["images"],
                output_names=["predictions"],
            )
        return {
            "stage": "export-onnx",
            "object_uri": output_object_key,
            "opset_version": 17,
            "input_size": list(session.runtime_target.input_size),
            "exporter_mode": "legacy-torch-onnx-export",
        }

    def _validate_onnx(
        self,
        *,
        session: PyTorchYoloXRuntimeSession,
        onnx_object_key: str,
        onnx_module: object,
        onnxruntime_module: object,
    ) -> dict[str, object]:
        """执行 ONNX 合法性和数值校验。"""

        onnx_path = self.dataset_storage.resolve(onnx_object_key)
        onnx_model = onnx_module.load(str(onnx_path))
        onnx_module.checker.check_model(onnx_model)

        dummy_input = session.imports.torch.randn(
            1,
            3,
            session.runtime_target.input_size[0],
            session.runtime_target.input_size[1],
            device=session.device_name,
            dtype=session.imports.torch.float32,
        )
        with session.imports.torch.no_grad():
            torch_outputs = normalize_model_outputs(session.model(dummy_input))
        ort_session = onnxruntime_module.InferenceSession(
            str(onnx_path),
            providers=["CPUExecutionProvider"],
        )
        ort_outputs = ort_session.run(
            None,
            {ort_session.get_inputs()[0].name: dummy_input.detach().cpu().numpy()},
        )
        summary = summarize_numeric_validation(
            np_module=session.imports.np,
            torch_outputs=torch_outputs,
            ort_outputs=ort_outputs,
        )
        if not bool(summary["allclose"]):
            raise ServiceConfigurationError(
                "ONNX 数值校验失败",
                details=dict(summary),
            )
        return summary

    def _optimize_onnx(
        self,
        *,
        source_object_key: str,
        output_object_key: str,
        onnx_module: object,
        onnx_simplify: object,
    ) -> dict[str, object]:
        """执行 ONNX 简化优化并写回独立输出。"""

        return optimize_onnx_model(
            source_path=self.dataset_storage.resolve(source_object_key),
            optimized_path=self.dataset_storage.resolve(output_object_key),
            source_object_key=source_object_key,
            output_object_key=output_object_key,
            onnx_module=onnx_module,
            onnx_simplify=onnx_simplify,
        )

    def _build_openvino_ir(
        self,
        *,
        source_object_key: str,
        output_object_key: str,
        build_precision: str,
    ) -> dict[str, object]:
        """把 optimized ONNX 转换为 OpenVINO IR。

        参数：
        - source_object_key：来源 optimized ONNX object key。
        - output_object_key：目标 OpenVINO XML object key。
        - build_precision：OpenVINO IR 权重压缩策略。

        返回：
        - dict[str, object]：OpenVINO IR 构建摘要。
        """

        source_path = self.dataset_storage.resolve(source_object_key)
        output_path = self.dataset_storage.resolve(output_object_key)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        compress_to_fp16 = build_precision == "fp16"
        completed_process = run_conversion_script(
            script_file_name=_OPENVINO_IR_BUILD_SCRIPT_FILE,
            args=[
                str(source_path),
                str(output_path),
                build_precision,
            ],
        )
        if completed_process.returncode != 0:
            raise ServiceConfigurationError(
                "OpenVINO IR 构建失败",
                details={
                    "source_object_uri": source_object_key,
                    "output_object_uri": output_object_key,
                    "stdout": completed_process.stdout.strip(),
                    "stderr": completed_process.stderr.strip(),
                },
            )

        weights_path = output_path.with_suffix(".bin")
        if not output_path.is_file() or not weights_path.is_file():
            raise ServiceConfigurationError(
                "OpenVINO IR 构建未生成完整的 xml/bin 产物",
                details={
                    "output_object_uri": output_object_key,
                    "weights_object_uri": _resolve_openvino_weights_object_key(output_object_key),
                },
            )
        return {
            "stage": "build-openvino-ir",
            "object_uri": output_object_key,
            "source_object_uri": source_object_key,
            "weights_object_uri": _resolve_openvino_weights_object_key(output_object_key),
            "build_precision": build_precision,
            "compress_to_fp16": compress_to_fp16,
            "execution_mode": "subprocess-openvino-convert-model",
        }

    def _build_tensorrt_engine(
        self,
        *,
        source_object_key: str,
        output_object_key: str,
        build_precision: str,
    ) -> dict[str, object]:
        """把 optimized ONNX 转换为 TensorRT engine。

        参数：
        - source_object_key：来源 optimized ONNX object key。
        - output_object_key：目标 TensorRT engine object key。
        - build_precision：TensorRT engine 构建精度策略。

        返回：
        - dict[str, object]：TensorRT engine 构建摘要。
        """

        source_path = self.dataset_storage.resolve(source_object_key)
        output_path = self.dataset_storage.resolve(output_object_key)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        completed_process = run_conversion_script(
            script_file_name=_TENSORRT_ENGINE_BUILD_SCRIPT_FILE,
            args=[
                str(source_path),
                str(output_path),
                build_precision,
            ],
        )
        if completed_process.returncode != 0:
            raise ServiceConfigurationError(
                "TensorRT engine 构建失败",
                details={
                    "source_object_uri": source_object_key,
                    "output_object_uri": output_object_key,
                    "stdout": completed_process.stdout.strip(),
                    "stderr": completed_process.stderr.strip(),
                },
            )
        if not output_path.is_file():
            raise ServiceConfigurationError(
                "TensorRT engine 构建未生成 engine 产物",
                details={"output_object_uri": output_object_key},
            )
        build_summary = {
            "stage": "build-tensorrt-engine",
            "object_uri": output_object_key,
            "source_object_uri": source_object_key,
            "build_precision": build_precision,
            "execution_mode": "subprocess-tensorrt-build-engine",
            "engine_file_bytes": output_path.stat().st_size,
        }
        stdout_payload = _parse_last_json_line(completed_process.stdout)
        if stdout_payload is not None:
            build_summary.update(dict(stdout_payload))
        return build_summary


def _resolve_openvino_weights_object_key(output_object_key: str) -> str:
    """根据 OpenVINO XML object key 推导同名 bin object key。"""

    return PurePosixPath(output_object_key).with_suffix(".bin").as_posix()


def _parse_last_json_line(stdout: str) -> dict[str, object] | None:
    """从标准输出最后一个非空行解析 JSON 对象。"""

    stdout_lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not stdout_lines:
        return None
    try:
        payload = json.loads(stdout_lines[-1])
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return {str(key): value for key, value in payload.items()}
    return None
