"""数据集导入格式解析共用函数。"""

from __future__ import annotations

import math

from backend.service.application.errors import InvalidRequestError
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
        if key not in {
            "id", "image_id", "category_id", "bbox", "iscrowd", "area",
            "segmentation", "keypoints", "num_keypoints", "poly", "polygon",
        }
    }
    if task_type == "segmentation":
        seg = annotation_payload.get("segmentation")
        _validate_coco_segmentation(segmentation=seg, annotation_id=annotation_id)
        return InstanceSegmentationAnnotation(
            annotation_id=annotation_id, category_id=category_id,
            bbox_xywh=bbox_xywh, iscrowd=iscrowd, area=area,
            segmentation=seg if isinstance(seg, (list, dict)) else None,
            metadata=extra_meta,
        )
    if task_type == "pose":
        kp = annotation_payload.get("keypoints")
        if not isinstance(kp, list) or len(kp) == 0 or len(kp) % 3 != 0:
            raise InvalidRequestError(
                "COCO pose annotation.keypoints 必须是非空且长度为 3 的倍数的数组",
                details={"annotation_id": annotation_id},
            )
        try:
            keypoints = [float(value) for value in kp]
        except (TypeError, ValueError) as error:
            raise InvalidRequestError("COCO pose keypoints 必须是数字") from error
        if not all(math.isfinite(value) for value in keypoints):
            raise InvalidRequestError("COCO pose keypoints 必须是有限数字")
        visibility_values = keypoints[2::3]
        if any(value not in {0.0, 1.0, 2.0} for value in visibility_values):
            raise InvalidRequestError("COCO pose visibility 必须是 0、1 或 2")
        nk = int(annotation_payload.get("num_keypoints", 0) or 0)
        visible_count = sum(1 for value in visibility_values if value > 0)
        if nk != visible_count:
            raise InvalidRequestError(
                "COCO pose num_keypoints 与可见关键点数量不一致",
                details={"annotation_id": annotation_id},
            )
        return PoseAnnotation(
            annotation_id=annotation_id, category_id=category_id,
            bbox_xywh=bbox_xywh, iscrowd=iscrowd, area=area,
            keypoints=keypoints,
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


def _validate_coco_segmentation(
    *, segmentation: object, annotation_id: str,
) -> None:
    """校验 COCO polygon 或 RLE segmentation 的基本结构。"""

    if isinstance(segmentation, list):
        if not segmentation or any(
            not isinstance(polygon, list)
            or len(polygon) < 6
            or len(polygon) % 2 != 0
            for polygon in segmentation
        ):
            raise InvalidRequestError(
                "COCO segmentation polygon 必须包含至少一个三点多边形",
                details={"annotation_id": annotation_id},
            )
        try:
            polygon_values = [
                float(value) for polygon in segmentation for value in polygon
            ]
        except (TypeError, ValueError) as error:
            raise InvalidRequestError("COCO segmentation polygon 坐标必须是数字") from error
        if not all(math.isfinite(value) for value in polygon_values):
            raise InvalidRequestError("COCO segmentation polygon 坐标必须是有限数字")
        return
    if isinstance(segmentation, dict):
        size = segmentation.get("size")
        counts = segmentation.get("counts")
        if (
            not isinstance(size, list)
            or len(size) != 2
            or not all(isinstance(value, int) and value > 0 for value in size)
            or not isinstance(counts, (str, list))
            or (isinstance(counts, str) and not counts)
        ):
            raise InvalidRequestError(
                "COCO segmentation RLE 必须包含合法的 size 和 counts",
                details={"annotation_id": annotation_id},
            )
        if isinstance(counts, list) and (
            not counts
            or any(not isinstance(value, int) or value < 0 for value in counts)
            or sum(counts) != size[0] * size[1]
        ):
            raise InvalidRequestError(
                "COCO segmentation 未压缩 RLE counts 与 mask 尺寸不一致",
                details={"annotation_id": annotation_id},
            )
        return
    raise InvalidRequestError(
        "COCO segmentation annotation 缺少合法的 polygon 或 RLE",
        details={"annotation_id": annotation_id},
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


def _validate_bbox_within_image(
    bbox_xywh: tuple[float, float, float, float],
    *,
    image_width: int,
    image_height: int,
) -> None:
    """要求像素 xywh 框完整落在图片边界内。"""

    x, y, width, height = bbox_xywh
    epsilon = 1e-6
    if (
        x < -epsilon
        or y < -epsilon
        or x + width > float(image_width) + epsilon
        or y + height > float(image_height) + epsilon
    ):
        raise InvalidRequestError("标注 bbox 超出图片范围")


def _validate_simple_polygon(
    polygon_xy: tuple[float, ...],
    *,
    image_width: int,
    image_height: int,
    allow_edge_coordinates: bool,
) -> None:
    """校验 polygon 边界、退化边和自相交。"""

    if len(polygon_xy) < 6 or len(polygon_xy) % 2 != 0:
        raise InvalidRequestError("polygon 至少需要三个点且坐标必须成对")
    points = [
        (float(polygon_xy[index]), float(polygon_xy[index + 1]))
        for index in range(0, len(polygon_xy), 2)
    ]
    # 常见标注工具会显式重复首点闭合 polygon；闭合边本来已隐含，校验时去掉冗余点。
    if len(points) >= 4 and points[0] == points[-1]:
        points = points[:-1]
        polygon_xy = tuple(value for point in points for value in point)
    max_x = float(image_width) if allow_edge_coordinates else float(image_width) - 1e-9
    max_y = float(image_height) if allow_edge_coordinates else float(image_height) - 1e-9
    if any(x < 0 or y < 0 or x > max_x or y > max_y for x, y in points):
        raise InvalidRequestError("polygon 顶点超出图片范围")
    if any(points[index] == points[(index + 1) % len(points)] for index in range(len(points))):
        raise InvalidRequestError("polygon 相邻顶点不能重合")
    if _compute_polygon_area(polygon_xy) <= 0:
        raise InvalidRequestError("polygon 面积必须大于 0")
    edge_count = len(points)
    for first_index in range(edge_count):
        first_next = (first_index + 1) % edge_count
        for second_index in range(first_index + 1, edge_count):
            second_next = (second_index + 1) % edge_count
            if (
                first_index == second_index
                or first_next == second_index
                or second_next == first_index
            ):
                continue
            if _segments_intersect(
                points[first_index],
                points[first_next],
                points[second_index],
                points[second_next],
            ):
                raise InvalidRequestError("polygon 边界不得自相交")


def _segments_intersect(
    point_a: tuple[float, float],
    point_b: tuple[float, float],
    point_c: tuple[float, float],
    point_d: tuple[float, float],
) -> bool:
    """判断两条闭线段是否相交。"""

    def orientation(
        left: tuple[float, float],
        middle: tuple[float, float],
        right: tuple[float, float],
    ) -> float:
        return (middle[1] - left[1]) * (right[0] - middle[0]) - (
            middle[0] - left[0]
        ) * (right[1] - middle[1])

    values = (
        orientation(point_a, point_b, point_c),
        orientation(point_a, point_b, point_d),
        orientation(point_c, point_d, point_a),
        orientation(point_c, point_d, point_b),
    )
    epsilon = 1e-9
    return values[0] * values[1] < -epsilon and values[2] * values[3] < -epsilon
