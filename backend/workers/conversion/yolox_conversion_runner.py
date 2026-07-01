"""YOLOX 转换 worker 接口。"""

from __future__ import annotations

from backend.service.application.backends import (
    ConversionBackend,
    ConversionBackendOutput,
    ConversionBackendRunRequest,
    ConversionBackendRunResult,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolox_core.export import (
    YoloXExportSession,
    build_yolox_openvino_ir,
    build_yolox_tensorrt_engine,
    export_yolox_onnx,
    load_yolox_export_session,
    optimize_yolox_onnx,
    validate_yolox_onnx,
)
from backend.service.domain.files.yolox_file_types import (
    YOLOX_ONNX_FILE,
    YOLOX_ONNX_OPTIMIZED_FILE,
    YOLOX_OPENVINO_IR_FILE,
    YOLOX_TENSORRT_ENGINE_FILE,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.model_conversion_common import (
    build_conversion_options_metadata,
    build_conversion_output_runtime_fields,
    build_output_base_name,
    import_onnx_conversion_dependencies,
    resolve_conversion_phase,
    resolve_openvino_ir_build_precision,
    resolve_tensorrt_engine_build_precision,
    run_conversion_script,
)


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
        session = load_yolox_export_session(
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
                )
                runtime_fields = build_conversion_output_runtime_fields(target_format="onnx")
                onnx_output = YoloXConversionOutput(
                    target_format="onnx",
                    object_uri=onnx_object_key,
                    file_type=YOLOX_ONNX_FILE,
                    runtime_backend=runtime_fields["runtime_backend"],
                    runtime_precision=runtime_fields["runtime_precision"],
                    metadata={
                        **export_summary,
                        **runtime_fields,
                    },
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
                        runtime_backend=onnx_output.runtime_backend,
                        runtime_precision=onnx_output.runtime_precision,
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
                runtime_fields = build_conversion_output_runtime_fields(target_format="onnx-optimized")
                optimized_output = YoloXConversionOutput(
                    target_format="onnx-optimized",
                    object_uri=optimized_object_key,
                    file_type=YOLOX_ONNX_OPTIMIZED_FILE,
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
                    raise ServiceConfigurationError("build-openvino-ir 缺少 optimize-onnx 输出")
                build_summary = self._build_openvino_ir(
                    source_object_key=optimized_object_key,
                    output_object_key=openvino_object_key,
                    build_precision=openvino_ir_build_precision,
                )
                runtime_fields = build_conversion_output_runtime_fields(
                    target_format="openvino-ir",
                    build_precision=openvino_ir_build_precision,
                )
                openvino_output = YoloXConversionOutput(
                    target_format="openvino-ir",
                    object_uri=openvino_object_key,
                    file_type=YOLOX_OPENVINO_IR_FILE,
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
                    raise ServiceConfigurationError("build-tensorrt-engine 缺少 optimize-onnx 输出")
                build_summary = self._build_tensorrt_engine(
                    source_object_key=optimized_object_key,
                    output_object_key=tensorrt_object_key,
                    build_precision=tensorrt_engine_build_precision,
                )
                runtime_fields = build_conversion_output_runtime_fields(
                    target_format="tensorrt-engine",
                    build_precision=tensorrt_engine_build_precision,
                )
                tensorrt_output = YoloXConversionOutput(
                    target_format="tensorrt-engine",
                    object_uri=tensorrt_object_key,
                    file_type=YOLOX_TENSORRT_ENGINE_FILE,
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
        session: YoloXExportSession,
        output_object_key: str,
    ) -> dict[str, object]:
        """把 PyTorch checkpoint 导出为 ONNX。"""

        output_path = self.dataset_storage.resolve(output_object_key)
        return export_yolox_onnx(
            session=session,
            output_path=output_path,
            output_object_key=output_object_key,
        )

    def _validate_onnx(
        self,
        *,
        session: YoloXExportSession,
        onnx_object_key: str,
        onnx_module: object,
        onnxruntime_module: object,
    ) -> dict[str, object]:
        """执行 ONNX 合法性和数值校验。"""

        onnx_path = self.dataset_storage.resolve(onnx_object_key)
        return validate_yolox_onnx(
            session=session,
            onnx_path=onnx_path,
            onnx_module=onnx_module,
            onnxruntime_module=onnxruntime_module,
        )

    def _optimize_onnx(
        self,
        *,
        source_object_key: str,
        output_object_key: str,
        onnx_module: object,
        onnx_simplify: object,
    ) -> dict[str, object]:
        """执行 ONNX 简化优化并写回独立输出。"""

        return optimize_yolox_onnx(
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

        return build_yolox_openvino_ir(
            source_path=self.dataset_storage.resolve(source_object_key),
            output_path=self.dataset_storage.resolve(output_object_key),
            source_object_key=source_object_key,
            output_object_key=output_object_key,
            build_precision=build_precision,
            run_conversion_script=run_conversion_script,
        )

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

        return build_yolox_tensorrt_engine(
            source_path=self.dataset_storage.resolve(source_object_key),
            output_path=self.dataset_storage.resolve(output_object_key),
            source_object_key=source_object_key,
            output_object_key=output_object_key,
            build_precision=build_precision,
            run_conversion_script=run_conversion_script,
        )
