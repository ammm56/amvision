"""YOLOv8 detection DatasetExport split 解析。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.contracts.datasets.exports.dataset_formats import (
    COCO_DETECTION_DATASET_FORMAT,
    YOLO_DETECTION_DATASET_FORMAT,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolov8_core.data.detection_types import (
    YoloV8DetectionResolvedSplit,
)


def resolve_yolov8_detection_splits(
    *,
    dataset_storage: Any,
    cv2_module: Any,
    manifest_payload: dict[str, object],
) -> tuple[YoloV8DetectionResolvedSplit, ...]:
    """从 DatasetExport manifest 解析 YOLOv8 detection 可用 split。"""

    format_id = str(manifest_payload.get("format_id") or COCO_DETECTION_DATASET_FORMAT).strip()
    if format_id == YOLO_DETECTION_DATASET_FORMAT:
        return _resolve_yolo_detection_splits(
            dataset_storage=dataset_storage,
            cv2_module=cv2_module,
            manifest_payload=manifest_payload,
        )
    return _resolve_coco_detection_splits(
        dataset_storage=dataset_storage,
        manifest_payload=manifest_payload,
    )


def resolve_yolov8_detection_train_split(
    resolved_splits: tuple[YoloV8DetectionResolvedSplit, ...],
) -> YoloV8DetectionResolvedSplit:
    """优先选择 YOLOv8 detection train split。"""

    for split in resolved_splits:
        if split.name.lower() == "train":
            return split
    return resolved_splits[0]


def resolve_yolov8_detection_validation_split(
    resolved_splits: tuple[YoloV8DetectionResolvedSplit, ...],
) -> YoloV8DetectionResolvedSplit | None:
    """选择 YOLOv8 detection validation split。"""

    validation_names = {"val", "valid", "validation", "test"}
    for split in resolved_splits:
        if split.name.lower() in validation_names:
            return split
    return None


def _resolve_coco_detection_splits(
    *,
    dataset_storage: Any,
    manifest_payload: dict[str, object],
) -> tuple[YoloV8DetectionResolvedSplit, ...]:
    """从 DatasetExport manifest 解析 COCO detection split。"""

    splits_payload = manifest_payload.get("splits")
    if not isinstance(splits_payload, list):
        raise InvalidRequestError("YOLOv8 detection 训练输入 manifest 缺少 splits 定义")
    resolved_splits: list[YoloV8DetectionResolvedSplit] = []
    for split_item in splits_payload:
        if not isinstance(split_item, dict):
            continue
        split_name = str(split_item.get("name") or "").strip()
        image_root = str(split_item.get("image_root") or "").strip()
        annotation_file = str(split_item.get("annotation_file") or "").strip()
        if not split_name or not image_root or not annotation_file:
            continue
        annotation_path = dataset_storage.resolve(annotation_file)
        image_root_path = dataset_storage.resolve(image_root)
        if not annotation_path.is_file():
            raise InvalidRequestError(
                "YOLOv8 detection 训练输入 split 缺少 annotation 文件",
                details={"split_name": split_name, "annotation_file": annotation_file},
            )
        if not image_root_path.is_dir():
            raise InvalidRequestError(
                "YOLOv8 detection 训练输入 split 缺少图片目录",
                details={"split_name": split_name, "image_root": image_root},
            )
        annotation_payload = json.loads(annotation_path.read_text(encoding="utf-8"))
        image_items = annotation_payload.get("images", [])
        sample_count = len(image_items) if isinstance(image_items, list) else 0
        resolved_splits.append(
            YoloV8DetectionResolvedSplit(
                name=split_name,
                image_root=image_root_path,
                sample_count=sample_count,
                annotation_payload=annotation_payload,
                annotation_file=annotation_path,
            )
        )
    if not resolved_splits:
        raise InvalidRequestError("YOLOv8 detection 训练输入 manifest 没有可用的 split")
    return tuple(resolved_splits)


def _resolve_yolo_detection_splits(
    *,
    dataset_storage: Any,
    cv2_module: Any,
    manifest_payload: dict[str, object],
) -> tuple[YoloV8DetectionResolvedSplit, ...]:
    """从 DatasetExport manifest 解析 YOLO detection split。"""

    splits_payload = manifest_payload.get("splits")
    if not isinstance(splits_payload, list):
        raise InvalidRequestError("YOLOv8 detection 训练输入 manifest 缺少 splits 定义")
    category_names_payload = manifest_payload.get("category_names")
    category_names = tuple(
        normalized_name
        for item in (category_names_payload if isinstance(category_names_payload, list | tuple) else ())
        if (normalized_name := str(item).strip())
    )

    resolved_splits: list[YoloV8DetectionResolvedSplit] = []
    for split_item in splits_payload:
        if not isinstance(split_item, dict):
            continue
        split_name = str(split_item.get("name") or "").strip()
        image_root = str(split_item.get("image_root") or "").strip()
        annotation_file = str(split_item.get("annotation_file") or "").strip()
        label_root = str(split_item.get("label_root") or "").strip()
        if not split_name or not image_root:
            continue
        image_root_path = dataset_storage.resolve(image_root)
        if annotation_file:
            annotation_path = dataset_storage.resolve(annotation_file)
            if not annotation_path.is_file():
                raise InvalidRequestError(
                    "YOLOv8 detection 训练输入 split 缺少 annotation 文件",
                    details={"split_name": split_name, "annotation_file": annotation_file},
                )
            if not image_root_path.is_dir():
                raise InvalidRequestError(
                    "YOLOv8 detection 训练输入 split 缺少图片目录",
                    details={"split_name": split_name, "image_root": image_root},
                )
            annotation_payload = json.loads(annotation_path.read_text(encoding="utf-8"))
            image_items = annotation_payload.get("images", [])
            sample_count = len(image_items) if isinstance(image_items, list) else 0
            resolved_splits.append(
                YoloV8DetectionResolvedSplit(
                    name=split_name,
                    image_root=image_root_path,
                    sample_count=sample_count,
                    annotation_payload=annotation_payload,
                    annotation_file=annotation_path,
                )
            )
            continue
        if not label_root:
            continue
        if not category_names:
            raise InvalidRequestError("YOLOv8 detection 训练输入缺少有效的 category_names")
        label_root_path = dataset_storage.resolve(label_root)
        if not image_root_path.is_dir():
            raise InvalidRequestError(
                "YOLOv8 detection 训练输入 split 缺少图片目录",
                details={"split_name": split_name, "image_root": image_root},
            )
        if not label_root_path.is_dir():
            raise InvalidRequestError(
                "YOLOv8 detection 训练输入 split 缺少标签目录",
                details={"split_name": split_name, "label_root": label_root},
            )
        annotation_payload = _build_coco_annotation_payload_from_yolo_detection_split(
            cv2_module=cv2_module,
            split_name=split_name,
            image_root=image_root_path,
            label_root=label_root_path,
            category_names=category_names,
        )
        image_items = annotation_payload.get("images", [])
        sample_count = len(image_items) if isinstance(image_items, list) else 0
        resolved_splits.append(
            YoloV8DetectionResolvedSplit(
                name=split_name,
                image_root=image_root_path,
                sample_count=sample_count,
                annotation_payload=annotation_payload,
            )
        )
    if not resolved_splits:
        raise InvalidRequestError("YOLOv8 detection 训练输入 manifest 没有可用的 split")
    return tuple(resolved_splits)


def _build_coco_annotation_payload_from_yolo_detection_split(
    *,
    cv2_module: Any,
    split_name: str,
    image_root: Path,
    label_root: Path,
    category_names: tuple[str, ...],
) -> dict[str, object]:
    """把 YOLO detection 标签目录转换成内存中的 COCO payload。"""

    images_payload: list[dict[str, object]] = []
    annotations_payload: list[dict[str, object]] = []
    categories_payload = [
        {"id": category_index + 1, "name": category_name}
        for category_index, category_name in enumerate(category_names)
    ]
    annotation_id = 1
    for image_id, image_path in enumerate(_iter_image_files(image_root), start=1):
        image_height, image_width = _read_image_shape(
            cv2_module=cv2_module,
            image_path=image_path,
        )
        relative_image_path = image_path.relative_to(image_root)
        images_payload.append(
            {
                "id": image_id,
                "file_name": relative_image_path.as_posix(),
                "width": image_width,
                "height": image_height,
            }
        )
        label_path = (label_root / relative_image_path).with_suffix(".txt")
        annotation_rows, annotation_id = _parse_yolo_detection_label_file(
            label_path=label_path,
            split_name=split_name,
            image_id=image_id,
            image_width=image_width,
            image_height=image_height,
            category_count=len(category_names),
            next_annotation_id=annotation_id,
        )
        annotations_payload.extend(annotation_rows)
    return {
        "images": images_payload,
        "annotations": annotations_payload,
        "categories": categories_payload,
    }


def _iter_image_files(image_root: Path) -> tuple[Path, ...]:
    """收集目录下全部 YOLOv8 detection 训练图片。"""

    image_suffixes = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
    return tuple(
        sorted(
            (
                candidate
                for candidate in image_root.rglob("*")
                if candidate.is_file() and candidate.suffix.lower() in image_suffixes
            ),
            key=lambda item: item.as_posix().lower(),
        )
    )


def _read_image_shape(*, cv2_module: Any, image_path: Path) -> tuple[int, int]:
    """读取一张 YOLOv8 detection 训练图片尺寸。"""

    image = cv2_module.imread(str(image_path), cv2_module.IMREAD_UNCHANGED)
    if image is None:
        raise InvalidRequestError(
            "YOLOv8 detection 训练输入图片无法读取",
            details={"image_path": str(image_path)},
        )
    image_height = int(image.shape[0])
    image_width = int(image.shape[1])
    if image_height <= 0 or image_width <= 0:
        raise InvalidRequestError(
            "YOLOv8 detection 训练输入图片尺寸无效",
            details={"image_path": str(image_path)},
        )
    return image_height, image_width


def _parse_yolo_detection_label_file(
    *,
    label_path: Path,
    split_name: str,
    image_id: int,
    image_width: int,
    image_height: int,
    category_count: int,
    next_annotation_id: int,
) -> tuple[list[dict[str, object]], int]:
    """解析一个 YOLO detection label 文件。"""

    if not label_path.is_file():
        return [], next_annotation_id
    annotation_rows: list[dict[str, object]] = []
    annotation_id = next_annotation_id
    for line_index, raw_line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            raise InvalidRequestError(
                "YOLOv8 detection 标注行必须是 5 列",
                details={
                    "split_name": split_name,
                    "label_file": str(label_path),
                    "line_index": line_index,
                },
            )
        try:
            category_index = int(parts[0])
            x_center = float(parts[1])
            y_center = float(parts[2])
            box_width = float(parts[3])
            box_height = float(parts[4])
        except ValueError as error:
            raise InvalidRequestError(
                "YOLOv8 detection 标注行包含非法数字",
                details={
                    "split_name": split_name,
                    "label_file": str(label_path),
                    "line_index": line_index,
                },
            ) from error
        if category_index < 0 or category_index >= category_count:
            raise InvalidRequestError(
                "YOLOv8 detection 标注行类别索引越界",
                details={
                    "split_name": split_name,
                    "label_file": str(label_path),
                    "line_index": line_index,
                    "category_index": category_index,
                    "category_count": category_count,
                },
            )
        if box_width <= 0.0 or box_height <= 0.0:
            continue
        normalized_x1 = x_center - (box_width / 2.0)
        normalized_y1 = y_center - (box_height / 2.0)
        normalized_x2 = x_center + (box_width / 2.0)
        normalized_y2 = y_center + (box_height / 2.0)
        x1 = max(0.0, min(normalized_x1 * float(image_width), float(image_width)))
        y1 = max(0.0, min(normalized_y1 * float(image_height), float(image_height)))
        x2 = max(0.0, min(normalized_x2 * float(image_width), float(image_width)))
        y2 = max(0.0, min(normalized_y2 * float(image_height), float(image_height)))
        bbox_width = max(0.0, x2 - x1)
        bbox_height = max(0.0, y2 - y1)
        if bbox_width <= 0.0 or bbox_height <= 0.0:
            continue
        annotation_rows.append(
            {
                "id": annotation_id,
                "image_id": image_id,
                "category_id": category_index + 1,
                "bbox": [x1, y1, bbox_width, bbox_height],
                "area": bbox_width * bbox_height,
                "iscrowd": 0,
            }
        )
        annotation_id += 1
    return annotation_rows, annotation_id


__all__ = [
    "resolve_yolov8_detection_splits",
    "resolve_yolov8_detection_train_split",
    "resolve_yolov8_detection_validation_split",
]
