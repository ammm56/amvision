"""classification 模型后端登记表。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from backend.service.domain.models.model_task_types import CLASSIFICATION_TASK_TYPE


CLASSIFICATION_BACKEND_STATUS_ACTIVE: Final[str] = "active"
CLASSIFICATION_BACKEND_STATUS_REGISTERED: Final[str] = "registered"


@dataclass(frozen=True)
class ClassificationBackendFeatureSet:
    """描述某个 classification 模型分类当前已接通的能力集合。

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
class ClassificationBackendRegistration:
    """描述一个 classification 模型分类在平台中的登记状态。

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
    task_type: str = CLASSIFICATION_TASK_TYPE
    status: str = CLASSIFICATION_BACKEND_STATUS_REGISTERED
    features: ClassificationBackendFeatureSet = field(default_factory=ClassificationBackendFeatureSet)
    notes: str = ""


_CLASSIFICATION_BACKEND_REGISTRATIONS: Final[dict[str, ClassificationBackendRegistration]] = {
    "yolov8": ClassificationBackendRegistration(
        model_type="yolov8",
        display_name="YOLOv8 Classification",
        status=CLASSIFICATION_BACKEND_STATUS_ACTIVE,
        features=ClassificationBackendFeatureSet(
            training=True,
            conversion=True,
            inference=True,
            deployment=True,
        ),
        notes="模型登记、训练执行、转换链、四后端推理与 deployment 已接通。",
    ),
    "yolo11": ClassificationBackendRegistration(
        model_type="yolo11",
        display_name="YOLO11 Classification",
        status=CLASSIFICATION_BACKEND_STATUS_ACTIVE,
        features=ClassificationBackendFeatureSet(
            training=True,
            conversion=True,
            inference=True,
            deployment=True,
        ),
        notes="共享结构与四后端推理、训练执行已接通。",
    ),
    "yolo26": ClassificationBackendRegistration(
        model_type="yolo26",
        display_name="YOLO26 Classification",
        status=CLASSIFICATION_BACKEND_STATUS_ACTIVE,
        features=ClassificationBackendFeatureSet(
            training=True,
            conversion=True,
            inference=True,
            deployment=True,
        ),
        notes="共享结构与四后端推理、训练执行已接通。",
    ),
}


def list_classification_backend_registrations() -> tuple[ClassificationBackendRegistration, ...]:
    return tuple(_CLASSIFICATION_BACKEND_REGISTRATIONS.values())


def get_classification_backend_registration(model_type: str) -> ClassificationBackendRegistration | None:
    normalized_model_type = _normalize_model_type(model_type)
    if normalized_model_type is None:
        return None
    return _CLASSIFICATION_BACKEND_REGISTRATIONS.get(normalized_model_type)


def has_classification_backend_registration(model_type: str) -> bool:
    return get_classification_backend_registration(model_type) is not None


def _normalize_model_type(model_type: str | None) -> str | None:
    if isinstance(model_type, str) and model_type.strip():
        return model_type.strip().lower()
    return None
