"""YOLO 主线共享转换 worker 接口与 ONNX/OpenVINO/TensorRT 实现。"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from backend.service.application.backends import (
    ConversionBackend,
    ConversionBackendOutput,
    ConversionBackendRunRequest,
    ConversionBackendRunResult,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.workers.conversion.yolox_conversion_runner import (
    LocalYoloXConversionRunner,
    _build_conversion_options_metadata,
    _build_output_base_name,
    _import_onnx_dependencies,
    _normalize_model_outputs,
    _resolve_conversion_phase,
    _resolve_openvino_ir_build_precision,
    _summarize_numeric_validation,
    _resolve_tensorrt_engine_build_precision,
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
        "segmentation": ("predictions", "proto"),
        "pose": ("predictions",),
        "obb": ("predictions",),
    }
    task_export_mode_enabled: frozenset[str] = frozenset({"classification"})

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
        export_output_names = self._resolve_export_output_names(request.task_type)
        export_mode_enabled = self._is_export_mode_enabled(request.task_type)
        session = session_cls.load(
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
                    output_names=export_output_names,
                    export_mode_enabled=export_mode_enabled,
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
                    output_names=export_output_names,
                    export_mode_enabled=export_mode_enabled,
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

    def _resolve_export_output_names(self, task_type: str) -> tuple[str, ...]:
        """按 task_type 返回 ONNX 导出输出名列表。"""

        output_names = self.task_export_output_names.get(task_type)
        if output_names is not None:
            return tuple(output_names)
        return ("predictions",)

    def _is_export_mode_enabled(self, task_type: str) -> bool:
        """返回当前 task_type 导出时是否需要打开 export 模式。"""

        return task_type in self.task_export_mode_enabled

    def _export_onnx(
        self,
        *,
        session: object,
        output_object_key: str,
        onnx_module: object,
        output_names: tuple[str, ...],
        export_mode_enabled: bool,
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
            with _using_model_export_mode(session.model, enabled=export_mode_enabled):
                session.imports.torch.onnx.export(
                    session.model,
                    dummy_input,
                    str(output_path),
                    export_params=True,
                    opset_version=17,
                    do_constant_folding=True,
                    input_names=["images"],
                    output_names=list(output_names),
                )
        return {
            "stage": "export-onnx",
            "object_uri": output_object_key,
            "opset_version": 17,
            "input_size": list(session.runtime_target.input_size),
            "exporter_mode": "legacy-torch-onnx-export",
            "output_names": list(output_names),
            "task_type": session.runtime_target.task_type,
        }

    def _validate_onnx(
        self,
        *,
        session: object,
        onnx_object_key: str,
        onnx_module: object,
        onnxruntime_module: object,
        output_names: tuple[str, ...],
        export_mode_enabled: bool,
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
            with _using_model_export_mode(session.model, enabled=export_mode_enabled):
                torch_outputs = _normalize_model_outputs(
                    session.model(dummy_input),
                    session.imports,
                )
        ort_session = onnxruntime_module.InferenceSession(
            str(onnx_path),
            providers=["CPUExecutionProvider"],
        )
        ort_outputs = ort_session.run(
            list(output_names),
            {ort_session.get_inputs()[0].name: dummy_input.detach().cpu().numpy()},
        )
        summary = self._summarize_numeric_validation(
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

    def _summarize_numeric_validation(
        self,
        *,
        np_module: object,
        torch_outputs: list[object],
        ort_outputs: list[object],
    ) -> dict[str, object]:
        """计算 PyTorch 与 ONNX 输出的数值差异摘要。"""

        return _summarize_numeric_validation(
            np_module=np_module,
            torch_outputs=torch_outputs,
            ort_outputs=ort_outputs,
        )


def _require_runner_hook(hook_name: str, value: Any, *, model_label: str) -> Any:
    """返回共享转换 runner 要求子类提供的 hook 值。"""

    if value is None:
        raise ServiceConfigurationError(
            f"当前 {model_label} conversion runner 缺少 {hook_name} 配置",
            details={"hook_name": hook_name, "model_label": model_label},
        )
    return value


@contextmanager
def _using_model_export_mode(model: object, *, enabled: bool):
    """临时切换模型内部 export 标志，保证导出和数值校验输出语义一致。"""

    if not enabled:
        yield
        return
    toggled_modules: list[tuple[object, bool]] = []
    modules = getattr(model, "modules", None)
    if callable(modules):
        for module in modules():
            export_flag = getattr(module, "export", None)
            if isinstance(export_flag, bool):
                toggled_modules.append((module, export_flag))
                setattr(module, "export", True)
    try:
        yield
    finally:
        for module, original_value in toggled_modules:
            setattr(module, "export", original_value)
