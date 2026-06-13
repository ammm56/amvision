"""YOLO 系列模型 profile 定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal

from backend.contracts.datasets.exports.dataset_formats import (
    COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    COCO_KEYPOINTS_DATASET_FORMAT,
    DOTA_OBB_DATASET_FORMAT,
    IMAGENET_CLASSIFICATION_DATASET_FORMAT,
    YOLO_DETECTION_DATASET_FORMAT,
)
from backend.service.domain.models.model_build_formats import (
    ModelBuildFormat,
    ONNX_BUILD_FORMAT,
    ONNX_OPTIMIZED_BUILD_FORMAT,
    OPENVINO_IR_BUILD_FORMAT,
    PYTORCH_CHECKPOINT_BUILD_FORMAT,
    RKNN_BUILD_FORMAT,
    TENSORRT_ENGINE_BUILD_FORMAT,
)
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    ModelTaskType,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


YoloModelType = Literal["yolov8", "yolo11", "yolo26"]

YOLO_PRIMARY_MODEL_SCALES: Final[tuple[str, ...]] = ("nano", "s", "m", "l", "x")
YOLO_PRIMARY_BUILD_FORMATS: Final[tuple[ModelBuildFormat, ...]] = (
    PYTORCH_CHECKPOINT_BUILD_FORMAT,
    ONNX_BUILD_FORMAT,
    ONNX_OPTIMIZED_BUILD_FORMAT,
    OPENVINO_IR_BUILD_FORMAT,
    TENSORRT_ENGINE_BUILD_FORMAT,
    RKNN_BUILD_FORMAT,
)


@dataclass(frozen=True)
class YoloModelProfile:
    """描述一个 YOLO 模型分类的稳定 profile。"""

    model_type: YoloModelType
    supported_tasks: tuple[ModelTaskType, ...]
    supported_scales: tuple[str, ...] = YOLO_PRIMARY_MODEL_SCALES
    supported_build_formats: tuple[ModelBuildFormat, ...] = YOLO_PRIMARY_BUILD_FORMATS
    default_dataset_formats: dict[ModelTaskType, str] = field(default_factory=dict)

    def supports_task_type(self, task_type: str) -> bool:
        """判断当前 profile 是否支持指定任务分类。"""

        return task_type in self.supported_tasks

    def supports_model_scale(self, model_scale: str) -> bool:
        """判断当前 profile 是否支持指定模型 scale。"""

        return model_scale in self.supported_scales

    def supports_build_format(self, build_format: str) -> bool:
        """判断当前 profile 是否支持指定 build 格式。"""

        return build_format in self.supported_build_formats

    def resolve_default_dataset_format(self, task_type: str) -> str | None:
        """返回指定任务分类的默认数据集导出格式。"""

        return self.default_dataset_formats.get(task_type)


YOLOV8_MODEL_PROFILE: Final[YoloModelProfile] = YoloModelProfile(
    model_type="yolov8",
    supported_tasks=(
        DETECTION_TASK_TYPE,
        SEGMENTATION_TASK_TYPE,
        POSE_TASK_TYPE,
        OBB_TASK_TYPE,
        CLASSIFICATION_TASK_TYPE,
    ),
    default_dataset_formats={
        DETECTION_TASK_TYPE: YOLO_DETECTION_DATASET_FORMAT,
        SEGMENTATION_TASK_TYPE: COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
        POSE_TASK_TYPE: COCO_KEYPOINTS_DATASET_FORMAT,
        OBB_TASK_TYPE: DOTA_OBB_DATASET_FORMAT,
        CLASSIFICATION_TASK_TYPE: IMAGENET_CLASSIFICATION_DATASET_FORMAT,
    },
)

YOLO11_MODEL_PROFILE: Final[YoloModelProfile] = YoloModelProfile(
    model_type="yolo11",
    supported_tasks=YOLOV8_MODEL_PROFILE.supported_tasks,
    default_dataset_formats=dict(YOLOV8_MODEL_PROFILE.default_dataset_formats),
)

YOLO26_MODEL_PROFILE: Final[YoloModelProfile] = YoloModelProfile(
    model_type="yolo26",
    supported_tasks=YOLOV8_MODEL_PROFILE.supported_tasks,
    default_dataset_formats=dict(YOLOV8_MODEL_PROFILE.default_dataset_formats),
)

YOLO_MODEL_PROFILES: Final[dict[YoloModelType, YoloModelProfile]] = {
    YOLOV8_MODEL_PROFILE.model_type: YOLOV8_MODEL_PROFILE,
    YOLO11_MODEL_PROFILE.model_type: YOLO11_MODEL_PROFILE,
    YOLO26_MODEL_PROFILE.model_type: YOLO26_MODEL_PROFILE,
}


def get_yolo_model_profile(model_type: str) -> YoloModelProfile | None:
    """按模型分类读取对应的 YOLO profile。"""

    return YOLO_MODEL_PROFILES.get(model_type)
