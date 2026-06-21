"""数据集导入格式解析共用函数。"""

from __future__ import annotations

from backend.service.domain.datasets.dataset_version import (
    DatasetAnnotation,
    DetectionAnnotation,
    InstanceSegmentationAnnotation,
    ObbAnnotation,
    PoseAnnotation,
)


def _build_annotation_for_task(
    *, task_type: str, annotation_id: str, category_id: int,
    bbox_xywh: tuple[float, float, float, float],
    iscrowd: int, area: float | None, annotation_payload: dict[str, object],
) -> DatasetAnnotation:
    """根据 task_type 创建对应的标注对象。"""

    extra_meta = {
        key: value for key, value in annotation_payload.items()
        if key not in {"id", "image_id", "category_id", "bbox", "iscrowd", "area"}
    }
    if task_type == "segmentation":
        seg = annotation_payload.get("segmentation")
        return InstanceSegmentationAnnotation(
            annotation_id=annotation_id, category_id=category_id,
            bbox_xywh=bbox_xywh, iscrowd=iscrowd, area=area,
            segmentation=seg if isinstance(seg, list) else None,
            metadata=extra_meta,
        )
    if task_type == "pose":
        kp = annotation_payload.get("keypoints")
        nk = int(annotation_payload.get("num_keypoints", 0) or 0)
        return PoseAnnotation(
            annotation_id=annotation_id, category_id=category_id,
            bbox_xywh=bbox_xywh, iscrowd=iscrowd, area=area,
            keypoints=kp if isinstance(kp, list) else None,
            num_keypoints=nk, metadata=extra_meta,
        )
    if task_type == "obb":
        polygon_xy = _extract_obb_polygon(annotation_payload)
        return ObbAnnotation(
            annotation_id=annotation_id,
            category_id=category_id,
            bbox_xywh=bbox_xywh,
            polygon_xy=polygon_xy,
            iscrowd=iscrowd,
            area=area,
            metadata=extra_meta,
        )
    return DetectionAnnotation(
        annotation_id=annotation_id, category_id=category_id,
        bbox_xywh=bbox_xywh, iscrowd=iscrowd, area=area,
        metadata=extra_meta,
    )

def _extract_obb_polygon(
    annotation_payload: dict[str, object],
) -> tuple[float, ...] | None:
    """从外部标注载荷中提取 OBB polygon。"""

    polygon_payload = (
        annotation_payload.get("poly")
        or annotation_payload.get("polygon")
    )
    if isinstance(polygon_payload, list) and len(polygon_payload) == 8:
        return tuple(float(value) for value in polygon_payload)
    segmentation_payload = annotation_payload.get("segmentation")
    if (
        isinstance(segmentation_payload, list)
        and len(segmentation_payload) == 1
        and isinstance(segmentation_payload[0], list)
        and len(segmentation_payload[0]) == 8
    ):
        return tuple(float(value) for value in segmentation_payload[0])
    return None

def _build_bbox_from_polygon(
    polygon_xy: tuple[float, ...],
) -> tuple[float, float, float, float]:
    """根据 polygon 计算轴对齐 bbox。"""

    xs = [float(polygon_xy[index]) for index in range(0, len(polygon_xy), 2)]
    ys = [float(polygon_xy[index]) for index in range(1, len(polygon_xy), 2)]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)
    return (min_x, min_y, max_x - min_x, max_y - min_y)

def _compute_polygon_area(
    polygon_xy: tuple[float, ...],
) -> float:
    """用鞋带公式计算 polygon 面积。"""

    points = [
        (float(polygon_xy[index]), float(polygon_xy[index + 1]))
        for index in range(0, len(polygon_xy), 2)
    ]
    area = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0
