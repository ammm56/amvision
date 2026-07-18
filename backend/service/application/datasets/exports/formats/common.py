"""数据集导出格式共用函数。"""

from __future__ import annotations

from pathlib import PurePosixPath

from backend.contracts.datasets.exports.coco_detection_export import CocoDetectionAnnotation
from backend.contracts.datasets.exports.coco_instance_segmentation_export import COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT
from backend.contracts.datasets.exports.coco_keypoints_export import COCO_KEYPOINTS_DATASET_FORMAT
from backend.contracts.datasets.exports.dataset_formats import (
    DOTA_OBB_DATASET_FORMAT,
    IMAGENET_CLASSIFICATION_DATASET_FORMAT,
    YOLO_DETECTION_DATASET_FORMAT,
    YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    YOLO_POSE_DATASET_FORMAT,
)
from backend.contracts.datasets.exports.voc_detection_export import VOC_DETECTION_DATASET_FORMAT
from backend.contracts.datasets.exports.coco_detection_export import COCO_DETECTION_DATASET_FORMAT
from backend.service.domain.datasets.dataset_version import (
    DatasetSample,
    DatasetVersion,
    PoseAnnotation,
)


def _build_coco_annotation_entry(annotation: CocoDetectionAnnotation) -> dict[str, object]:
    """把 COCO annotation 序列化为字典，包含 metadata 中的 segmentation/keypoints。"""

    entry: dict[str, object] = {
        "id": annotation.annotation_id,
        "image_id": annotation.image_id,
        "category_id": annotation.category_id,
        "bbox": list(annotation.bbox_xywh),
        "area": annotation.area,
        "iscrowd": annotation.iscrowd,
    }
    meta = annotation.metadata
    if isinstance(meta, dict):
        if "segmentation" in meta:
            entry["segmentation"] = meta["segmentation"]
        if "keypoints" in meta:
            entry["keypoints"] = meta["keypoints"]
        if "num_keypoints" in meta:
            entry["num_keypoints"] = meta["num_keypoints"]
    return entry


def _build_version_image_relative_path(
    *,
    dataset_version: DatasetVersion,
    sample: DatasetSample,
) -> str:
    """计算 DatasetVersion 中某张图片的相对路径。"""

    image_object_key = str(
        sample.metadata.get("image_object_key")
        or f"images/{sample.split}/{sample.sample_id}/{sample.file_name}"
    ).lstrip("/")
    return (
        f"projects/{dataset_version.project_id}/datasets/{dataset_version.dataset_id}/versions/"
        f"{dataset_version.dataset_version_id}/{image_object_key}"
    )


def _build_collision_safe_image_names(
    samples: tuple[DatasetSample, ...],
    *,
    match_by_stem: bool = False,
) -> dict[str, str]:
    """生成不会在目标格式中互相覆盖的相对图片名。"""

    rows: list[tuple[DatasetSample, PurePosixPath, str]] = []
    counts: dict[str, int] = {}
    for sample in samples:
        normalized = PurePosixPath(sample.file_name.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts or not normalized.name:
            raise ValueError(f"样本文件名不是安全相对路径: sample_id={sample.sample_id}")
        collision_path = normalized.with_suffix("") if match_by_stem else normalized
        key = collision_path.as_posix().casefold()
        counts[key] = counts.get(key, 0) + 1
        rows.append((sample, normalized, key))

    result: dict[str, str] = {}
    for sample, normalized, key in rows:
        if counts[key] == 1:
            result[sample.sample_id] = normalized.as_posix()
            continue
        renamed = normalized.parent / f"{sample.sample_id}{normalized.suffix}"
        result[sample.sample_id] = renamed.as_posix()
    if len(set(value.casefold() for value in result.values())) != len(result):
        raise ValueError("样本 sample_id 无法生成唯一的导出文件名")
    return result

def _dataset_export_format_matches_task_type(
    *,
    format_id: str,
    task_type: str,
) -> bool:
    """判断导出格式与 DatasetVersion.task_type 是否匹配。"""

    format_to_task_types = {
        COCO_DETECTION_DATASET_FORMAT: {"detection"},
        VOC_DETECTION_DATASET_FORMAT: {"detection"},
        YOLO_DETECTION_DATASET_FORMAT: {"detection"},
        COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT: {"segmentation"},
        YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT: {"segmentation"},
        COCO_KEYPOINTS_DATASET_FORMAT: {"pose"},
        YOLO_POSE_DATASET_FORMAT: {"pose"},
        IMAGENET_CLASSIFICATION_DATASET_FORMAT: {"classification"},
        DOTA_OBB_DATASET_FORMAT: {"obb"},
    }
    return task_type in format_to_task_types.get(format_id, set())

def _resolve_pose_keypoint_shape(
    split_samples: tuple[tuple[str, tuple[DatasetSample, ...]], ...],
) -> tuple[int, int]:
    """从 PoseAnnotation 中解析 YOLO pose 导出需要的 kpt_shape。"""

    for _split_name, samples in split_samples:
        for sample in samples:
            for annotation in sample.annotations:
                if not isinstance(annotation, PoseAnnotation):
                    continue
                keypoints = annotation.keypoints
                if not isinstance(keypoints, list) or not keypoints:
                    continue
                if len(keypoints) % 3 != 0:
                    continue
                return (len(keypoints) // 3, 3)
    return (17, 3)
