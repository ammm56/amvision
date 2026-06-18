"""YOLOv8 detection 训练样本计划。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class YoloV8DetectionTrainingSamplePlan:
    """描述 YOLOv8 detection 训练样本和 validation 样本的基础计划。"""

    category_names: tuple[str, ...]
    category_ids: tuple[int, ...]
    train_sample_count: int
    validation_sample_count: int
    has_validation: bool


def plan_yolov8_detection_training_samples(
    *,
    category_names: tuple[str, ...],
    category_ids: tuple[int, ...],
    train_sample_count: int,
    validation_sample_count: int,
    validation_category_names: tuple[str, ...] | None = None,
    validation_category_ids: tuple[int, ...] | None = None,
    validation_split_name: str | None = None,
) -> YoloV8DetectionTrainingSamplePlan:
    """校验并返回 YOLOv8 detection 训练样本计划。"""

    if not category_names:
        raise InvalidRequestError("YOLOv8 detection 训练输入缺少有效的 categories")
    if int(train_sample_count) <= 0:
        raise InvalidRequestError("YOLOv8 detection 训练 split 不包含可用样本")

    has_validation = validation_split_name is not None and int(validation_sample_count) > 0
    if validation_split_name is not None:
        _validate_yolov8_detection_validation_categories(
            category_names=category_names,
            category_ids=category_ids,
            validation_category_names=validation_category_names,
            validation_category_ids=validation_category_ids,
        )

    return YoloV8DetectionTrainingSamplePlan(
        category_names=category_names,
        category_ids=category_ids,
        train_sample_count=int(train_sample_count),
        validation_sample_count=max(0, int(validation_sample_count)),
        has_validation=has_validation,
    )


def _validate_yolov8_detection_validation_categories(
    *,
    category_names: tuple[str, ...],
    category_ids: tuple[int, ...],
    validation_category_names: tuple[str, ...] | None,
    validation_category_ids: tuple[int, ...] | None,
) -> None:
    """校验 YOLOv8 detection validation split 与 train split 的类别映射一致。"""

    if validation_category_names != category_names:
        raise InvalidRequestError(
            "YOLOv8 detection 验证 split 的 categories 与训练 split 不一致",
            details={
                "train_categories": list(category_names),
                "validation_categories": list(validation_category_names or ()),
            },
        )
    if validation_category_ids != category_ids:
        raise InvalidRequestError(
            "YOLOv8 detection 验证 split 的 category_id 映射与训练 split 不一致",
            details={
                "train_category_ids": list(category_ids),
                "validation_category_ids": list(validation_category_ids or ()),
            },
        )


__all__ = [
    "YoloV8DetectionTrainingSamplePlan",
    "plan_yolov8_detection_training_samples",
]
