"""YOLO26 segmentation 训练 manifest 解析。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.contracts.datasets.exports.dataset_formats import (
    COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.support.yolo_dataset_manifest_support import (
    build_coco_payload_from_yolo_segmentation_split,
    normalize_yolo_category_names,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class Yolo26SegmentationTrainingAnnotation:
    """描述 YOLO26 segmentation 训练样本标注。"""

    image_path: str
    boxes_xywh: list[list[float]]
    class_ids: list[int]
    segmentations: list[list[list[float]] | None] | None = None


@dataclass(frozen=True)
class Yolo26SegmentationTrainingManifest:
    """描述 YOLO26 segmentation 训练 manifest 解析结果。"""

    labels: tuple[str, ...]
    train_annotations: list[Yolo26SegmentationTrainingAnnotation]
    val_annotations: list[Yolo26SegmentationTrainingAnnotation]


def load_yolo26_segmentation_training_manifest(
    *,
    dataset_storage: LocalDatasetStorage,
    manifest_payload: dict[str, object],
) -> Yolo26SegmentationTrainingManifest:
    """读取 DatasetExport manifest 并转换成 YOLO26 segmentation 样本。"""

    splits = manifest_payload.get("splits")
    if not isinstance(splits, list):
        raise InvalidRequestError("YOLO26 segmentation 训练 manifest 缺少合法 splits")

    format_id = str(
        manifest_payload.get("format_id") or COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT
    ).strip()
    yolo_category_names = (
        normalize_yolo_category_names(
            category_names=manifest_payload.get("category_names"),
            format_label="YOLO segmentation",
        )
        if format_id == YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT
        else ()
    )

    all_categories: dict[int, str] = {}
    train_annotations: list[Yolo26SegmentationTrainingAnnotation] = []
    val_annotations: list[Yolo26SegmentationTrainingAnnotation] = []
    for split_payload in splits:
        if not isinstance(split_payload, dict):
            continue
        split_name = str(split_payload.get("name", ""))
        image_root = str(split_payload.get("image_root", ""))
        payload = _load_yolo26_segmentation_split_payload(
            dataset_storage=dataset_storage,
            split_payload=split_payload,
            split_name=split_name,
            image_root=image_root,
            format_id=format_id,
            yolo_category_names=yolo_category_names,
        )
        _collect_yolo26_segmentation_categories(payload, all_categories)
        split_annotations = _build_yolo26_segmentation_split_annotations(
            dataset_storage=dataset_storage,
            payload=payload,
            image_root=image_root,
        )
        if split_name == "train":
            train_annotations = split_annotations
        elif split_name == "val":
            val_annotations = split_annotations

    labels, category_id_to_index = _build_yolo26_segmentation_label_mapping(
        all_categories
    )
    return Yolo26SegmentationTrainingManifest(
        labels=labels,
        train_annotations=_remap_yolo26_segmentation_annotation_classes(
            train_annotations,
            category_id_to_index,
        ),
        val_annotations=_remap_yolo26_segmentation_annotation_classes(
            val_annotations,
            category_id_to_index,
        ),
    )


def _load_yolo26_segmentation_split_payload(
    *,
    dataset_storage: LocalDatasetStorage,
    split_payload: dict[str, object],
    split_name: str,
    image_root: str,
    format_id: str,
    yolo_category_names: tuple[str, ...],
) -> dict[str, object]:
    """读取单个 split 的 COCO-style segmentation payload。"""

    if format_id == YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT:
        label_root = str(split_payload.get("label_root", ""))
        image_root_path = dataset_storage.resolve(image_root)
        label_root_path = dataset_storage.resolve(label_root)
        if not image_root_path.is_dir():
            raise InvalidRequestError(
                "YOLO26 segmentation 训练 split 缺少图片目录",
                details={"split_name": split_name, "image_root": image_root},
            )
        if not label_root_path.is_dir():
            raise InvalidRequestError(
                "YOLO26 segmentation 训练 split 缺少标签目录",
                details={"split_name": split_name, "label_root": label_root},
            )
        return build_coco_payload_from_yolo_segmentation_split(
            split_name=split_name,
            image_root=image_root_path,
            label_root=label_root_path,
            category_names=yolo_category_names,
        )

    annotation_file = str(split_payload.get("annotation_file", ""))
    annotation_path = dataset_storage.resolve(annotation_file)
    if not annotation_path.is_file():
        raise InvalidRequestError(
            f"YOLO26 segmentation 标注文件不存在: {annotation_file}"
        )
    payload = dataset_storage.read_json(annotation_file)
    if not isinstance(payload, dict):
        raise InvalidRequestError(
            f"YOLO26 segmentation 标注格式无效: {annotation_file}"
        )
    return payload


def _collect_yolo26_segmentation_categories(
    payload: dict[str, object],
    category_map: dict[int, str],
) -> None:
    """收集 COCO categories。"""

    categories = payload.get("categories", [])
    if not isinstance(categories, list):
        return
    for category in categories:
        if isinstance(category, dict):
            category_map[int(category.get("id", -1))] = str(category.get("name", ""))


def _build_yolo26_segmentation_split_annotations(
    *,
    dataset_storage: LocalDatasetStorage,
    payload: dict[str, object],
    image_root: str,
) -> list[Yolo26SegmentationTrainingAnnotation]:
    """把 COCO annotations 转成 YOLO26 segmentation 训练样本。"""

    image_map: dict[int, str] = {}
    for image_payload in payload.get("images") or []:
        if isinstance(image_payload, dict):
            image_map[int(image_payload.get("id", -1))] = str(
                image_payload.get("file_name", "")
            )

    annotations: list[Yolo26SegmentationTrainingAnnotation] = []
    for annotation_payload in payload.get("annotations") or []:
        if not isinstance(annotation_payload, dict):
            continue
        image_id = int(annotation_payload.get("image_id", -1))
        file_name = image_map.get(image_id, "")
        if not file_name:
            continue
        bbox = annotation_payload.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        annotations.append(
            Yolo26SegmentationTrainingAnnotation(
                image_path=str(dataset_storage.resolve(f"{image_root}/{file_name}")),
                boxes_xywh=[bbox],
                class_ids=[int(annotation_payload.get("category_id", 0))],
                segmentations=_extract_yolo26_segmentation_polygons(annotation_payload),
            )
        )
    return annotations


def _extract_yolo26_segmentation_polygons(
    annotation_payload: dict[str, object],
) -> list[list[list[float]] | None] | None:
    """从 COCO annotation 提取 segmentation 多边形。"""

    segmentation = annotation_payload.get("segmentation")
    if not isinstance(segmentation, list) or len(segmentation) == 0:
        return None
    if isinstance(segmentation[0], list):
        return segmentation
    return None


def _build_yolo26_segmentation_label_mapping(
    category_map: dict[int, str],
) -> tuple[tuple[str, ...], dict[int, int]]:
    """生成连续类别索引。"""

    sorted_categories = sorted(category_map.items())
    category_id_to_index = {
        category_id: index for index, (category_id, _) in enumerate(sorted_categories)
    }
    labels = tuple(name for _, name in sorted_categories)
    return labels, category_id_to_index


def _remap_yolo26_segmentation_annotation_classes(
    annotations: list[Yolo26SegmentationTrainingAnnotation],
    category_id_to_index: dict[int, int],
) -> list[Yolo26SegmentationTrainingAnnotation]:
    """把原始 category_id 重映射为连续 class index。"""

    return [
        Yolo26SegmentationTrainingAnnotation(
            image_path=annotation.image_path,
            boxes_xywh=annotation.boxes_xywh,
            class_ids=[
                category_id_to_index.get(class_id, 0)
                for class_id in annotation.class_ids
            ],
            segmentations=annotation.segmentations,
        )
        for annotation in annotations
    ]


__all__ = [
    "Yolo26SegmentationTrainingAnnotation",
    "Yolo26SegmentationTrainingManifest",
    "load_yolo26_segmentation_training_manifest",
]
