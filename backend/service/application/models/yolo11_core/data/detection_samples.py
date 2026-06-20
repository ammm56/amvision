"""YOLO11 detection 训练样本解析。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo11_core.data.detection import (
    Yolo11DetectionResolvedSplit,
    Yolo11DetectionTrainingAnnotation,
    Yolo11DetectionTrainingSample,
)


def load_yolo11_detection_training_samples(
    *,
    split: Yolo11DetectionResolvedSplit,
) -> tuple[
    tuple[Yolo11DetectionTrainingSample, ...],
    tuple[str, ...],
    tuple[int, ...],
]:
    """把 YOLO11 detection split 转成训练阶段可直接消费的样本列表。"""

    annotation_payload = split.annotation_payload
    categories_payload = annotation_payload.get("categories", [])
    images_payload = annotation_payload.get("images", [])
    annotations_payload = annotation_payload.get("annotations", [])
    if not isinstance(categories_payload, list) or not isinstance(images_payload, list):
        raise InvalidRequestError(
            "YOLO11 detection annotation 结构不合法",
            details={
                "split_name": split.name,
                "annotation_file": (
                    str(split.annotation_file)
                    if split.annotation_file is not None
                    else None
                ),
            },
        )

    category_names: list[str] = []
    category_ids: list[int] = []
    category_id_to_index: dict[int, int] = {}
    for category_item in categories_payload:
        if not isinstance(category_item, dict):
            continue
        category_id = category_item.get("id")
        category_name = str(category_item.get("name") or "").strip()
        if not isinstance(category_id, int) or not category_name:
            continue
        category_id_to_index[category_id] = len(category_names)
        category_names.append(category_name)
        category_ids.append(category_id)
    if not category_names:
        raise InvalidRequestError("YOLO11 detection 训练输入缺少有效的 categories")

    image_meta_by_id: dict[int, dict[str, object]] = {}
    for image_item in images_payload:
        if not isinstance(image_item, dict):
            continue
        image_id = image_item.get("id")
        file_name = str(image_item.get("file_name") or "").strip()
        width = image_item.get("width")
        height = image_item.get("height")
        if (
            not isinstance(image_id, int)
            or not file_name
            or not isinstance(width, int)
            or not isinstance(height, int)
            or width <= 0
            or height <= 0
        ):
            continue
        image_meta_by_id[image_id] = {
            "file_name": file_name,
            "width": width,
            "height": height,
            "annotations": [],
        }

    for annotation_item in (
        annotations_payload if isinstance(annotations_payload, list) else ()
    ):
        if not isinstance(annotation_item, dict):
            continue
        image_id = annotation_item.get("image_id")
        category_id = annotation_item.get("category_id")
        bbox = annotation_item.get("bbox")
        image_meta = image_meta_by_id.get(image_id if isinstance(image_id, int) else -1)
        category_index = category_id_to_index.get(
            category_id if isinstance(category_id, int) else -1
        )
        if (
            image_meta is None
            or category_index is None
            or not isinstance(bbox, list | tuple)
            or len(bbox) != 4
        ):
            continue
        x, y, width, height = bbox
        if not all(isinstance(item, int | float) for item in (x, y, width, height)):
            continue
        if float(width) <= 0.0 or float(height) <= 0.0:
            continue
        image_width = int(image_meta["width"])
        image_height = int(image_meta["height"])
        x1 = max(0.0, min(float(x), float(image_width)))
        y1 = max(0.0, min(float(y), float(image_height)))
        x2 = max(0.0, min(float(x + width), float(image_width)))
        y2 = max(0.0, min(float(y + height), float(image_height)))
        if x2 <= x1 or y2 <= y1:
            continue
        image_meta["annotations"].append(
            Yolo11DetectionTrainingAnnotation(
                category_index=category_index,
                category_id=int(category_id),
                bbox_xyxy=(x1, y1, x2, y2),
            )
        )

    resolved_samples: list[Yolo11DetectionTrainingSample] = []
    for image_id, image_meta in image_meta_by_id.items():
        file_name = str(image_meta["file_name"])
        width = int(image_meta["width"])
        height = int(image_meta["height"])
        annotations = tuple(
            item
            for item in image_meta["annotations"]
            if isinstance(item, Yolo11DetectionTrainingAnnotation)
        )
        image_path = split.image_root / file_name
        if not image_path.is_file():
            continue
        resolved_samples.append(
            Yolo11DetectionTrainingSample(
                image_id=image_id,
                image_path=image_path,
                image_width=width,
                image_height=height,
                annotations=annotations,
            )
        )
    return tuple(resolved_samples), tuple(category_names), tuple(category_ids)


__all__ = ["load_yolo11_detection_training_samples"]
