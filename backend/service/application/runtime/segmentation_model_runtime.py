"""segmentation 模型运行时加载器与注册表。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.runtime.segmentation_runtime_contracts import (
    SegmentationPredictionExecutionResult,
    SegmentationPredictionRequest,
)
from backend.service.application.runtime.yolo11_segmentation_predictor import (
    OnnxRuntimeYolo11SegmentationRuntimeSession,
    OpenVINOYolo11SegmentationRuntimeSession,
    PyTorchYolo11SegmentationRuntimeSession,
    TensorRTYolo11SegmentationRuntimeSession,
)
from backend.service.application.runtime.yolo26_segmentation_predictor import (
    OnnxRuntimeYolo26SegmentationRuntimeSession,
    OpenVINOYolo26SegmentationRuntimeSession,
    PyTorchYolo26SegmentationRuntimeSession,
    TensorRTYolo26SegmentationRuntimeSession,
)
from backend.service.application.runtime.yolov8_segmentation_predictor import (
    OnnxRuntimeYoloV8SegmentationRuntimeSession,
    OpenVINOYoloV8SegmentationRuntimeSession,
    PyTorchYoloV8SegmentationRuntimeSession,
    TensorRTYoloV8SegmentationRuntimeSession,
)
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


SegmentationRuntimeLoader = Callable[
    [LocalDatasetStorage, RuntimeTargetSnapshot, bool | None, int | None],
    "SegmentationModelRuntimeSession",
]


class SegmentationModelRuntimeSession(Protocol):
    """定义 segmentation 模型会话需要满足的最小协议。"""

    def predict(self, request: SegmentationPredictionRequest) -> SegmentationPredictionExecutionResult:
        """执行一次 segmentation 预测并返回结果。"""

        ...


class SegmentationModelRuntime(Protocol):
    """定义 segmentation 模型运行时加载器需要满足的最小协议。"""

    def load_session(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        pinned_output_buffer_enabled: bool | None = None,
        pinned_output_buffer_max_bytes: int | None = None,
    ) -> SegmentationModelRuntimeSession:
        """按运行时快照加载 segmentation 模型会话。"""

        ...


@dataclass
class SegmentationModelRuntimeRegistry:
    """按模型分类管理 segmentation 运行时加载器。"""

    runtime_loaders: dict[str, SegmentationRuntimeLoader] = field(default_factory=dict)

    def register_runtime_loader(self, model_type: str, loader: SegmentationRuntimeLoader) -> None:
        """登记指定模型分类对应的 segmentation 运行时加载器。"""

        normalized_model_type = _normalize_model_type(model_type)
        if normalized_model_type is None:
            raise ServiceConfigurationError("登记 segmentation runtime loader 时 model_type 不能为空")
        self.runtime_loaders[normalized_model_type] = loader

    def resolve_runtime_loader(self, model_type: str) -> SegmentationRuntimeLoader:
        """按模型分类解析 segmentation 运行时加载器。"""

        normalized_model_type = _normalize_model_type(model_type)
        if normalized_model_type is None:
            raise ServiceConfigurationError("当前 segmentation runtime 缺少有效 model_type")
        runtime_loader = self.runtime_loaders.get(normalized_model_type)
        if runtime_loader is None:
            raise ServiceConfigurationError(
                "当前 segmentation runtime 尚未接通该模型分类",
                details={"model_type": normalized_model_type},
            )
        return runtime_loader


class DefaultSegmentationModelRuntime:
    """根据模型分类与 runtime backend 分发 segmentation 会话加载。"""

    def __init__(self, runtime_registry: SegmentationModelRuntimeRegistry | None = None) -> None:
        """初始化 segmentation 运行时加载器。"""

        self.runtime_registry = runtime_registry or build_default_segmentation_model_runtime_registry()

    def load_session(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        pinned_output_buffer_enabled: bool | None = None,
        pinned_output_buffer_max_bytes: int | None = None,
    ) -> SegmentationModelRuntimeSession:
        """按模型分类和 runtime backend 加载 segmentation 模型会话。"""

        runtime_loader = self.runtime_registry.resolve_runtime_loader(runtime_target.model_type)
        return runtime_loader(dataset_storage, runtime_target, pinned_output_buffer_enabled, pinned_output_buffer_max_bytes)


def build_default_segmentation_model_runtime_registry() -> SegmentationModelRuntimeRegistry:
    """构建当前进程默认使用的 segmentation runtime 注册表。"""

    registry = SegmentationModelRuntimeRegistry()
    registry.register_runtime_loader("yolov8", _load_yolov8_segmentation_session)
    registry.register_runtime_loader("yolo11", _load_yolo11_segmentation_session)
    registry.register_runtime_loader("yolo26", _load_yolo26_segmentation_session)
    return registry


def _load_yolov8_segmentation_session(
    dataset_storage: LocalDatasetStorage,
    runtime_target: RuntimeTargetSnapshot,
    pinned_output_buffer_enabled: bool | None,
    pinned_output_buffer_max_bytes: int | None,
) -> SegmentationModelRuntimeSession:
    """按 runtime backend 加载当前已接通的 YOLOv8 segmentation 会话。"""

    if runtime_target.runtime_backend == "pytorch":
        return PyTorchYoloV8SegmentationRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "onnxruntime":
        return OnnxRuntimeYoloV8SegmentationRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "openvino":
        return OpenVINOYoloV8SegmentationRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "tensorrt":
        return TensorRTYoloV8SegmentationRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            pinned_output_buffer_enabled=pinned_output_buffer_enabled,
            pinned_output_buffer_max_bytes=pinned_output_buffer_max_bytes,
        )
    raise ValueError(f"unsupported segmentation runtime backend: {runtime_target.runtime_backend}")


def _load_yolo11_segmentation_session(
    dataset_storage: LocalDatasetStorage,
    runtime_target: RuntimeTargetSnapshot,
    pinned_output_buffer_enabled: bool | None,
    pinned_output_buffer_max_bytes: int | None,
) -> SegmentationModelRuntimeSession:
    """按 runtime backend 加载当前已接通的 YOLO11 segmentation 会话。"""

    if runtime_target.runtime_backend == "pytorch":
        return PyTorchYolo11SegmentationRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "onnxruntime":
        return OnnxRuntimeYolo11SegmentationRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "openvino":
        return OpenVINOYolo11SegmentationRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "tensorrt":
        return TensorRTYolo11SegmentationRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            pinned_output_buffer_enabled=pinned_output_buffer_enabled,
            pinned_output_buffer_max_bytes=pinned_output_buffer_max_bytes,
        )
    raise ValueError(f"unsupported segmentation runtime backend: {runtime_target.runtime_backend}")


def _load_yolo26_segmentation_session(
    dataset_storage: LocalDatasetStorage,
    runtime_target: RuntimeTargetSnapshot,
    pinned_output_buffer_enabled: bool | None,
    pinned_output_buffer_max_bytes: int | None,
) -> SegmentationModelRuntimeSession:
    """按 runtime backend 加载当前已接通的 YOLO26 segmentation 会话。"""

    if runtime_target.runtime_backend == "pytorch":
        return PyTorchYolo26SegmentationRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "onnxruntime":
        return OnnxRuntimeYolo26SegmentationRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "openvino":
        return OpenVINOYolo26SegmentationRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "tensorrt":
        return TensorRTYolo26SegmentationRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            pinned_output_buffer_enabled=pinned_output_buffer_enabled,
            pinned_output_buffer_max_bytes=pinned_output_buffer_max_bytes,
        )
    raise ValueError(f"unsupported segmentation runtime backend: {runtime_target.runtime_backend}")


def _normalize_model_type(model_type: str | None) -> str | None:
    """把模型分类名称归一为小写非空字符串。"""

    if isinstance(model_type, str) and model_type.strip():
        return model_type.strip().lower()
    return None
