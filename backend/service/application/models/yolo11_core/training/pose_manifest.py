"""YOLO11 pose DatasetExport manifest 解析。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.contracts.datasets.exports.dataset_formats import (
    COCO_KEYPOINTS_DATASET_FORMAT,
    YOLO_POSE_DATASET_FORMAT,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_dataset_manifest_support import (
    build_coco_payload_from_yolo_pose_split,
    normalize_yolo_category_names,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


YOLO11_POSE_DEFAULT_KEYPOINT_SHAPE = (17, 3)


@dataclass(frozen=True)
class Yolo11PoseTrainingAnnotation:
    """描述一张 YOLO11 pose 训练图片及其标注。"""

    image_path: str
    boxes_xywh: list[list[float]]
    class_ids: list[int]
    keypoints: list[list[float]] | None = None


@dataclass(frozen=True)
class Yolo11PoseTrainingManifest:
    """描述 YOLO11 pose 训练 manifest 解析结果。"""

    labels: tuple[str, ...]
    train_annotations: list[Yolo11PoseTrainingAnnotation]
    val_annotations: list[Yolo11PoseTrainingAnnotation]
    keypoint_shape: tuple[int, int]


def load_yolo11_pose_training_manifest(
    *,
    dataset_storage: LocalDatasetStorage,
    manifest_payload: dict[str, object],
) -> Yolo11PoseTrainingManifest:
    """加载 COCO keypoints 或 YOLO pose DatasetExport manifest。"""

    labels, train_annotations, val_annotations = _load_pose_annotations(
        dataset_storage=dataset_storage,
        manifest=manifest_payload,
    )
    keypoint_shape = resolve_yolo11_pose_keypoint_shape(
        manifest=manifest_payload,
        train_annotations=train_annotations,
        val_annotations=val_annotations,
    )
    return Yolo11PoseTrainingManifest(
        labels=labels,
        train_annotations=train_annotations,
        val_annotations=val_annotations,
        keypoint_shape=keypoint_shape,
    )


def resolve_yolo11_pose_keypoint_shape(
    *,
    manifest: dict[str, object],
    train_annotations: list[Yolo11PoseTrainingAnnotation],
    val_annotations: list[Yolo11PoseTrainingAnnotation],
) -> tuple[int, int]:
    """从 manifest 或标注内容推断 YOLO11 pose keypoint shape。"""

    manifest_shape = read_yolo11_pose_keypoint_shape(manifest)
    if manifest_shape is not None:
        return manifest_shape
    for annotation in (*train_annotations, *val_annotations):
        for keypoints in annotation.keypoints or []:
            if len(keypoints) > 0 and len(keypoints) % 3 == 0:
                return (len(keypoints) // 3, 3)
    return YOLO11_POSE_DEFAULT_KEYPOINT_SHAPE


def read_yolo11_pose_keypoint_shape(
    manifest: dict[str, object],
) -> tuple[int, int] | None:
    """从 manifest metadata 中读取可选 kpt_shape。"""

    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict):
        return None
    raw_shape = metadata.get("kpt_shape")
    if not isinstance(raw_shape, list | tuple) or len(raw_shape) < 2:
        return None
    try:
        keypoint_count = int(raw_shape[0])
        point_dimensions = int(raw_shape[1])
    except (TypeError, ValueError):
        return None
    if keypoint_count <= 0 or point_dimensions not in {2, 3}:
        return None
    return (keypoint_count, point_dimensions)


def _load_pose_annotations(
    *,
    dataset_storage: LocalDatasetStorage,
    manifest: dict[str, object],
) -> tuple[
    tuple[str, ...],
    list[Yolo11PoseTrainingAnnotation],
    list[Yolo11PoseTrainingAnnotation],
]:
    """加载并规整 YOLO11 pose 训练和验证标注。"""

    splits = manifest.get("splits", [])
    format_id = str(manifest.get("format_id") or COCO_KEYPOINTS_DATASET_FORMAT).strip()
    yolo_category_names = (
        normalize_yolo_category_names(
            category_names=manifest.get("category_names"),
            format_label="YOLO pose",
        )
        if format_id == YOLO_POSE_DATASET_FORMAT
        else ()
    )
    all_categories: dict[int, str] = {}
    train_annotations: list[Yolo11PoseTrainingAnnotation] = []
    val_annotations: list[Yolo11PoseTrainingAnnotation] = []
    for split in splits or []:
        if not isinstance(split, dict):
            continue
        split_name = str(split.get("name", ""))
        image_root = str(split.get("image_root", ""))
        payload = _load_pose_split_payload(
            dataset_storage=dataset_storage,
            manifest=manifest,
            split=split,
            split_name=split_name,
            image_root=image_root,
            format_id=format_id,
            yolo_category_names=yolo_category_names,
        )
        if payload is None:
            continue
        all_categories.update(_collect_categories(payload))
        records = _build_pose_split_records(
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
    return (
        labels,
        _remap_pose_categories(train_annotations, category_id_map),
        _remap_pose_categories(val_annotations, category_id_map),
    )


def _load_pose_split_payload(
    *,
    dataset_storage: LocalDatasetStorage,
    manifest: dict[str, object],
    split: dict[str, object],
    split_name: str,
    image_root: str,
    format_id: str,
    yolo_category_names: tuple[str, ...],
) -> dict[str, object] | None:
    """读取单个 pose split 的 COCO 风格 payload。"""

    if format_id == YOLO_POSE_DATASET_FORMAT:
        label_root = str(split.get("label_root", ""))
        image_root_path = dataset_storage.resolve(image_root)
        label_root_path = dataset_storage.resolve(label_root)
        if not image_root_path.is_dir():
            raise InvalidRequestError(
                "YOLO11 pose 训练 split 缺少图片目录",
                details={"split_name": split_name, "image_root": image_root},
            )
        if not label_root_path.is_dir():
            raise InvalidRequestError(
                "YOLO11 pose 训练 split 缺少标签目录",
                details={"split_name": split_name, "label_root": label_root},
            )
        return build_coco_payload_from_yolo_pose_split(
            split_name=split_name,
            image_root=image_root_path,
            label_root=label_root_path,
            category_names=yolo_category_names,
            pose_shape=read_yolo11_pose_keypoint_shape(manifest),
        )

    annotation_file = str(split.get("annotation_file", ""))
    annotation_path = dataset_storage.resolve(annotation_file)
    if not annotation_path.is_file():
        return None
    payload = dataset_storage.read_json(annotation_file)
    return payload if isinstance(payload, dict) else None


def _collect_categories(payload: dict[str, object]) -> dict[int, str]:
    """从 COCO payload 中收集类别。"""

    categories: dict[int, str] = {}
    for category in payload.get("categories") or []:
        if isinstance(category, dict):
            categories[int(category.get("id", -1))] = str(category.get("name", ""))
    return categories


def _build_pose_split_records(
    *,
    dataset_storage: LocalDatasetStorage,
    payload: dict[str, object],
    image_root: str,
) -> list[Yolo11PoseTrainingAnnotation]:
    """把 COCO payload 转成 YOLO11 pose 训练样本。"""

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

    records: list[Yolo11PoseTrainingAnnotation] = []
    for image_id, file_name in image_map.items():
        boxes: list[list[float]] = []
        class_ids: list[int] = []
        keypoints: list[list[float]] = []
        for annotation in annotations_by_image.get(image_id, []):
            bbox = annotation.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            boxes.append([float(value) for value in bbox])
            class_ids.append(int(annotation.get("category_id", 0)))
            raw_keypoints = annotation.get("keypoints")
            keypoints.append(
                [float(value) for value in raw_keypoints]
                if isinstance(raw_keypoints, list) and raw_keypoints
                else []
            )
        if boxes:
            records.append(
                Yolo11PoseTrainingAnnotation(
                    image_path=str(
                        dataset_storage.resolve(f"{image_root}/{file_name}")
                    ),
                    boxes_xywh=boxes,
                    class_ids=class_ids,
                    keypoints=keypoints,
                )
            )
    return records


def _remap_pose_categories(
    annotations: list[Yolo11PoseTrainingAnnotation],
    category_id_map: dict[int, int],
) -> list[Yolo11PoseTrainingAnnotation]:
    """把原始 category id 映射为连续训练类别索引。"""

    return [
        Yolo11PoseTrainingAnnotation(
            image_path=annotation.image_path,
            boxes_xywh=annotation.boxes_xywh,
            class_ids=[
                category_id_map.get(category_id, 0)
                for category_id in annotation.class_ids
            ],
            keypoints=annotation.keypoints,
        )
        for annotation in annotations
    ]


__all__ = [
    "YOLO11_POSE_DEFAULT_KEYPOINT_SHAPE",
    "Yolo11PoseTrainingAnnotation",
    "Yolo11PoseTrainingManifest",
    "load_yolo11_pose_training_manifest",
    "read_yolo11_pose_keypoint_shape",
    "resolve_yolo11_pose_keypoint_shape",
]
