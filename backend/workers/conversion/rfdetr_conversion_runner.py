"""RF-DETR 转换 worker 接口与 ONNX/OpenVINO/TensorRT 实现。"""

from __future__ import annotations

from backend.service.application.backends import (
    ConversionBackend,
    ConversionBackendOutput,
    ConversionBackendRunRequest,
    ConversionBackendRunResult,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.task_type_support import (
    require_supported_platform_task_type,
)
from backend.service.domain.models.model_task_types import (
    DETECTION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)
from backend.service.application.models.rfdetr_core.export.execution import (
    build_rfdetr_tensorrt_engine_artifact,
    export_rfdetr_onnx_artifact,
    import_rfdetr_onnx_conversion_dependencies,
    prepare_rfdetr_export_context,
    validate_rfdetr_onnx_artifact,
)
from backend.service.application.models.rfdetr_core.export.onnx_optimize import (
    optimize_rfdetr_onnx_model,
)
from backend.service.application.models.rfdetr_core.export.openvino import (
    build_rfdetr_openvino_ir,
)
from backend.service.application.models.catalog.rfdetr import (
    RFDETR_MODEL_FILE_TYPES,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.workers.conversion.model_conversion_common import (
    attach_conversion_output_provenance,
    build_conversion_options_metadata,
    build_conversion_output_runtime_fields,
    build_output_base_name,
    resolve_conversion_phase,
    resolve_openvino_ir_build_precision,
    resolve_tensorrt_engine_build_precision,
    write_conversion_onnx_provenance,
)


RfdetrConversionRunRequest = ConversionBackendRunRequest
RfdetrConversionOutput = ConversionBackendOutput
RfdetrConversionRunResult = ConversionBackendRunResult
RfdetrConversionRunner = ConversionBackend

RFDETR_ONNX_FILE = RFDETR_MODEL_FILE_TYPES.onnx_file_type
RFDETR_ONNX_OPTIMIZED_FILE = RFDETR_MODEL_FILE_TYPES.onnx_optimized_file_type
RFDETR_OPENVINO_IR_FILE = RFDETR_MODEL_FILE_TYPES.openvino_ir_file_type
RFDETR_TENSORRT_ENGINE_FILE = RFDETR_MODEL_FILE_TYPES.tensorrt_engine_file_type


class LocalRfdetrConversionRunner(ConversionBackend):
    """本地 RF-DETR 转换执行器。"""

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化 RF-DETR 转换执行器。"""

        self.dataset_storage = dataset_storage

    def run_conversion(
        self,
        request: RfdetrConversionRunRequest,
    ) -> RfdetrConversionRunResult:
        """执行 RF-DETR ONNX/OpenVINO/TensorRT 转换链。"""

        if not request.plan_steps:
            raise InvalidRequestError("转换计划 steps 不能为空")
        metadata = dict(request.metadata or {})
        task_type = require_supported_platform_task_type(
            metadata.get("task_type") or request.task_type,
            empty_message="RF-DETR conversion 必须显式传 task_type",
            unsupported_message="RF-DETR conversion 收到了不支持的 task_type",
        )
        if task_type not in {DETECTION_TASK_TYPE, SEGMENTATION_TASK_TYPE}:
            raise InvalidRequestError(
                "RF-DETR conversion 当前只支持 detection 和 segmentation",
                details={
                    "task_type": task_type,
                    "supported": [DETECTION_TASK_TYPE, SEGMENTATION_TASK_TYPE],
                },
            )

        runtime_target = request.source_runtime_target
        export_context = prepare_rfdetr_export_context(
            checkpoint_path=runtime_target.checkpoint_path,
            task_type=task_type,
            model_scale=runtime_target.model_scale,
            num_classes=len(runtime_target.labels),
            input_size=runtime_target.input_size,
        )
        onnx_module, onnxruntime_module, onnx_simplify = (
            import_rfdetr_onnx_conversion_dependencies()
        )
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
        executed_step_kinds: list[str] = []
        validation_summary: dict[str, object] = {}
        onnx_output: RfdetrConversionOutput | None = None
        optimized_output: RfdetrConversionOutput | None = None
        openvino_output: RfdetrConversionOutput | None = None
        tensorrt_output: RfdetrConversionOutput | None = None

        for step in request.plan_steps:
            executed_step_kinds.append(step.kind)
            if step.kind == "export-onnx":
                export_summary = export_rfdetr_onnx_artifact(
                    model=export_context.model,
                    dummy_input=export_context.dummy_input,
                    output_path=self.dataset_storage.resolve(onnx_object_key),
                    output_object_key=onnx_object_key,
                    output_names=export_context.output_names,
                )
                write_conversion_onnx_provenance(
                    onnx_module=onnx_module,
                    model_path=self.dataset_storage.resolve(onnx_object_key),
                    conversion_task_id=request.conversion_task_id,
                    source_model_version_id=runtime_target.model_version_id,
                    target_format="onnx",
                )
                runtime_fields = build_conversion_output_runtime_fields(target_format="onnx")
                onnx_output = RfdetrConversionOutput(
                    target_format="onnx",
                    object_uri=onnx_object_key,
                    file_type=RFDETR_ONNX_FILE,
                    runtime_backend=runtime_fields["runtime_backend"],
                    runtime_precision=runtime_fields["runtime_precision"],
                    metadata={
                        **export_summary,
                        **runtime_fields,
                    },
                )
                continue
            if step.kind == "validate-onnx":
                validation_summary = validate_rfdetr_onnx_artifact(
                    model=export_context.model,
                    dummy_input=export_context.dummy_input,
                    onnx_path=self.dataset_storage.resolve(onnx_object_key),
                    onnx_module=onnx_module,
                    onnxruntime_module=onnxruntime_module,
                    output_names=export_context.output_names,
                )
                if onnx_output is not None:
                    onnx_output = RfdetrConversionOutput(
                        target_format=onnx_output.target_format,
                        object_uri=onnx_output.object_uri,
                        file_type=onnx_output.file_type,
                        runtime_backend=onnx_output.runtime_backend,
                        runtime_precision=onnx_output.runtime_precision,
                        metadata={
                            **onnx_output.metadata,
                            "validation_summary": validation_summary,
                        },
                    )
                continue
            if step.kind == "optimize-onnx":
                if onnx_output is None:
                    raise ServiceConfigurationError("optimize-onnx 缺少 export-onnx 输出")
                optimize_summary = optimize_rfdetr_onnx_model(
                    source_path=self.dataset_storage.resolve(onnx_object_key),
                    optimized_path=self.dataset_storage.resolve(optimized_object_key),
                    source_object_key=onnx_object_key,
                    output_object_key=optimized_object_key,
                    onnx_module=onnx_module,
                    onnx_simplify=onnx_simplify,
                )
                write_conversion_onnx_provenance(
                    onnx_module=onnx_module,
                    model_path=self.dataset_storage.resolve(
                        optimized_object_key
                    ),
                    conversion_task_id=request.conversion_task_id,
                    source_model_version_id=runtime_target.model_version_id,
                    target_format="onnx-optimized",
                )
                runtime_fields = build_conversion_output_runtime_fields(target_format="onnx-optimized")
                optimized_output = RfdetrConversionOutput(
                    target_format="onnx-optimized",
                    object_uri=optimized_object_key,
                    file_type=RFDETR_ONNX_OPTIMIZED_FILE,
                    runtime_backend=runtime_fields["runtime_backend"],
                    runtime_precision=runtime_fields["runtime_precision"],
                    metadata={
                        **optimize_summary,
                        **runtime_fields,
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
                runtime_fields = build_conversion_output_runtime_fields(
                    target_format="openvino-ir",
                    build_precision=openvino_ir_build_precision,
                )
                openvino_output = RfdetrConversionOutput(
                    target_format="openvino-ir",
                    object_uri=openvino_object_key,
                    file_type=RFDETR_OPENVINO_IR_FILE,
                    runtime_backend=runtime_fields["runtime_backend"],
                    runtime_precision=runtime_fields["runtime_precision"],
                    metadata={
                        **build_summary,
                        **runtime_fields,
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
                runtime_fields = build_conversion_output_runtime_fields(
                    target_format="tensorrt-engine",
                    build_precision=tensorrt_engine_build_precision,
                )
                tensorrt_output = RfdetrConversionOutput(
                    target_format="tensorrt-engine",
                    object_uri=tensorrt_object_key,
                    file_type=RFDETR_TENSORRT_ENGINE_FILE,
                    runtime_backend=runtime_fields["runtime_backend"],
                    runtime_precision=runtime_fields["runtime_precision"],
                    metadata={
                        **build_summary,
                        **runtime_fields,
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
        traced_outputs = tuple(
            attach_conversion_output_provenance(
                output,
                conversion_task_id=request.conversion_task_id,
                source_model_version_id=runtime_target.model_version_id,
            )
            for output in outputs
        )
        return RfdetrConversionRunResult(
            conversion_task_id=request.conversion_task_id,
            outputs=traced_outputs,
            metadata={
                "phase": resolve_conversion_phase(request.target_formats),
                "executed_step_kinds": executed_step_kinds,
                "input_size": export_context.input_size_summary,
                "validation_summary": validation_summary,
                "conversion_options": build_conversion_options_metadata(
                    target_formats=request.target_formats,
                    openvino_ir_build_precision=openvino_ir_build_precision,
                    tensorrt_engine_build_precision=tensorrt_engine_build_precision,
                ),
            },
        )

    def _build_openvino_ir(
        self,
        *,
        source_object_key: str,
        output_object_key: str,
        build_precision: str,
    ) -> dict[str, object]:
        """通过 RF-DETR core OpenVINO builder 生成 IR。"""

        return build_rfdetr_openvino_ir(
            source_path=self.dataset_storage.resolve(source_object_key),
            output_path=self.dataset_storage.resolve(output_object_key),
            source_object_key=source_object_key,
            output_object_key=output_object_key,
            build_precision=build_precision,
        )

    def _build_tensorrt_engine(
        self,
        *,
        source_object_key: str,
        output_object_key: str,
        build_precision: str,
    ) -> dict[str, object]:
        """通过 RF-DETR core TensorRT builder 生成 engine。"""

        return build_rfdetr_tensorrt_engine_artifact(
            source_path=self.dataset_storage.resolve(source_object_key),
            output_path=self.dataset_storage.resolve(output_object_key),
            source_object_key=source_object_key,
            output_object_key=output_object_key,
            build_precision=build_precision,
        )
