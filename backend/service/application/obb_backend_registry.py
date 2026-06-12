"""obb 模型后端登记表。"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Final
from backend.service.domain.models.model_task_types import OBB_TASK_TYPE
from backend.service.domain.models.platform_model_support import normalize_platform_model_type

OBB_BACKEND_STATUS_ACTIVE: Final[str] = "active"
OBB_BACKEND_STATUS_REGISTERED: Final[str] = "registered"

@dataclass(frozen=True)
class ObbBackendFeatureSet:
    """描述某个 obb 模型分类当前已接通的能力集合。"""
    training: bool = False
    conversion: bool = False
    inference: bool = False
    deployment: bool = False

@dataclass(frozen=True)
class ObbBackendRegistration:
    model_type: str
    display_name: str
    task_type: str = OBB_TASK_TYPE
    status: str = OBB_BACKEND_STATUS_REGISTERED
    features: ObbBackendFeatureSet = field(default_factory=ObbBackendFeatureSet)
    notes: str = ""

_OBB_BACKEND_REGISTRATIONS: Final[dict[str, ObbBackendRegistration]] = {
    "yolov8": ObbBackendRegistration(model_type="yolov8", display_name="YOLOv8 OBB", status=OBB_BACKEND_STATUS_ACTIVE,
        features=ObbBackendFeatureSet(training=True, conversion=True, inference=True, deployment=True),
        notes="模型登记、训练结果回写、转换链、四后端推理与 deployment 已接通。"),
    "yolo11": ObbBackendRegistration(model_type="yolo11", display_name="YOLO11 OBB", status=OBB_BACKEND_STATUS_ACTIVE,
        features=ObbBackendFeatureSet(training=True, conversion=True, inference=True, deployment=True),
        notes="共享结构、训练结果回写与四后端推理已接通。"),
    "yolo26": ObbBackendRegistration(model_type="yolo26", display_name="YOLO26 OBB", status=OBB_BACKEND_STATUS_ACTIVE,
        features=ObbBackendFeatureSet(training=True, conversion=True, inference=True, deployment=True),
        notes="共享结构、训练结果回写与四后端推理已接通。"),
}

def list_obb_backend_registrations() -> tuple[ObbBackendRegistration, ...]:
    return tuple(_OBB_BACKEND_REGISTRATIONS.values())

def get_obb_backend_registration(model_type: str) -> ObbBackendRegistration | None:
    normalized_model_type = normalize_platform_model_type(model_type)
    if normalized_model_type is not None:
        return _OBB_BACKEND_REGISTRATIONS.get(normalized_model_type)
    return None
