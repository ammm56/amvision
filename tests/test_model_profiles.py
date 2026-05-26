"""模型 profile 与规格基础行为测试。"""

from __future__ import annotations

from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.contracts.datasets.exports.dataset_formats import (
    YOLO_DETECTION_DATASET_FORMAT,
    YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    YOLO_POSE_DATASET_FORMAT,
)
from backend.service.domain.models.model_task_types import (
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)
from backend.service.domain.models.yolo_model_profiles import get_yolo_model_profile
from backend.service.domain.models.yolox_model_spec import DEFAULT_YOLOX_MODEL_SPEC


def test_yolox_model_spec_exposes_detection_capabilities() -> None:
    """验证 YOLOX 规格对象暴露 detection 主线的最小公共能力。"""

    spec = DEFAULT_YOLOX_MODEL_SPEC

    assert spec.supports_task_type(DETECTION_TASK_TYPE) is True
    assert spec.supports_model_scale("s") is True
    assert spec.supports_model_scale("n") is False
    assert spec.supports_build_format("onnx") is True
    assert spec.resolve_default_dataset_format(DETECTION_TASK_TYPE) == COCO_DETECTION_DATASET_FORMAT


def test_yolo_model_profiles_expose_shared_task_defaults() -> None:
    """验证 YOLO 系列 profile 已登记 detection、segmentation 和 pose 的默认导出格式。"""

    profile = get_yolo_model_profile("yolo11")

    assert profile is not None
    assert profile.supports_task_type(DETECTION_TASK_TYPE) is True
    assert profile.supports_task_type(SEGMENTATION_TASK_TYPE) is True
    assert profile.supports_task_type(POSE_TASK_TYPE) is True
    assert profile.supports_task_type(OBB_TASK_TYPE) is True
    assert profile.supports_model_scale("n") is True
    assert profile.resolve_default_dataset_format(DETECTION_TASK_TYPE) == YOLO_DETECTION_DATASET_FORMAT
    assert profile.resolve_default_dataset_format(SEGMENTATION_TASK_TYPE) == YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT
    assert profile.resolve_default_dataset_format(POSE_TASK_TYPE) == YOLO_POSE_DATASET_FORMAT
    assert profile.resolve_default_dataset_format(OBB_TASK_TYPE) is None
