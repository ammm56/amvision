"""pose 模型运行时加载器与注册表。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.model_type_support import (
    normalize_optional_platform_model_type,
)
from backend.service.application.runtime.pose_runtime_contracts import (
    PosePredictionExecutionResult,
    PosePredictionRequest,
)
from backend.service.application.runtime.predictors.yolo11_pose import (
    OnnxRuntimeYolo11PoseRuntimeSession,
    OpenVINOYolo11PoseRuntimeSession,
    PyTorchYolo11PoseRuntimeSession,
    TensorRTYolo11PoseRuntimeSession,
)
from backend.service.application.runtime.yolo26_pose_predictor import (
    OnnxRuntimeYolo26PoseRuntimeSession,
    OpenVINOYolo26PoseRuntimeSession,
    PyTorchYolo26PoseRuntimeSession,
    TensorRTYolo26PoseRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8_pose import (
    OnnxRuntimeYoloV8PoseRuntimeSession,
    OpenVINOYoloV8PoseRuntimeSession,
    PyTorchYoloV8PoseRuntimeSession,
    TensorRTYoloV8PoseRuntimeSession,
)
from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


PoseRuntimeLoader = Callable[
    [LocalDatasetStorage, RuntimeTargetSnapshot, bool | None, int | None],
    "PoseModelRuntimeSession",
]


class PoseModelRuntimeSession(Protocol):
    def predict(
        self, request: PosePredictionRequest
    ) -> PosePredictionExecutionResult: ...


@dataclass
class PoseModelRuntimeRegistry:
    runtime_loaders: dict[str, PoseRuntimeLoader] = field(default_factory=dict)

    def register_runtime_loader(
        self, model_type: str, loader: PoseRuntimeLoader
    ) -> None:
        normalized_model_type = _normalize_model_type(model_type)
        if normalized_model_type is None:
            raise ServiceConfigurationError(
                "登记 pose runtime loader 时 model_type 不能为空"
            )
        self.runtime_loaders[normalized_model_type] = loader

    def resolve_runtime_loader(self, model_type: str) -> PoseRuntimeLoader:
        normalized_model_type = _normalize_model_type(model_type)
        if normalized_model_type is None:
            raise ServiceConfigurationError("当前 pose runtime 缺少有效 model_type")
        runtime_loader = self.runtime_loaders.get(normalized_model_type)
        if runtime_loader is None:
            raise ServiceConfigurationError(
                "当前 pose runtime 尚未接通该模型分类",
                details={"model_type": normalized_model_type},
            )
        return runtime_loader


class DefaultPoseModelRuntime:
    def __init__(
        self, runtime_registry: PoseModelRuntimeRegistry | None = None
    ) -> None:
        self.runtime_registry = (
            runtime_registry or build_default_pose_model_runtime_registry()
        )

    def load_session(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        pinned_output_buffer_enabled: bool | None = None,
        pinned_output_buffer_max_bytes: int | None = None,
    ) -> PoseModelRuntimeSession:
        runtime_loader = self.runtime_registry.resolve_runtime_loader(
            runtime_target.model_type
        )
        return runtime_loader(
            dataset_storage,
            runtime_target,
            pinned_output_buffer_enabled,
            pinned_output_buffer_max_bytes,
        )


def build_default_pose_model_runtime_registry() -> PoseModelRuntimeRegistry:
    registry = PoseModelRuntimeRegistry()
    registry.register_runtime_loader("yolov8", _load_yolov8_pose_session)
    registry.register_runtime_loader("yolo11", _load_yolo11_pose_session)
    registry.register_runtime_loader("yolo26", _load_yolo26_pose_session)
    return registry


def _load_yolov8_pose_session(
    dataset_storage,
    runtime_target,
    pinned_output_buffer_enabled,
    pinned_output_buffer_max_bytes,
):
    if runtime_target.runtime_backend == "pytorch":
        return PyTorchYoloV8PoseRuntimeSession.load(
            dataset_storage=dataset_storage, runtime_target=runtime_target
        )
    if runtime_target.runtime_backend == "onnxruntime":
        return OnnxRuntimeYoloV8PoseRuntimeSession.load(
            dataset_storage=dataset_storage, runtime_target=runtime_target
        )
    if runtime_target.runtime_backend == "openvino":
        return OpenVINOYoloV8PoseRuntimeSession.load(
            dataset_storage=dataset_storage, runtime_target=runtime_target
        )
    if runtime_target.runtime_backend == "tensorrt":
        return TensorRTYoloV8PoseRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            pinned_output_buffer_enabled=pinned_output_buffer_enabled,
            pinned_output_buffer_max_bytes=pinned_output_buffer_max_bytes,
        )
    raise ValueError(
        f"unsupported pose runtime backend: {runtime_target.runtime_backend}"
    )


def _load_yolo11_pose_session(
    dataset_storage,
    runtime_target,
    pinned_output_buffer_enabled,
    pinned_output_buffer_max_bytes,
):
    if runtime_target.runtime_backend == "pytorch":
        return PyTorchYolo11PoseRuntimeSession.load(
            dataset_storage=dataset_storage, runtime_target=runtime_target
        )
    if runtime_target.runtime_backend == "onnxruntime":
        return OnnxRuntimeYolo11PoseRuntimeSession.load(
            dataset_storage=dataset_storage, runtime_target=runtime_target
        )
    if runtime_target.runtime_backend == "openvino":
        return OpenVINOYolo11PoseRuntimeSession.load(
            dataset_storage=dataset_storage, runtime_target=runtime_target
        )
    if runtime_target.runtime_backend == "tensorrt":
        return TensorRTYolo11PoseRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            pinned_output_buffer_enabled=pinned_output_buffer_enabled,
            pinned_output_buffer_max_bytes=pinned_output_buffer_max_bytes,
        )
    raise ValueError(
        f"unsupported pose runtime backend: {runtime_target.runtime_backend}"
    )


def _load_yolo26_pose_session(
    dataset_storage,
    runtime_target,
    pinned_output_buffer_enabled,
    pinned_output_buffer_max_bytes,
):
    if runtime_target.runtime_backend == "pytorch":
        return PyTorchYolo26PoseRuntimeSession.load(
            dataset_storage=dataset_storage, runtime_target=runtime_target
        )
    if runtime_target.runtime_backend == "onnxruntime":
        return OnnxRuntimeYolo26PoseRuntimeSession.load(
            dataset_storage=dataset_storage, runtime_target=runtime_target
        )
    if runtime_target.runtime_backend == "openvino":
        return OpenVINOYolo26PoseRuntimeSession.load(
            dataset_storage=dataset_storage, runtime_target=runtime_target
        )
    if runtime_target.runtime_backend == "tensorrt":
        return TensorRTYolo26PoseRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            pinned_output_buffer_enabled=pinned_output_buffer_enabled,
            pinned_output_buffer_max_bytes=pinned_output_buffer_max_bytes,
        )
    raise ValueError(
        f"unsupported pose runtime backend: {runtime_target.runtime_backend}"
    )


def _normalize_model_type(model_type: str | None) -> str | None:
    return normalize_optional_platform_model_type(model_type)
