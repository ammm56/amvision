"""detection 模型后端登记表。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE


DETECTION_BACKEND_STATUS_ACTIVE: Final[str] = "active"
DETECTION_BACKEND_STATUS_REGISTERED: Final[str] = "registered"


@dataclass(frozen=True)
class DetectionBackendFeatureSet:
    """描述某个 detection 模型分类当前已接通的能力集合。

    字段：
    - training：是否已经接通训练任务链。
    - conversion：是否已经接通转换任务链。
    - inference：是否已经接通推理任务链。
    - deployment：是否已经接通长期运行 deployment 链。
    """

    training: bool = False
    conversion: bool = False
    inference: bool = False
    deployment: bool = False


@dataclass(frozen=True)
class DetectionBackendRegistration:
    """描述一个 detection 模型分类在平台中的登记状态。

    字段：
    - model_type：模型分类名称。
    - display_name：对外展示名称。
    - task_type：当前登记的任务分类。
    - status：当前实现阶段。
    - features：当前已经接通的能力集合。
    - notes：额外说明。
    """

    model_type: str
    display_name: str
    task_type: str = DETECTION_TASK_TYPE
    status: str = DETECTION_BACKEND_STATUS_REGISTERED
    features: DetectionBackendFeatureSet = field(default_factory=DetectionBackendFeatureSet)
    notes: str = ""


_DETECTION_BACKEND_REGISTRATIONS: Final[dict[str, DetectionBackendRegistration]] = {
    "yolox": DetectionBackendRegistration(
        model_type="yolox",
        display_name="YOLOX Detection",
        status=DETECTION_BACKEND_STATUS_ACTIVE,
        features=DetectionBackendFeatureSet(
            training=True,
            conversion=True,
            inference=True,
            deployment=True,
        ),
        notes="当前 detection 主线参考实现。",
    ),
    "yolov8": DetectionBackendRegistration(
        model_type="yolov8",
        display_name="YOLOv8 Detection",
        status=DETECTION_BACKEND_STATUS_ACTIVE,
        features=DetectionBackendFeatureSet(
            training=False,
            conversion=True,
            inference=True,
            deployment=True,
        ),
        notes=(
            "模型登记、训练任务入口、转换规划、PyTorch/ONNXRuntime 推理与 deployment 外壳已接通；"
            "训练执行后端以及 OpenVINO/TensorRT 链仍待补齐。"
        ),
    ),
}


def list_detection_backend_registrations() -> tuple[DetectionBackendRegistration, ...]:
    """返回当前已登记的 detection 模型分类列表。"""

    return tuple(_DETECTION_BACKEND_REGISTRATIONS.values())


def get_detection_backend_registration(model_type: str) -> DetectionBackendRegistration | None:
    """按模型分类读取 detection 后端登记信息。"""

    normalized_model_type = _normalize_model_type(model_type)
    if normalized_model_type is None:
        return None
    return _DETECTION_BACKEND_REGISTRATIONS.get(normalized_model_type)


def has_detection_backend_registration(model_type: str) -> bool:
    """判断指定模型分类是否已经登记到 detection 后端表。"""

    return get_detection_backend_registration(model_type) is not None


def _normalize_model_type(model_type: str | None) -> str | None:
    """把模型分类名称归一为小写非空字符串。"""

    if isinstance(model_type, str) and model_type.strip():
        return model_type.strip().lower()
    return None
