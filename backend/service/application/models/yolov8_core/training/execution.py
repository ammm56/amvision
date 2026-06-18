"""YOLOv8 detection 训练执行上下文。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.models.yolov8_core.data import (
    YoloV8DetectionResolvedSplit,
    YoloV8DetectionTrainingSample,
    load_yolov8_detection_training_samples,
    resolve_yolov8_detection_splits,
    resolve_yolov8_detection_train_split,
    resolve_yolov8_detection_validation_split,
)
from backend.service.application.models.yolov8_core.training.dataloader import (
    YoloV8DetectionTrainingDataloaderPlan,
    plan_yolov8_detection_training_dataloader,
)
from backend.service.application.models.yolov8_core.training.epoch import (
    resolve_yolov8_detection_best_metric_name,
    resolve_yolov8_detection_initial_best_metric_value,
)
from backend.service.application.models.yolov8_core.training.samples import (
    YoloV8DetectionTrainingSamplePlan,
    plan_yolov8_detection_training_samples,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class YoloV8DetectionTrainingDataContext:
    """描述 YOLOv8 detection 训练使用的数据上下文。"""

    resolved_splits: tuple[YoloV8DetectionResolvedSplit, ...]
    train_split: YoloV8DetectionResolvedSplit
    validation_split: YoloV8DetectionResolvedSplit | None
    train_samples: tuple[YoloV8DetectionTrainingSample, ...]
    validation_samples: tuple[YoloV8DetectionTrainingSample, ...]
    category_names: tuple[str, ...]
    category_ids: tuple[int, ...]
    validation_category_names: tuple[str, ...] | None
    validation_category_ids: tuple[int, ...]
    validation_split_name: str | None
    sample_plan: YoloV8DetectionTrainingSamplePlan


@dataclass(frozen=True)
class YoloV8DetectionTrainingExecutionPlan:
    """描述 YOLOv8 detection 训练循环的执行边界。"""

    has_validation: bool
    best_metric_name: str
    best_metric_value: float
    dataloader_plan: YoloV8DetectionTrainingDataloaderPlan
    total_iterations: int
    initial_global_iteration: int


def prepare_yolov8_detection_training_data_context(
    *,
    dataset_storage: LocalDatasetStorage,
    cv2_module: Any,
    manifest_payload: dict[str, object],
) -> YoloV8DetectionTrainingDataContext:
    """解析 DatasetExport manifest 并返回 YOLOv8 detection 训练数据上下文。"""

    resolved_splits = resolve_yolov8_detection_splits(
        dataset_storage=dataset_storage,
        cv2_module=cv2_module,
        manifest_payload=manifest_payload,
    )
    train_split = resolve_yolov8_detection_train_split(resolved_splits)
    validation_split = resolve_yolov8_detection_validation_split(resolved_splits)
    train_samples, category_names, category_ids = load_yolov8_detection_training_samples(
        split=train_split,
    )

    validation_samples: tuple[YoloV8DetectionTrainingSample, ...] = ()
    validation_category_ids: tuple[int, ...] = ()
    validation_category_names: tuple[str, ...] | None = None
    if validation_split is not None:
        (
            validation_samples,
            validation_category_names,
            validation_category_ids,
        ) = load_yolov8_detection_training_samples(split=validation_split)

    validation_split_name = validation_split.name if validation_split is not None else None
    sample_plan = plan_yolov8_detection_training_samples(
        category_names=category_names,
        category_ids=category_ids,
        train_sample_count=len(train_samples),
        validation_sample_count=len(validation_samples),
        validation_category_names=validation_category_names,
        validation_category_ids=validation_category_ids,
        validation_split_name=validation_split_name,
    )
    return YoloV8DetectionTrainingDataContext(
        resolved_splits=resolved_splits,
        train_split=train_split,
        validation_split=validation_split,
        train_samples=train_samples,
        validation_samples=validation_samples,
        category_names=category_names,
        category_ids=category_ids,
        validation_category_names=validation_category_names,
        validation_category_ids=validation_category_ids,
        validation_split_name=validation_split_name,
        sample_plan=sample_plan,
    )


def plan_yolov8_detection_training_execution(
    *,
    data_context: YoloV8DetectionTrainingDataContext,
    batch_size: int,
    max_epochs: int,
    resume_epoch: int,
    resume_best_metric_name: str | None = None,
    resume_best_metric_value: float | None = None,
) -> YoloV8DetectionTrainingExecutionPlan:
    """根据数据上下文和 resume 状态返回 YOLOv8 detection 训练执行计划。"""

    dataloader_plan = plan_yolov8_detection_training_dataloader(
        train_sample_count=len(data_context.train_samples),
        batch_size=batch_size,
        max_epochs=max_epochs,
        resume_epoch=resume_epoch,
    )
    has_validation = data_context.sample_plan.has_validation
    best_metric_name = (
        resume_best_metric_name.strip()
        if isinstance(resume_best_metric_name, str) and resume_best_metric_name.strip()
        else resolve_yolov8_detection_best_metric_name(has_validation=has_validation)
    )
    best_metric_value = (
        float(resume_best_metric_value)
        if resume_best_metric_value is not None
        else resolve_yolov8_detection_initial_best_metric_value(has_validation=has_validation)
    )
    return YoloV8DetectionTrainingExecutionPlan(
        has_validation=has_validation,
        best_metric_name=best_metric_name,
        best_metric_value=best_metric_value,
        dataloader_plan=dataloader_plan,
        total_iterations=dataloader_plan.total_iterations,
        initial_global_iteration=dataloader_plan.initial_global_iteration,
    )


__all__ = [
    "YoloV8DetectionTrainingDataContext",
    "YoloV8DetectionTrainingExecutionPlan",
    "plan_yolov8_detection_training_execution",
    "prepare_yolov8_detection_training_data_context",
]
