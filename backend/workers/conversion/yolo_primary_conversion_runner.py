"""YOLO 主线共享转换 worker 接口与 ONNX/OpenVINO/TensorRT 实现。"""

from __future__ import annotations

from typing import Any

from backend.service.application.backends import (
    ConversionBackend,
    ConversionBackendOutput,
    ConversionBackendRunRequest,
    ConversionBackendRunResult,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolo_core_common.export import (
    YoloExportTaskPlan,
    build_yolo_openvino_ir,
    build_yolo_tensorrt_engine,
    build_yolo_export_task_plan,
    export_yolo_onnx,
    resolve_segmentation_export_output_names,
    validate_yolo_onnx,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.model_conversion_common import (
    build_conversion_options_metadata,
    build_output_base_name,
    import_onnx_conversion_dependencies,
    resolve_conversion_phase,
    resolve_openvino_ir_build_precision,
    resolve_tensorrt_engine_build_precision,
    run_conversion_script,
)
from backend.workers.conversion.yolox_conversion_runner import (
    LocalYoloXConversionRunner,
)


YoloPrimaryConversionRunRequest = ConversionBackendRunRequest
YoloPrimaryConversionOutput = ConversionBackendOutput
YoloPrimaryConversionRunResult = ConversionBackendRunResult
YoloPrimaryConversionRunner = ConversionBackend


class LocalYoloPrimaryConversionRunner(LocalYoloXConversionRunner):
    """使用本地文件存储执行 YOLO 主线 ONNX/OpenVINO/TensorRT 转换链。"""

    model_label = "YOLO primary"
    task_runtime_session_classes: dict[str, type] | None = None
    onnx_file_type: str | None = None
    onnx_optimized_file_type: str | None = None
    openvino_ir_file_type: str | None = None
    tensorrt_engine_file_type: str | None = None
    task_export_output_names: dict[str, tuple[str, ...]] = {
        "classification": ("probabilities",),
        "segmentation": resolve_segmentation_export_output_names(),
        "pose": ("predictions",),
        "obb": ("predictions",),
    }
    export_task_plan_builder = staticmethod(build_yolo_export_task_plan)

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化本地 YOLO 主线转换 runner。"""

        super().__init__(dataset_storage=dataset_storage)

    def run_conversion(
        self,
        request: YoloPrimaryConversionRunRequest,
    ) -> YoloPrimaryConversionRunResult:
        """执行当前已接通的 YOLO 主线 ONNX/OpenVINO/TensorRT 转换链。"""

        if not request.plan_steps:
            raise InvalidRequestError("转换计划 steps 不能为空")
        session_cls = self._resolve_task_runtime_session_cls(request.task_type)
        export_plan = self._resolve_export_task_plan(
            task_type=request.task_type,
            target_formats=request.target_formats,
        )
        session = session_cls.load(
            dataset_storage=self.dataset_storage,
            runtime_target=request.source_runtime_target,
        )
        onnx_module, onnxruntime_module, onnx_simplify = import_onnx_conversion_dependencies()
        base_name = build_output_base_name(request.source_runtime_target)
        onnx_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.onnx"
        optimized_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.optimized.onnx"
        openvino_object_key = f"{request.output_object_prefix}/artifacts/builds/{base_name}.openvino.xml"
        tensorrt_object_key = (
            f"{request.output_object_prefix}/artifacts/builds/{base_name}.tensorrt.engine"
        )
        openvino_ir_build_precision = resolve_openvino_ir_build_precision(request.metadata)
        tensorrt_engine_build_precision = resolve_tensorrt_engine_build_precision(
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
                    export_plan=export_plan,
                )
                onnx_output = YoloPrimaryConversionOutput(
                    target_format="onnx",
                    object_uri=onnx_object_key,
                    file_type=_require_runner_hook(
                        "onnx_file_type",
                        self.onnx_file_type,
                        model_label=self.model_label,
                    ),
                    metadata=export_summary,
                )
                continue
            if step.kind == "validate-onnx":
                validation_summary = self._validate_onnx(
                    session=session,
                    onnx_object_key=onnx_object_key,
                    onnx_module=onnx_module,
                    onnxruntime_module=onnxruntime_module,
                    export_plan=export_plan,
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
                    file_type=_require_runner_hook(
                        "onnx_optimized_file_type",
                        self.onnx_optimized_file_type,
                        model_label=self.model_label,
                    ),
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
                    file_type=_require_runner_hook(
                        "openvino_ir_file_type",
                        self.openvino_ir_file_type,
                        model_label=self.model_label,
                    ),
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
                    file_type=_require_runner_hook(
                        "tensorrt_engine_file_type",
                        self.tensorrt_engine_file_type,
                        model_label=self.model_label,
                    ),
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
                "phase": resolve_conversion_phase(request.target_formats),
                "executed_step_kinds": executed_step_kinds,
                "validation_summary": validation_summary,
                "conversion_options": build_conversion_options_metadata(
                    target_formats=request.target_formats,
                    openvino_ir_build_precision=openvino_ir_build_precision,
                    tensorrt_engine_build_precision=tensorrt_engine_build_precision,
                ),
                "export_plan": export_plan.to_metadata(),
            },
        )

    def _resolve_task_runtime_session_cls(self, task_type: str) -> type:
        """按 task_type 返回共享 runner 要使用的 PyTorch runtime session。"""

        task_runtime_session_classes = _require_runner_hook(
            "task_runtime_session_classes",
            self.task_runtime_session_classes,
            model_label=self.model_label,
        )
        session_cls = task_runtime_session_classes.get(task_type)
        if session_cls is None:
            raise InvalidRequestError(
                f"当前 {self.model_label} conversion runner 尚未接通指定 task_type",
                details={"task_type": task_type},
            )
        return session_cls

    def _resolve_export_task_plan(
        self,
        *,
        task_type: str,
        target_formats: tuple[str, ...],
    ) -> YoloExportTaskPlan:
        """按 task_type 返回 core 提供的导出构建计划。"""

        return self.export_task_plan_builder(
            task_type=task_type,
            target_formats=target_formats,
        )

    def _export_onnx(
        self,
        *,
        session: object,
        output_object_key: str,
        export_plan: YoloExportTaskPlan,
    ) -> dict[str, object]:
        """把 PyTorch checkpoint 导出为 ONNX。"""

        output_path = self.dataset_storage.resolve(output_object_key)
        return export_yolo_onnx(
            session=session,
            output_path=output_path,
            output_object_key=output_object_key,
            export_plan=export_plan,
        )

    def _validate_onnx(
        self,
        *,
        session: object,
        onnx_object_key: str,
        onnx_module: object,
        onnxruntime_module: object,
        export_plan: YoloExportTaskPlan,
    ) -> dict[str, object]:
        """执行 ONNX 合法性和数值校验。"""

        onnx_path = self.dataset_storage.resolve(onnx_object_key)
        return validate_yolo_onnx(
            session=session,
            onnx_path=onnx_path,
            onnx_module=onnx_module,
            onnxruntime_module=onnxruntime_module,
            export_plan=export_plan,
        )

    def _build_openvino_ir(
        self,
        *,
        source_object_key: str,
        output_object_key: str,
        build_precision: str,
    ) -> dict[str, object]:
        """把 optimized ONNX 转换为 OpenVINO IR。"""

        return build_yolo_openvino_ir(
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
        """把 optimized ONNX 转换为 TensorRT engine。"""

        return build_yolo_tensorrt_engine(
            source_path=self.dataset_storage.resolve(source_object_key),
            output_path=self.dataset_storage.resolve(output_object_key),
            source_object_key=source_object_key,
            output_object_key=output_object_key,
            build_precision=build_precision,
            run_conversion_script=run_conversion_script,
        )


def _require_runner_hook(hook_name: str, value: Any, *, model_label: str) -> Any:
    """返回共享转换 runner 要求子类提供的 hook 值。"""

    if value is None:
        raise ServiceConfigurationError(
            f"当前 {model_label} conversion runner 缺少 {hook_name} 配置",
            details={"hook_name": hook_name, "model_label": model_label},
        )
    return value


