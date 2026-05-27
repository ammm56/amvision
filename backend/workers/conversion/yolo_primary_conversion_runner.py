"""YOLO 主线 detection 转换 worker 接口与 ONNX/OpenVINO/TensorRT 实现。"""

from __future__ import annotations

from backend.service.application.backends import (
    ConversionBackend,
    ConversionBackendOutput,
    ConversionBackendRunRequest,
    ConversionBackendRunResult,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.runtime.yolo_primary_predictor import (
    PyTorchYoloPrimaryRuntimeSession,
)
from backend.service.domain.files.yolov8_file_types import (
    YOLOV8_ONNX_FILE,
    YOLOV8_ONNX_OPTIMIZED_FILE,
    YOLOV8_OPENVINO_IR_FILE,
    YOLOV8_TENSORRT_ENGINE_FILE,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.yolox_conversion_runner import (
    LocalYoloXConversionRunner,
    _build_conversion_options_metadata,
    _build_output_base_name,
    _import_onnx_dependencies,
    _resolve_conversion_phase,
    _resolve_openvino_ir_build_precision,
    _resolve_tensorrt_engine_build_precision,
)


YoloPrimaryConversionRunRequest = ConversionBackendRunRequest
YoloPrimaryConversionOutput = ConversionBackendOutput
YoloPrimaryConversionRunResult = ConversionBackendRunResult
YoloPrimaryConversionRunner = ConversionBackend


class LocalYoloPrimaryConversionRunner(LocalYoloXConversionRunner):
    """使用本地文件存储执行 YOLO 主线 ONNX/OpenVINO/TensorRT 转换链。"""

    model_label = "YOLOv8"
    pytorch_runtime_session_cls = PyTorchYoloPrimaryRuntimeSession
    onnx_file_type = YOLOV8_ONNX_FILE
    onnx_optimized_file_type = YOLOV8_ONNX_OPTIMIZED_FILE
    openvino_ir_file_type = YOLOV8_OPENVINO_IR_FILE
    tensorrt_engine_file_type = YOLOV8_TENSORRT_ENGINE_FILE

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化本地 YOLOv8 转换 runner。"""

        super().__init__(dataset_storage=dataset_storage)

    def run_conversion(
        self,
        request: YoloPrimaryConversionRunRequest,
    ) -> YoloPrimaryConversionRunResult:
        """执行当前已接通的 YOLO 主线 ONNX/OpenVINO/TensorRT 转换链。"""

        if not request.plan_steps:
            raise InvalidRequestError("转换计划 steps 不能为空")
        session = self.pytorch_runtime_session_cls.load(
            dataset_storage=self.dataset_storage,
            runtime_target=request.source_runtime_target,
        )
        onnx_module, onnxruntime_module, onnx_simplify = _import_onnx_dependencies()
        base_name = _build_output_base_name(request.source_runtime_target)
        onnx_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.onnx"
        optimized_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.optimized.onnx"
        openvino_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.openvino.xml"
        tensorrt_object_key = (
            f"{request.output_object_prefix}/artifacts/builds/{base_name}.tensorrt.engine"
        )
        openvino_ir_build_precision = _resolve_openvino_ir_build_precision(request.metadata)
        tensorrt_engine_build_precision = _resolve_tensorrt_engine_build_precision(
            request.metadata
        )
        executed_step_kinds: list[str] = []
        validation_summary: dict[str, object] = {}
        onnx_output: YoloPrimaryConversionOutput | None = None
        optimized_output: YoloPrimaryConversionOutput | None = None
        openvino_output: YoloPrimaryConversionOutput | None = None
        tensorrt_output: YoloPrimaryConversionOutput | None = None

        for step in request.plan_steps:
            executed_step_kinds.append(step.kind)
            if step.kind == "export-onnx":
                export_summary = self._export_onnx(
                    session=session,
                    output_object_key=onnx_object_key,
                    onnx_module=onnx_module,
                )
                onnx_output = YoloPrimaryConversionOutput(
                    target_format="onnx",
                    object_uri=onnx_object_key,
                    file_type=self.onnx_file_type,
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
                    onnx_output = YoloPrimaryConversionOutput(
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
                optimized_output = YoloPrimaryConversionOutput(
                    target_format="onnx-optimized",
                    object_uri=optimized_object_key,
                    file_type=self.onnx_optimized_file_type,
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
                openvino_output = YoloPrimaryConversionOutput(
                    target_format="openvino-ir",
                    object_uri=openvino_object_key,
                    file_type=self.openvino_ir_file_type,
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
                tensorrt_output = YoloPrimaryConversionOutput(
                    target_format="tensorrt-engine",
                    object_uri=tensorrt_object_key,
                    file_type=self.tensorrt_engine_file_type,
                    metadata={
                        **build_summary,
                        "validation_summary": validation_summary,
                        "source_object_uri": optimized_object_key,
                    },
                )
                continue
            raise InvalidRequestError(
                f"当前 {self.model_label} conversion runner 不支持指定步骤",
                details={"step_kind": step.kind},
            )

        outputs: list[YoloPrimaryConversionOutput] = []
        if onnx_output is not None:
            outputs.append(onnx_output)
        if optimized_output is not None:
            outputs.append(optimized_output)
        if openvino_output is not None:
            outputs.append(openvino_output)
        if tensorrt_output is not None:
            outputs.append(tensorrt_output)
        return YoloPrimaryConversionRunResult(
            conversion_task_id=request.conversion_task_id,
            outputs=tuple(outputs),
            metadata={
                "phase": _resolve_conversion_phase(request.target_formats),
                "executed_step_kinds": executed_step_kinds,
                "validation_summary": validation_summary,
                "conversion_options": _build_conversion_options_metadata(
                    target_formats=request.target_formats,
                    openvino_ir_build_precision=openvino_ir_build_precision,
                    tensorrt_engine_build_precision=tensorrt_engine_build_precision,
                ),
            },
        )
