"""YOLO26 detection 训练数据上下文。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo26_core.data import (
    Yolo26DetectionResolvedSplit,
    Yolo26DetectionTrainingSample,
    load_yolo26_detection_training_samples,
    resolve_yolo26_detection_splits,
    resolve_yolo26_detection_train_split,
    resolve_yolo26_detection_validation_split,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class Yolo26DetectionTrainingDataContext:
    """描述 YOLO26 detection 训练使用的 DatasetExport 数据上下文。"""

    resolved_splits: tuple[Yolo26DetectionResolvedSplit, ...]
    train_split: Yolo26DetectionResolvedSplit
    validation_split: Yolo26DetectionResolvedSplit | None
    train_samples: tuple[Yolo26DetectionTrainingSample, ...]
    validation_samples: tuple[Yolo26DetectionTrainingSample, ...]
    category_names: tuple[str, ...]
    category_ids: tuple[int, ...]
    validation_category_names: tuple[str, ...] | None
    validation_category_ids: tuple[int, ...]
    validation_split_name: str | None


def prepare_yolo26_detection_training_data_context(
    *,
    dataset_storage: LocalDatasetStorage,
    cv2_module: Any,
    manifest_payload: dict[str, object],
) -> Yolo26DetectionTrainingDataContext:
    """解析 DatasetExport manifest 并返回 YOLO26 detection 训练数据上下文。"""

    resolved_splits = resolve_yolo26_detection_splits(
        dataset_storage=dataset_storage,
        cv2_module=cv2_module,
        manifest_payload=manifest_payload,
    )
    train_split = resolve_yolo26_detection_train_split(resolved_splits)
    validation_split = resolve_yolo26_detection_validation_split(resolved_splits)
    train_samples, category_names, category_ids = (
        load_yolo26_detection_training_samples(
            split=train_split,
        )
    )
    if not train_samples:
        raise InvalidRequestError("YOLO26 detection 训练 split 不包含可用样本")

    validation_samples: tuple[Yolo26DetectionTrainingSample, ...] = ()
    validation_category_ids: tuple[int, ...] = ()
    validation_category_names: tuple[str, ...] | None = None
    if validation_split is not None:
        (
            validation_samples,
            validation_category_names,
            validation_category_ids,
        ) = load_yolo26_detection_training_samples(split=validation_split)
        if validation_category_names != category_names:
            raise InvalidRequestError(
                "YOLO26 detection 验证 split 的 categories 与训练 split 不一致",
                details={
                    "train_categories": list(category_names),
                    "validation_categories": list(validation_category_names),
                },
            )
        if validation_category_ids != category_ids:
            raise InvalidRequestError(
                "YOLO26 detection 验证 split 的 category_id 映射与训练 split 不一致",
                details={
                    "train_category_ids": list(category_ids),
                    "validation_category_ids": list(validation_category_ids),
                },
            )

    return Yolo26DetectionTrainingDataContext(
        resolved_splits=resolved_splits,
        train_split=train_split,
        validation_split=validation_split,
        train_samples=train_samples,
        validation_samples=validation_samples,
        category_names=category_names,
        category_ids=category_ids,
        validation_category_names=validation_category_names,
        validation_category_ids=validation_category_ids,
        validation_split_name=(
            validation_split.name if validation_split is not None else None
        ),
    )


__all__ = [
    "Yolo26DetectionTrainingDataContext",
    "prepare_yolo26_detection_training_data_context",
]
