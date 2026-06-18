"""detection 模型运行时加载器与注册表。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from backend.service.application.detection_backend_registry import (
    get_detection_backend_registration,
)
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.model_type_support import (
    normalize_optional_platform_model_type,
)
from backend.service.application.runtime.yolo11_predictor import (
    OnnxRuntimeYolo11RuntimeSession,
    OpenVINOYolo11RuntimeSession,
    PyTorchYolo11RuntimeSession,
    TensorRTYolo11RuntimeSession,
)
from backend.service.application.runtime.yolo26_predictor import (
    OnnxRuntimeYolo26RuntimeSession,
    OpenVINOYolo26RuntimeSession,
    PyTorchYolo26RuntimeSession,
    TensorRTYolo26RuntimeSession,
)
from backend.service.application.runtime.detection_runtime_contracts import (
    DetectionPredictionExecutionResult,
    DetectionPredictionRequest,
)
from backend.service.application.runtime.predictors.yolox import (
    OpenVINODetectionRuntimeSession,
    OnnxRuntimeDetectionRuntimeSession,
    PyTorchDetectionRuntimeSession,
    TensorRTDetectionRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr import (
    PyTorchRfdetrRuntimeSession,
    OnnxRuntimeRfdetrRuntimeSession,
    OpenVINORfdetrRuntimeSession,
    TensorRTRfdetrRuntimeSession,
)
from backend.service.application.runtime.predictors.yolov8_detection import (
    OpenVINOYoloV8RuntimeSession,
    OnnxRuntimeYoloV8RuntimeSession,
    PyTorchYoloV8RuntimeSession,
    TensorRTYoloV8RuntimeSession,
)
from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


DetectionRuntimeLoader = Callable[
    [LocalDatasetStorage, RuntimeTargetSnapshot, bool | None, int | None],
    "DetectionModelRuntimeSession",
]


class DetectionModelRuntimeSession(Protocol):
    """定义 detection 模型会话需要满足的最小协议。"""

    def predict(self, request: DetectionPredictionRequest) -> DetectionPredictionExecutionResult:
        """执行一次 detection 预测并返回结果。"""

        ...


class DetectionModelRuntime(Protocol):
    """定义 detection 模型运行时加载器需要满足的最小协议。"""

    def load_session(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        pinned_output_buffer_enabled: bool | None = None,
        pinned_output_buffer_max_bytes: int | None = None,
    ) -> DetectionModelRuntimeSession:
        """按运行时快照加载 detection 模型会话。"""

        ...


@dataclass
class DetectionModelRuntimeRegistry:
    """按模型分类管理 detection 运行时加载器。"""

    runtime_loaders: dict[str, DetectionRuntimeLoader] = field(default_factory=dict)

    def register_runtime_loader(self, model_type: str, loader: DetectionRuntimeLoader) -> None:
        """登记指定模型分类对应的 detection 运行时加载器。"""

        normalized_model_type = _normalize_model_type(model_type)
        if normalized_model_type is None:
            raise ServiceConfigurationError("登记 detection runtime loader 时 model_type 不能为空")
        self.runtime_loaders[normalized_model_type] = loader

    def resolve_runtime_loader(self, model_type: str) -> DetectionRuntimeLoader:
        """按模型分类解析 detection 运行时加载器。"""

        normalized_model_type = _normalize_model_type(model_type)
        if normalized_model_type is None:
            raise ServiceConfigurationError("当前 detection runtime 缺少有效 model_type")

        runtime_loader = self.runtime_loaders.get(normalized_model_type)
        if runtime_loader is not None:
            return runtime_loader

        registration = get_detection_backend_registration(normalized_model_type)
        if registration is None:
            raise ServiceConfigurationError(
                "当前 detection runtime 收到了未登记的模型分类",
                details={"model_type": normalized_model_type},
            )
        raise ServiceConfigurationError(
            "当前 detection runtime 尚未接通该模型分类",
            details={
                "model_type": normalized_model_type,
                "display_name": registration.display_name,
                "status": registration.status,
                "notes": registration.notes,
            },
        )


class DefaultDetectionModelRuntime:
    """根据模型分类与 runtime backend 分发 detection 会话加载。"""

    def __init__(self, runtime_registry: DetectionModelRuntimeRegistry | None = None) -> None:
        """初始化 detection 运行时加载器。"""

        self.runtime_registry = runtime_registry or build_default_detection_model_runtime_registry()

    def load_session(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        runtime_target: RuntimeTargetSnapshot,
        pinned_output_buffer_enabled: bool | None = None,
        pinned_output_buffer_max_bytes: int | None = None,
    ) -> DetectionModelRuntimeSession:
        """按模型分类和 runtime backend 加载 detection 模型会话。"""

        runtime_loader = self.runtime_registry.resolve_runtime_loader(runtime_target.model_type)
        return runtime_loader(
            dataset_storage,
            runtime_target,
            pinned_output_buffer_enabled,
            pinned_output_buffer_max_bytes,
        )


def build_default_detection_model_runtime_registry() -> DetectionModelRuntimeRegistry:
    """构建当前进程默认使用的 detection runtime 注册表。"""

    registry = DetectionModelRuntimeRegistry()
    registry.register_runtime_loader("yolox", _load_yolox_detection_session)
    registry.register_runtime_loader("yolov8", _load_yolov8_detection_session)
    registry.register_runtime_loader("yolo11", _load_yolo11_detection_session)
    registry.register_runtime_loader("yolo26", _load_yolo26_detection_session)
    registry.register_runtime_loader("rfdetr", _load_rfdetr_detection_session)
    return registry


def _load_yolox_detection_session(
    dataset_storage: LocalDatasetStorage,
    runtime_target: RuntimeTargetSnapshot,
    pinned_output_buffer_enabled: bool | None,
    pinned_output_buffer_max_bytes: int | None,
) -> DetectionModelRuntimeSession:
    """按 runtime backend 加载当前已接通的 YOLOX detection 会话。"""

    if runtime_target.runtime_backend == "pytorch":
        return PyTorchDetectionRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "onnxruntime":
        return OnnxRuntimeDetectionRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "openvino":
        return OpenVINODetectionRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "tensorrt":
        return TensorRTDetectionRuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            pinned_output_buffer_enabled=pinned_output_buffer_enabled,
            pinned_output_buffer_max_bytes=pinned_output_buffer_max_bytes,
        )
    raise ValueError(f"unsupported runtime backend: {runtime_target.runtime_backend}")


def _load_yolov8_detection_session(
    dataset_storage: LocalDatasetStorage,
    runtime_target: RuntimeTargetSnapshot,
    pinned_output_buffer_enabled: bool | None,
    pinned_output_buffer_max_bytes: int | None,
) -> DetectionModelRuntimeSession:
    """按 runtime backend 加载当前已接通的 YOLOv8 detection 会话。"""

    if runtime_target.runtime_backend == "pytorch":
        return PyTorchYoloV8RuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "onnxruntime":
        return OnnxRuntimeYoloV8RuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "openvino":
        return OpenVINOYoloV8RuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "tensorrt":
        return TensorRTYoloV8RuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            pinned_output_buffer_enabled=pinned_output_buffer_enabled,
            pinned_output_buffer_max_bytes=pinned_output_buffer_max_bytes,
        )
    raise ValueError(f"unsupported runtime backend: {runtime_target.runtime_backend}")


def _load_yolo11_detection_session(
    dataset_storage: LocalDatasetStorage,
    runtime_target: RuntimeTargetSnapshot,
    pinned_output_buffer_enabled: bool | None,
    pinned_output_buffer_max_bytes: int | None,
) -> DetectionModelRuntimeSession:
    """按 runtime backend 加载当前已接通的 YOLO11 detection 会话。"""

    if runtime_target.runtime_backend == "pytorch":
        return PyTorchYolo11RuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "onnxruntime":
        return OnnxRuntimeYolo11RuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "openvino":
        return OpenVINOYolo11RuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "tensorrt":
        return TensorRTYolo11RuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            pinned_output_buffer_enabled=pinned_output_buffer_enabled,
            pinned_output_buffer_max_bytes=pinned_output_buffer_max_bytes,
        )
    raise ValueError(f"unsupported runtime backend: {runtime_target.runtime_backend}")


def _load_yolo26_detection_session(
    dataset_storage: LocalDatasetStorage,
    runtime_target: RuntimeTargetSnapshot,
    pinned_output_buffer_enabled: bool | None,
    pinned_output_buffer_max_bytes: int | None,
) -> DetectionModelRuntimeSession:
    """按 runtime backend 加载当前已接通的 YOLO26 detection 会话。"""

    if runtime_target.runtime_backend == "pytorch":
        return PyTorchYolo26RuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "onnxruntime":
        return OnnxRuntimeYolo26RuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "openvino":
        return OpenVINOYolo26RuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    if runtime_target.runtime_backend == "tensorrt":
        return TensorRTYolo26RuntimeSession.load(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            pinned_output_buffer_enabled=pinned_output_buffer_enabled,
            pinned_output_buffer_max_bytes=pinned_output_buffer_max_bytes,
        )
    raise ValueError(f"unsupported runtime backend: {runtime_target.runtime_backend}")


def _load_rfdetr_detection_session(
    dataset_storage: LocalDatasetStorage,
    runtime_target: RuntimeTargetSnapshot,
    pinned_output_buffer_enabled: bool | None,
    pinned_output_buffer_max_bytes: int | None,
) -> DetectionModelRuntimeSession:
    """按 runtime backend 加载当前已接通的 RF-DETR 会话。"""

    del pinned_output_buffer_enabled, pinned_output_buffer_max_bytes
    if runtime_target.runtime_backend == "pytorch":
        return PyTorchRfdetrRuntimeSession.load(dataset_storage=dataset_storage, runtime_target=runtime_target)
    if runtime_target.runtime_backend == "onnxruntime":
        return OnnxRuntimeRfdetrRuntimeSession.load(dataset_storage=dataset_storage, runtime_target=runtime_target)
    if runtime_target.runtime_backend == "openvino":
        return OpenVINORfdetrRuntimeSession.load(dataset_storage=dataset_storage, runtime_target=runtime_target)
    if runtime_target.runtime_backend == "tensorrt":
        return TensorRTRfdetrRuntimeSession.load(dataset_storage=dataset_storage, runtime_target=runtime_target)
    raise ValueError(f"unsupported rfdetr runtime backend: {runtime_target.runtime_backend}")


def _normalize_model_type(model_type: str | None) -> str | None:
    """把模型分类名称归一为小写非空字符串。"""

    return normalize_optional_platform_model_type(model_type)
