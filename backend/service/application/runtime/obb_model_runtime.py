"""obb 模型运行时加载器与注册表。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.model_type_support import (
    normalize_optional_platform_model_type,
)
from backend.service.application.runtime.obb_runtime_contracts import (
    ObbPredictionExecutionResult,
    ObbPredictionRequest,
)
from backend.service.application.runtime.yolo11_obb_predictor import (
    OnnxRuntimeYolo11ObbRuntimeSession,
    OpenVINOYolo11ObbRuntimeSession,
    PyTorchYolo11ObbRuntimeSession,
    TensorRTYolo11ObbRuntimeSession,
)
from backend.service.application.runtime.yolo26_obb_predictor import (
    OnnxRuntimeYolo26ObbRuntimeSession,
    OpenVINOYolo26ObbRuntimeSession,
    PyTorchYolo26ObbRuntimeSession,
    TensorRTYolo26ObbRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8_obb import (
    OnnxRuntimeYoloV8ObbRuntimeSession,
    OpenVINOYoloV8ObbRuntimeSession,
    PyTorchYoloV8ObbRuntimeSession,
    TensorRTYoloV8ObbRuntimeSession,
)
from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


ObbRuntimeLoader = Callable[
    [LocalDatasetStorage, RuntimeTargetSnapshot, bool | None, int | None],
    "ObbModelRuntimeSession",
]


class ObbModelRuntimeSession(Protocol):
    def predict(self, request: ObbPredictionRequest) -> ObbPredictionExecutionResult:
        ...


@dataclass
class ObbModelRuntimeRegistry:
    runtime_loaders: dict[str, ObbRuntimeLoader] = field(default_factory=dict)

    def register_runtime_loader(self, model_type, loader):
        normalized_model_type = _normalize_model_type(model_type)
        if normalized_model_type is None:
            raise ServiceConfigurationError("登记 obb runtime loader 时 model_type 不能为空")
        self.runtime_loaders[normalized_model_type] = loader

    def resolve_runtime_loader(self, model_type):
        normalized_model_type = _normalize_model_type(model_type)
        if normalized_model_type is None:
            raise ServiceConfigurationError("当前 obb runtime 缺少有效 model_type")
        loader = self.runtime_loaders.get(normalized_model_type)
        if loader is None:
            raise ServiceConfigurationError(
                "当前 obb runtime 尚未接通该模型分类",
                details={"model_type": normalized_model_type},
            )
        return loader


class DefaultObbModelRuntime:
    def __init__(self, runtime_registry=None):
        self.runtime_registry = runtime_registry or build_default_obb_model_runtime_registry()

    def load_session(
        self,
        *,
        dataset_storage,
        runtime_target,
        pinned_output_buffer_enabled=None,
        pinned_output_buffer_max_bytes=None,
    ):
        loader = self.runtime_registry.resolve_runtime_loader(runtime_target.model_type)
        return loader(
            dataset_storage,
            runtime_target,
            pinned_output_buffer_enabled,
            pinned_output_buffer_max_bytes,
        )


def build_default_obb_model_runtime_registry():
    registry = ObbModelRuntimeRegistry()
    registry.register_runtime_loader("yolov8", _load_yolov8_obb)
    registry.register_runtime_loader("yolo11", _load_yolo11_obb)
    registry.register_runtime_loader("yolo26", _load_yolo26_obb)
    return registry


def _load_yolov8_obb(ds, rt, pe, pm):
    if rt.runtime_backend == "pytorch":
        return PyTorchYoloV8ObbRuntimeSession.load(dataset_storage=ds, runtime_target=rt)
    if rt.runtime_backend == "onnxruntime":
        return OnnxRuntimeYoloV8ObbRuntimeSession.load(dataset_storage=ds, runtime_target=rt)
    if rt.runtime_backend == "openvino":
        return OpenVINOYoloV8ObbRuntimeSession.load(dataset_storage=ds, runtime_target=rt)
    if rt.runtime_backend == "tensorrt":
        return TensorRTYoloV8ObbRuntimeSession.load(
            dataset_storage=ds,
            runtime_target=rt,
            pinned_output_buffer_enabled=pe,
            pinned_output_buffer_max_bytes=pm,
        )
    raise ValueError(f"unsupported obb runtime backend: {rt.runtime_backend}")


def _load_yolo11_obb(ds, rt, pe, pm):
    if rt.runtime_backend == "pytorch":
        return PyTorchYolo11ObbRuntimeSession.load(dataset_storage=ds, runtime_target=rt)
    if rt.runtime_backend == "onnxruntime":
        return OnnxRuntimeYolo11ObbRuntimeSession.load(dataset_storage=ds, runtime_target=rt)
    if rt.runtime_backend == "openvino":
        return OpenVINOYolo11ObbRuntimeSession.load(dataset_storage=ds, runtime_target=rt)
    if rt.runtime_backend == "tensorrt":
        return TensorRTYolo11ObbRuntimeSession.load(
            dataset_storage=ds,
            runtime_target=rt,
            pinned_output_buffer_enabled=pe,
            pinned_output_buffer_max_bytes=pm,
        )
    raise ValueError(f"unsupported obb runtime backend: {rt.runtime_backend}")


def _load_yolo26_obb(ds, rt, pe, pm):
    if rt.runtime_backend == "pytorch":
        return PyTorchYolo26ObbRuntimeSession.load(dataset_storage=ds, runtime_target=rt)
    if rt.runtime_backend == "onnxruntime":
        return OnnxRuntimeYolo26ObbRuntimeSession.load(dataset_storage=ds, runtime_target=rt)
    if rt.runtime_backend == "openvino":
        return OpenVINOYolo26ObbRuntimeSession.load(dataset_storage=ds, runtime_target=rt)
    if rt.runtime_backend == "tensorrt":
        return TensorRTYolo26ObbRuntimeSession.load(
            dataset_storage=ds,
            runtime_target=rt,
            pinned_output_buffer_enabled=pe,
            pinned_output_buffer_max_bytes=pm,
        )
    raise ValueError(f"unsupported obb runtime backend: {rt.runtime_backend}")


def _normalize_model_type(model_type):
    return normalize_optional_platform_model_type(model_type)
