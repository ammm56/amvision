"""YOLO26 classification DatasetExport manifest 解析。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class Yolo26ClassificationTrainingAnnotation:
    """描述 YOLO26 classification 训练样本。"""

    image_path: str
    class_id: int


@dataclass(frozen=True)
class Yolo26ClassificationTrainingManifest:
    """描述 YOLO26 classification 训练 manifest 的已解析内容。"""

    labels: tuple[str, ...]
    train_annotations: list[Yolo26ClassificationTrainingAnnotation]
    val_annotations: list[Yolo26ClassificationTrainingAnnotation]


def load_yolo26_classification_training_manifest(
    *,
    dataset_storage: LocalDatasetStorage,
    manifest_payload: dict[str, object],
) -> Yolo26ClassificationTrainingManifest:
    """解析 DatasetExport manifest，输出 YOLO26 classification 训练样本。"""

    splits = manifest_payload.get("splits")
    if not isinstance(splits, list) or len(splits) < 1:
        raise InvalidRequestError("YOLO26 classification 训练 manifest 缺少合法 splits")

    all_labels: dict[int, str] = {}
    train_annotations: list[Yolo26ClassificationTrainingAnnotation] = []
    val_annotations: list[Yolo26ClassificationTrainingAnnotation] = []
    for split in splits:
        if not isinstance(split, dict):
            continue
        split_name = str(split.get("name", ""))
        resolved = _load_yolo26_classification_split_annotations(
            dataset_storage=dataset_storage,
            split=split,
            all_labels=all_labels,
        )
        if split_name == "train":
            train_annotations = resolved
        elif split_name == "val":
            val_annotations = resolved

    labels, category_id_to_index = _build_yolo26_classification_label_mapping(
        all_labels
    )
    return Yolo26ClassificationTrainingManifest(
        labels=labels,
        train_annotations=_remap_yolo26_classification_annotations(
            annotations=train_annotations,
            category_id_to_index=category_id_to_index,
        ),
        val_annotations=_remap_yolo26_classification_annotations(
            annotations=val_annotations,
            category_id_to_index=category_id_to_index,
        ),
    )


def _load_yolo26_classification_split_annotations(
    *,
    dataset_storage: LocalDatasetStorage,
    split: dict[str, object],
    all_labels: dict[int, str],
) -> list[Yolo26ClassificationTrainingAnnotation]:
    """读取单个 split 的分类标注。"""

    image_root = str(split.get("image_root", ""))
    annotation_file = str(split.get("annotation_file", ""))
    ann_path = dataset_storage.resolve(annotation_file)
    if not ann_path.is_file():
        raise InvalidRequestError(
            f"YOLO26 classification 标注文件不存在: {annotation_file}"
        )
    ann_payload = dataset_storage.read_json(annotation_file)
    if not isinstance(ann_payload, dict):
        raise InvalidRequestError(
            f"YOLO26 classification 标注格式无效: {annotation_file}"
        )

    _collect_yolo26_classification_labels(
        categories=ann_payload.get("categories", []),
        all_labels=all_labels,
    )
    return _resolve_yolo26_classification_annotations(
        dataset_storage=dataset_storage,
        image_root=image_root,
        images=ann_payload.get("images", []),
        annotations=ann_payload.get("annotations", []),
    )


def _collect_yolo26_classification_labels(
    *,
    categories: Any,
    all_labels: dict[int, str],
) -> None:
    """从分类标注中收集类别名称。"""

    if not isinstance(categories, list):
        return
    for category in categories:
        if not isinstance(category, dict):
            continue
        category_id = int(category.get("id", -1))
        category_name = str(category.get("name", ""))
        if category_id >= 0:
            all_labels[category_id] = category_name


def _resolve_yolo26_classification_annotations(
    *,
    dataset_storage: LocalDatasetStorage,
    image_root: str,
    images: Any,
    annotations: Any,
) -> list[Yolo26ClassificationTrainingAnnotation]:
    """把 manifest 标注转换为磁盘图片路径和类别 id。"""

    image_map = _build_yolo26_classification_image_map(images)
    resolved: list[Yolo26ClassificationTrainingAnnotation] = []
    if not isinstance(annotations, list):
        return resolved
    for annotation in annotations:
        if not isinstance(annotation, dict):
            continue
        image_id = int(annotation.get("image_id", -1))
        class_id = int(annotation.get("category_id", -1))
        file_name = image_map.get(image_id, "")
        if not file_name:
            continue
        resolved.append(
            Yolo26ClassificationTrainingAnnotation(
                image_path=str(dataset_storage.resolve(f"{image_root}/{file_name}")),
                class_id=class_id,
            )
        )
    return resolved


def _build_yolo26_classification_image_map(images: Any) -> dict[int, str]:
    """构建 image id 到文件名的映射。"""

    image_map: dict[int, str] = {}
    if not isinstance(images, list):
        return image_map
    for image in images:
        if isinstance(image, dict):
            image_map[int(image.get("id", -1))] = str(image.get("file_name", ""))
    return image_map


def _build_yolo26_classification_label_mapping(
    labels_by_category_id: dict[int, str],
) -> tuple[tuple[str, ...], dict[int, int]]:
    """构建类别名称和 category id 到连续训练 id 的映射。"""

    sorted_labels = sorted(labels_by_category_id.items())
    labels = tuple(name for _category_id, name in sorted_labels)
    category_id_to_index = {
        category_id: index for index, (category_id, _name) in enumerate(sorted_labels)
    }
    return labels, category_id_to_index


def _remap_yolo26_classification_annotations(
    *,
    annotations: list[Yolo26ClassificationTrainingAnnotation],
    category_id_to_index: dict[int, int],
) -> list[Yolo26ClassificationTrainingAnnotation]:
    """把原始 category id 重新映射为连续训练类别 id。"""

    return [
        Yolo26ClassificationTrainingAnnotation(
            image_path=annotation.image_path,
            class_id=category_id_to_index.get(annotation.class_id, 0),
        )
        for annotation in annotations
    ]


__all__ = [
    "Yolo26ClassificationTrainingAnnotation",
    "Yolo26ClassificationTrainingManifest",
    "load_yolo26_classification_training_manifest",
]

