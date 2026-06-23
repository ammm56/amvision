"""regions.v1 几何指标支撑函数。"""

from __future__ import annotations

import math

import cv2
import numpy as np

from backend.nodes.core_nodes.support.region.components import compute_component_areas
from backend.nodes.core_nodes.support.region.masks import (
    build_region_binary_mask,
    resolve_region_canvas_size,
)
from backend.nodes.core_nodes.support.region.metadata import (
    normalize_optional_int,
    normalize_optional_text,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def compute_regions_linearity_metrics(
    request: WorkflowNodeExecutionRequest,
    *,
    regions_payload: dict[str, object],
) -> dict[str, object]:
    """计算 regions.v1 的拟合直线偏差指标。"""

    image_width, image_height = resolve_region_canvas_size(
        request,
        regions_payload=regions_payload,
    )
    metrics_items: list[dict[str, object]] = []
    for region_item in regions_payload["items"]:
        region_mask = build_region_binary_mask(
            request,
            region_item=region_item,
            image_width=image_width,
            image_height=image_height,
        )
        metrics_items.append(
            _compute_region_linearity_item(
                region_item=region_item,
                region_mask=region_mask,
            )
        )
    return {
        "count": len(metrics_items),
        "image_width": image_width,
        "image_height": image_height,
        "items": metrics_items,
    }


def compute_regions_circularity_metrics(
    request: WorkflowNodeExecutionRequest,
    *,
    regions_payload: dict[str, object],
) -> dict[str, object]:
    """计算 regions.v1 的圆度、圆填充率和外接圆派生指标。"""

    image_width, image_height = resolve_region_canvas_size(
        request,
        regions_payload=regions_payload,
    )
    metrics_items: list[dict[str, object]] = []
    for region_item in regions_payload["items"]:
        region_mask = build_region_binary_mask(
            request,
            region_item=region_item,
            image_width=image_width,
            image_height=image_height,
        )
        metrics_items.append(
            _compute_region_circularity_item(
                region_item=region_item,
                region_mask=region_mask,
            )
        )
    return {
        "count": len(metrics_items),
        "image_width": image_width,
        "image_height": image_height,
        "items": metrics_items,
    }


def compute_region_bbox_metrics(region_item: dict[str, object]) -> dict[str, object]:
    """计算单个 region 的 bbox 派生指标。"""

    bbox_xyxy = region_item.get("bbox_xyxy")
    if not isinstance(bbox_xyxy, list) or len(bbox_xyxy) != 4:
        raise InvalidRequestError("regions-bbox-metrics 要求每个 region 包含长度为 4 的 bbox_xyxy")
    x1_value = float(bbox_xyxy[0])
    y1_value = float(bbox_xyxy[1])
    x2_value = float(bbox_xyxy[2])
    y2_value = float(bbox_xyxy[3])
    width_value = max(0.0, x2_value - x1_value)
    height_value = max(0.0, y2_value - y1_value)
    aspect_ratio = float(width_value / height_value) if height_value > 0 else None
    center_x = float((x1_value + x2_value) / 2.0)
    center_y = float((y1_value + y2_value) / 2.0)
    return {
        "region_id": str(region_item["region_id"]),
        "class_id": int(region_item.get("class_id", 0)),
        "class_name": str(region_item.get("class_name") or ""),
        "prompt_id": str(region_item.get("prompt_id") or "") or None,
        "track_id": str(region_item.get("track_id") or "") or None,
        "state": str(region_item.get("state") or "") or None,
        "x1": x1_value,
        "y1": y1_value,
        "x2": x2_value,
        "y2": y2_value,
        "width": width_value,
        "height": height_value,
        "aspect_ratio": aspect_ratio,
        "center_x": center_x,
        "center_y": center_y,
        "area": int(region_item["area"]),
        "score": float(region_item["score"]),
    }


def _compute_region_linearity_item(
    *,
    region_item: dict[str, object],
    region_mask: np.ndarray,
) -> dict[str, object]:
    """计算单个 region 的直线度指标。"""

    foreground_points = np.column_stack(np.nonzero(region_mask > 0))
    mask_area = int(np.count_nonzero(region_mask))
    base_item = _build_metric_base_item(region_item=region_item, mask_area=mask_area)
    if foreground_points.size <= 0:
        return {
            **base_item,
            "point_count": 0,
            "line_length_pixels": 0.0,
            "angle_deg": None,
            "mean_distance_pixels": None,
            "rms_distance_pixels": None,
            "max_distance_pixels": None,
            "mean_distance_ratio": None,
            "rms_distance_ratio": None,
            "max_distance_ratio": None,
        }
    point_cloud = np.column_stack(
        (foreground_points[:, 1].astype(np.float32), foreground_points[:, 0].astype(np.float32))
    )
    if point_cloud.shape[0] < 2:
        return {
            **base_item,
            "point_count": int(point_cloud.shape[0]),
            "line_length_pixels": 0.0,
            "angle_deg": None,
            "mean_distance_pixels": None,
            "rms_distance_pixels": None,
            "max_distance_pixels": None,
            "mean_distance_ratio": None,
            "rms_distance_ratio": None,
            "max_distance_ratio": None,
        }
    fit_result = cv2.fitLine(point_cloud, distType=cv2.DIST_L2, param=0, reps=0.01, aeps=0.01)
    direction_x = float(fit_result[0][0])
    direction_y = float(fit_result[1][0])
    origin_x = float(fit_result[2][0])
    origin_y = float(fit_result[3][0])
    relative_points = point_cloud - np.array([origin_x, origin_y], dtype=np.float32)
    direction_vector = np.array([direction_x, direction_y], dtype=np.float32)
    direction_norm = float(np.linalg.norm(direction_vector))
    if direction_norm <= 0:
        direction_norm = 1.0
    projection_values = relative_points @ direction_vector
    line_length_pixels = float(np.max(projection_values) - np.min(projection_values))
    signed_cross_values = relative_points[:, 0] * direction_y - relative_points[:, 1] * direction_x
    distance_values = np.abs(signed_cross_values) / direction_norm
    mean_distance_pixels = float(np.mean(distance_values))
    rms_distance_pixels = float(np.sqrt(np.mean(np.square(distance_values))))
    max_distance_pixels = float(np.max(distance_values))
    angle_deg = float(math.degrees(math.atan2(direction_y, direction_x)))
    angle_deg = float(angle_deg % 180.0)
    if angle_deg >= 90.0:
        angle_deg -= 180.0
    return {
        **base_item,
        "point_count": int(point_cloud.shape[0]),
        "line_length_pixels": round(line_length_pixels, 4),
        "angle_deg": round(angle_deg, 4),
        "mean_distance_pixels": round(mean_distance_pixels, 4),
        "rms_distance_pixels": round(rms_distance_pixels, 4),
        "max_distance_pixels": round(max_distance_pixels, 4),
        "mean_distance_ratio": round(float(mean_distance_pixels / line_length_pixels), 6)
        if line_length_pixels > 0
        else None,
        "rms_distance_ratio": round(float(rms_distance_pixels / line_length_pixels), 6)
        if line_length_pixels > 0
        else None,
        "max_distance_ratio": round(float(max_distance_pixels / line_length_pixels), 6)
        if line_length_pixels > 0
        else None,
    }


def _compute_region_circularity_item(
    *,
    region_item: dict[str, object],
    region_mask: np.ndarray,
) -> dict[str, object]:
    """计算单个 region 的圆度指标。"""

    binary_mask = (region_mask > 0).astype(np.uint8)
    mask_area = int(np.count_nonzero(binary_mask))
    component_count = len(compute_component_areas(binary_mask))
    base_item = _build_metric_base_item(region_item=region_item, mask_area=mask_area)
    if mask_area <= 0:
        return {
            **base_item,
            "component_count": component_count,
            "perimeter_pixels": 0.0,
            "circularity": None,
            "equivalent_diameter_pixels": None,
            "axis_bbox_aspect_ratio": None,
            "min_enclosing_circle_radius": None,
            "min_enclosing_circle_fill_ratio": None,
        }

    contours, _hierarchy = cv2.findContours(binary_mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    perimeter_pixels = float(
        sum(float(cv2.arcLength(contour, True)) for contour in contours if contour is not None and len(contour) >= 2)
    )
    foreground_points = np.column_stack(np.nonzero(binary_mask > 0))
    point_cloud = np.column_stack(
        (foreground_points[:, 1].astype(np.float32), foreground_points[:, 0].astype(np.float32))
    )
    x_span_pixels = int(np.max(foreground_points[:, 1]) - np.min(foreground_points[:, 1]) + 1)
    y_span_pixels = int(np.max(foreground_points[:, 0]) - np.min(foreground_points[:, 0]) + 1)
    axis_bbox_aspect_ratio = float(x_span_pixels / y_span_pixels) if y_span_pixels > 0 else None
    equivalent_diameter_pixels = float(math.sqrt((4.0 * mask_area) / math.pi))
    if point_cloud.shape[0] >= 2:
        (_center_x, _center_y), min_enclosing_circle_radius = cv2.minEnclosingCircle(point_cloud)
        min_enclosing_circle_radius = float(min_enclosing_circle_radius)
    else:
        min_enclosing_circle_radius = 0.0
    min_enclosing_circle_area = float(math.pi * min_enclosing_circle_radius * min_enclosing_circle_radius)
    min_enclosing_circle_fill_ratio = (
        float(mask_area / min_enclosing_circle_area) if min_enclosing_circle_area > 0 else None
    )
    circularity = None
    if perimeter_pixels > 0:
        circularity_value = float((4.0 * math.pi * mask_area) / (perimeter_pixels * perimeter_pixels))
        circularity = min(1.0, max(0.0, circularity_value))
    return {
        **base_item,
        "component_count": component_count,
        "perimeter_pixels": round(perimeter_pixels, 4),
        "circularity": round(circularity, 6) if circularity is not None else None,
        "equivalent_diameter_pixels": round(equivalent_diameter_pixels, 4),
        "axis_bbox_aspect_ratio": round(axis_bbox_aspect_ratio, 6)
        if axis_bbox_aspect_ratio is not None
        else None,
        "min_enclosing_circle_radius": round(min_enclosing_circle_radius, 4),
        "min_enclosing_circle_fill_ratio": round(min_enclosing_circle_fill_ratio, 6)
        if min_enclosing_circle_fill_ratio is not None
        else None,
    }


def _build_metric_base_item(
    *,
    region_item: dict[str, object],
    mask_area: int,
) -> dict[str, object]:
    """构造几何指标通用字段。"""

    return {
        "region_id": str(region_item["region_id"]),
        "class_id": normalize_optional_int(region_item.get("class_id")),
        "class_name": normalize_optional_text(region_item.get("class_name")),
        "prompt_id": normalize_optional_text(region_item.get("prompt_id")),
        "track_id": normalize_optional_text(region_item.get("track_id")),
        "state": normalize_optional_text(region_item.get("state")),
        "score": float(region_item["score"]),
        "declared_area": int(region_item["area"]),
        "mask_area": mask_area,
    }

