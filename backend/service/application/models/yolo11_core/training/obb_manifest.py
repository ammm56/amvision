"""YOLO11 OBB DatasetExport manifest 解析。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class Yolo11ObbTrainingAnnotation:
    """描述一张 YOLO11 OBB 训练图片及其标注。"""

    image_path: str
    boxes_xywhr: list[list[float]]
    class_ids: list[int]


@dataclass(frozen=True)
class Yolo11ObbTrainingManifest:
    """描述 YOLO11 OBB 训练 manifest 解析结果。"""

    labels: tuple[str, ...]
    train_annotations: list[Yolo11ObbTrainingAnnotation]
    val_annotations: list[Yolo11ObbTrainingAnnotation]


def load_yolo11_obb_training_manifest(
    *,
    dataset_storage: LocalDatasetStorage,
    manifest_payload: dict[str, object],
) -> Yolo11ObbTrainingManifest:
    """加载 DOTA OBB 或 COCO + angle DatasetExport manifest。"""

    all_categories: dict[int, str] = {}
    train_annotations: list[Yolo11ObbTrainingAnnotation] = []
    val_annotations: list[Yolo11ObbTrainingAnnotation] = []
    for split in manifest_payload.get("splits", []) or []:
        if not isinstance(split, dict):
            continue
        split_name = str(split.get("name", ""))
        image_root = str(split.get("image_root", ""))
        annotation_file = str(split.get("annotation_file", ""))
        annotation_path = dataset_storage.resolve(annotation_file)
        if not annotation_path.is_file():
            continue
        payload = dataset_storage.read_json(annotation_file)
        if not isinstance(payload, dict):
            continue
        all_categories.update(_collect_obb_categories(payload))
        records = _build_obb_split_records(
            dataset_storage=dataset_storage,
            payload=payload,
            image_root=image_root,
        )
        if split_name == "train":
            train_annotations = records
        elif split_name in {"val", "valid", "validation"}:
            val_annotations = records

    sorted_categories = sorted(all_categories.items())
    category_id_map = {
        category_id: index for index, (category_id, _) in enumerate(sorted_categories)
    }
    labels = tuple(name for _, name in sorted_categories)
    return Yolo11ObbTrainingManifest(
        labels=labels,
        train_annotations=_remap_obb_categories(train_annotations, category_id_map),
        val_annotations=_remap_obb_categories(val_annotations, category_id_map),
    )


def _collect_obb_categories(payload: dict[str, object]) -> dict[int, str]:
    """从 OBB payload 中收集类别。"""

    categories: dict[int, str] = {}
    for category in payload.get("categories") or []:
        if isinstance(category, dict):
            categories[int(category.get("id", -1))] = str(category.get("name", ""))
    return categories


def _build_obb_split_records(
    *,
    dataset_storage: LocalDatasetStorage,
    payload: dict[str, object],
    image_root: str,
) -> list[Yolo11ObbTrainingAnnotation]:
    """把 OBB payload 转成 YOLO11 OBB 训练样本。"""

    image_map: dict[int, str] = {}
    for image in payload.get("images") or []:
        if isinstance(image, dict):
            image_map[int(image.get("id", -1))] = str(image.get("file_name", ""))
    annotations_by_image: dict[int, list[dict[str, Any]]] = {}
    for annotation in payload.get("annotations") or []:
        if not isinstance(annotation, dict):
            continue
        image_id = int(annotation.get("image_id", -1))
        annotations_by_image.setdefault(image_id, []).append(annotation)

    records: list[Yolo11ObbTrainingAnnotation] = []
    for image_id, file_name in image_map.items():
        boxes_xywhr: list[list[float]] = []
        class_ids: list[int] = []
        for annotation in annotations_by_image.get(image_id, []):
            box_xywhr = parse_yolo11_obb_annotation(annotation)
            if box_xywhr is None:
                continue
            boxes_xywhr.append(box_xywhr)
            class_ids.append(int(annotation.get("category_id", 0)))
        if boxes_xywhr:
            records.append(
                Yolo11ObbTrainingAnnotation(
                    image_path=str(
                        dataset_storage.resolve(f"{image_root}/{file_name}")
                    ),
                    boxes_xywhr=boxes_xywhr,
                    class_ids=class_ids,
                )
            )
    return records


def parse_yolo11_obb_annotation(annotation: dict[str, Any]) -> list[float] | None:
    """解析单条 OBB 标注为 [cx, cy, w, h, angle]。"""

    rbox = annotation.get("rbox")
    if isinstance(rbox, list) and len(rbox) == 5:
        return [float(value) for value in rbox]

    polygon = annotation.get("poly") or annotation.get("polygon")
    if isinstance(polygon, list) and len(polygon) == 8:
        return polygon_to_yolo11_xywhr([float(value) for value in polygon])

    bbox = annotation.get("bbox")
    angle = annotation.get("angle")
    if isinstance(bbox, list) and len(bbox) == 4:
        x, y, width, height = [float(value) for value in bbox]
        if width <= 0 or height <= 0:
            return None
        return [
            x + width / 2.0,
            y + height / 2.0,
            width,
            height,
            float(angle) if angle is not None else 0.0,
        ]
    return None


def polygon_to_yolo11_xywhr(polygon: list[float]) -> list[float] | None:
    """把四角点 polygon 转成 [cx, cy, w, h, angle]。"""

    import numpy as np

    points = np.array(polygon, dtype=np.float64).reshape(4, 2)
    order = np.argsort(points[:, 0])
    left = points[order[:2]]
    right = points[order[2:]]
    if left[0, 1] > left[1, 1]:
        left = left[::-1]
    if right[0, 1] > right[1, 1]:
        right = right[::-1]
    p1, p4 = left[0], left[1]
    p2 = right[0]
    width = float(np.linalg.norm(p1 - p2))
    height = float(np.linalg.norm(p1 - p4))
    if width <= 0 or height <= 0:
        return None
    return [
        float(np.mean(points[:, 0])),
        float(np.mean(points[:, 1])),
        width,
        height,
        float(np.arctan2(p2[1] - p1[1], p2[0] - p1[0])),
    ]


def _remap_obb_categories(
    annotations: list[Yolo11ObbTrainingAnnotation],
    category_id_map: dict[int, int],
) -> list[Yolo11ObbTrainingAnnotation]:
    """把原始 category id 映射为连续训练类别索引。"""

    return [
        Yolo11ObbTrainingAnnotation(
            image_path=annotation.image_path,
            boxes_xywhr=annotation.boxes_xywhr,
            class_ids=[
                category_id_map.get(category_id, 0)
                for category_id in annotation.class_ids
            ],
        )
        for annotation in annotations
    ]


__all__ = [
    "Yolo11ObbTrainingAnnotation",
    "Yolo11ObbTrainingManifest",
    "load_yolo11_obb_training_manifest",
    "parse_yolo11_obb_annotation",
    "polygon_to_yolo11_xywhr",
]
