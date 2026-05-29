"""pose 模型后端登记表。"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Final
from backend.service.domain.models.model_task_types import POSE_TASK_TYPE

POSE_BACKEND_STATUS_ACTIVE: Final[str] = "active"
POSE_BACKEND_STATUS_REGISTERED: Final[str] = "registered"

@dataclass(frozen=True)
class PoseBackendFeatureSet:
    """描述某个 pose 模型分类当前已接通的能力集合。"""
    training: bool = False
    conversion: bool = False
    inference: bool = False
    deployment: bool = False

@dataclass(frozen=True)
class PoseBackendRegistration:
    model_type: str
    display_name: str
    task_type: str = POSE_TASK_TYPE
    status: str = POSE_BACKEND_STATUS_REGISTERED
    features: PoseBackendFeatureSet = field(default_factory=PoseBackendFeatureSet)
    notes: str = ""

_POSE_BACKEND_REGISTRATIONS: Final[dict[str, PoseBackendRegistration]] = {
    "yolov8": PoseBackendRegistration(model_type="yolov8", display_name="YOLOv8 Pose", status=POSE_BACKEND_STATUS_ACTIVE,
        features=PoseBackendFeatureSet(training=True, conversion=True, inference=True, deployment=True),
        notes="模型登记、训练结果回写、转换链、四后端推理与 deployment 已接通。"),
    "yolo11": PoseBackendRegistration(model_type="yolo11", display_name="YOLO11 Pose", status=POSE_BACKEND_STATUS_ACTIVE,
        features=PoseBackendFeatureSet(training=True, conversion=True, inference=True, deployment=True),
        notes="共享结构、训练结果回写与四后端推理已接通。"),
    "yolo26": PoseBackendRegistration(model_type="yolo26", display_name="YOLO26 Pose", status=POSE_BACKEND_STATUS_ACTIVE,
        features=PoseBackendFeatureSet(training=True, conversion=True, inference=True, deployment=True),
        notes="共享结构、训练结果回写与四后端推理已接通。"),
}

def list_pose_backend_registrations() -> tuple[PoseBackendRegistration, ...]:
    return tuple(_POSE_BACKEND_REGISTRATIONS.values())

def get_pose_backend_registration(model_type: str) -> PoseBackendRegistration | None:
    if isinstance(model_type, str) and model_type.strip():
        return _POSE_BACKEND_REGISTRATIONS.get(model_type.strip().lower())
    return None

def has_pose_backend_registration(model_type: str) -> bool:
    return get_pose_backend_registration(model_type) is not None
