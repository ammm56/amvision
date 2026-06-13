"""平台训练与评估使用的数据集导出格式支持规则。"""

from __future__ import annotations

from backend.contracts.datasets.exports.dataset_formats import (
    COCO_DETECTION_DATASET_FORMAT,
    COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    COCO_KEYPOINTS_DATASET_FORMAT,
    DOTA_OBB_DATASET_FORMAT,
    IMAGENET_CLASSIFICATION_DATASET_FORMAT,
    YOLO_DETECTION_DATASET_FORMAT,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.model_type_support import (
    normalize_optional_platform_model_type,
)
from backend.service.domain.models.model_task_types import (
    CLASSIFICATION_TASK_TYPE,
    DETECTION_TASK_TYPE,
    OBB_TASK_TYPE,
    POSE_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


_SUPPORTED_DATASET_EXPORT_FORMATS_BY_MODEL_TASK: dict[tuple[str, str], str] = {
    ("yolox", DETECTION_TASK_TYPE): COCO_DETECTION_DATASET_FORMAT,
    ("yolov8", DETECTION_TASK_TYPE): YOLO_DETECTION_DATASET_FORMAT,
    ("yolo11", DETECTION_TASK_TYPE): YOLO_DETECTION_DATASET_FORMAT,
    ("yolo26", DETECTION_TASK_TYPE): YOLO_DETECTION_DATASET_FORMAT,
    ("yolov8", SEGMENTATION_TASK_TYPE): COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    ("yolo11", SEGMENTATION_TASK_TYPE): COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    ("yolo26", SEGMENTATION_TASK_TYPE): COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    ("rfdetr", SEGMENTATION_TASK_TYPE): COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    ("yolov8", POSE_TASK_TYPE): COCO_KEYPOINTS_DATASET_FORMAT,
    ("yolo11", POSE_TASK_TYPE): COCO_KEYPOINTS_DATASET_FORMAT,
    ("yolo26", POSE_TASK_TYPE): COCO_KEYPOINTS_DATASET_FORMAT,
    ("yolov8", OBB_TASK_TYPE): DOTA_OBB_DATASET_FORMAT,
    ("yolo11", OBB_TASK_TYPE): DOTA_OBB_DATASET_FORMAT,
    ("yolo26", OBB_TASK_TYPE): DOTA_OBB_DATASET_FORMAT,
    ("yolov8", CLASSIFICATION_TASK_TYPE): IMAGENET_CLASSIFICATION_DATASET_FORMAT,
    ("yolo11", CLASSIFICATION_TASK_TYPE): IMAGENET_CLASSIFICATION_DATASET_FORMAT,
    ("yolo26", CLASSIFICATION_TASK_TYPE): IMAGENET_CLASSIFICATION_DATASET_FORMAT,
    ("rfdetr", DETECTION_TASK_TYPE): COCO_DETECTION_DATASET_FORMAT,
}


def resolve_supported_dataset_export_format(
    *,
    model_type: str | None,
    task_type: str,
) -> str | None:
    """返回指定 model_type 与 task_type 当前真正支持的数据集导出格式。"""

    normalized_model_type = normalize_optional_platform_model_type(model_type)
    if normalized_model_type is None:
        return None
    return _SUPPORTED_DATASET_EXPORT_FORMATS_BY_MODEL_TASK.get((normalized_model_type, task_type))


def require_supported_dataset_export_format(
    *,
    model_type: str | None,
    task_type: str,
    format_id: str,
    dataset_export_id: str | None = None,
    unsupported_message: str,
) -> str:
    """要求指定导出格式受当前 model_type 与 task_type 支持。"""

    normalized_model_type = normalize_optional_platform_model_type(model_type)
    expected_format = resolve_supported_dataset_export_format(
        model_type=normalized_model_type,
        task_type=task_type,
    )
    if expected_format is None:
        raise InvalidRequestError(
            "当前模型与任务类型缺少明确的数据集导出格式支持规则",
            details={
                "model_type": normalized_model_type,
                "task_type": task_type,
            },
        )
    if format_id == expected_format:
        return expected_format
    details: dict[str, object] = {
        "model_type": normalized_model_type,
        "task_type": task_type,
        "format_id": format_id,
        "expected_format_id": expected_format,
    }
    if dataset_export_id is not None:
        details["dataset_export_id"] = dataset_export_id
    raise InvalidRequestError(
        unsupported_message,
        details=details,
    )
