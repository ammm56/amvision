"""roi.v1 与 ROI/交集规则节点共享 helper。"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np

from backend.nodes.core_nodes._region_node_support import (
    require_regions_payload,
    resolve_region_source_image_size,
    select_best_region_item,
)
from backend.nodes.runtime_support import load_image_bytes_from_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def build_roi_payload(
    *,
    roi_id: str,
    display_name: str | None,
    roi_kind: str,
    bbox_xyxy: list[float],
    polygon_xy: list[list[float]],
    area: int,
    source_image: object | None = None,
) -> dict[str, object]:
    """构建规范化后的 roi.v1 payload。"""

    payload: dict[str, object] = {
        "roi_id": roi_id,
        "roi_kind": roi_kind,
        "bbox_xyxy": [float(value) for value in bbox_xyxy],
        "polygon_xy": [[float(point[0]), float(point[1])] for point in polygon_xy],
        "area": int(area),
    }
    if display_name:
        payload["display_name"] = display_name
    if isinstance(source_image, dict):
        payload["source_image"] = dict(source_image)
    return payload


def require_roi_payload(payload: object, *, node_id: str | None = None) -> dict[str, object]:
    """校验并规范化 roi.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError(
            "ROI 节点要求 roi.v1 payload 必须是对象",
            details={"node_id": node_id},
        )
    roi_id = payload.get("roi_id")
    roi_kind = payload.get("roi_kind")
    bbox_xyxy = payload.get("bbox_xyxy")
    polygon_xy = payload.get("polygon_xy")
    area = payload.get("area")
    if not isinstance(roi_id, str) or not roi_id.strip():
        raise InvalidRequestError("roi.v1 payload 缺少有效 roi_id", details={"node_id": node_id})
    if roi_kind not in {"bbox", "polygon"}:
        raise InvalidRequestError("roi.v1 payload 缺少有效 roi_kind", details={"node_id": node_id})
    normalized_bbox = normalize_bbox_xyxy(bbox_xyxy, field_name="bbox_xyxy", node_id=node_id)
    normalized_polygon = normalize_polygon_xy(polygon_xy, field_name="polygon_xy", node_id=node_id)
    if isinstance(area, bool) or not isinstance(area, int) or area < 0:
        raise InvalidRequestError("roi.v1 payload 缺少有效 area", details={"node_id": node_id})
    normalized_payload = build_roi_payload(
        roi_id=roi_id.strip(),
        display_name=str(payload.get("display_name")).strip() if isinstance(payload.get("display_name"), str) else None,
        roi_kind=str(roi_kind),
        bbox_xyxy=normalized_bbox,
        polygon_xy=normalized_polygon,
        area=int(area),
        source_image=payload.get("source_image"),
    )
    return normalized_payload


def normalize_bbox_xyxy(raw_value: object, *, field_name: str, node_id: str | None) -> list[float]:
    """规范化 bbox_xyxy。"""

    if not isinstance(raw_value, list) or len(raw_value) != 4:
        raise InvalidRequestError(f"{field_name} 必须是长度为 4 的数值数组", details={"node_id": node_id})
    normalized_values: list[float] = []
    for item_value in raw_value:
        if isinstance(item_value, bool) or not isinstance(item_value, (int, float)):
            raise InvalidRequestError(f"{field_name} 必须全部是数值", details={"node_id": node_id})
        normalized_values.append(float(item_value))
    x1_value, y1_value, x2_value, y2_value = normalized_values
    if x2_value < x1_value or y2_value < y1_value:
        raise InvalidRequestError(f"{field_name} 要求 x2>=x1 且 y2>=y1", details={"node_id": node_id})
    return normalized_values


def normalize_polygon_xy(raw_value: object, *, field_name: str, node_id: str | None) -> list[list[float]]:
    """规范化 polygon_xy。"""

    if not isinstance(raw_value, list) or len(raw_value) < 3:
        raise InvalidRequestError(f"{field_name} 必须是至少 3 个点的数组", details={"node_id": node_id})
    normalized_points: list[list[float]] = []
    for point_value in raw_value:
        if not isinstance(point_value, list) or len(point_value) != 2:
            raise InvalidRequestError(f"{field_name} 中的点必须是长度为 2 的数组", details={"node_id": node_id})
        x_value, y_value = point_value
        if isinstance(x_value, bool) or isinstance(y_value, bool) or not isinstance(x_value, (int, float)) or not isinstance(y_value, (int, float)):
            raise InvalidRequestError(f"{field_name} 中的点坐标必须是数值", details={"node_id": node_id})
        normalized_points.append([float(x_value), float(y_value)])
    return normalized_points


def polygon_bbox_xyxy(polygon_xy: list[list[float]]) -> list[float]:
    """根据 polygon 计算外接 bbox。"""

    x_values = [float(point[0]) for point in polygon_xy]
    y_values = [float(point[1]) for point in polygon_xy]
    return [min(x_values), min(y_values), max(x_values), max(y_values)]


def polygon_area(polygon_xy: list[list[float]]) -> int:
    """计算 polygon 面积。"""

    polygon_array = np.array(polygon_xy, dtype=np.float32)
    return max(0, int(round(abs(float(cv2.contourArea(polygon_array))))))


def bbox_area(bbox_xyxy: list[float]) -> int:
    """计算 bbox 面积。"""

    x1_value, y1_value, x2_value, y2_value = bbox_xyxy
    return max(0, int(round(max(0.0, x2_value - x1_value) * max(0.0, y2_value - y1_value))))


def bbox_to_polygon_xy(bbox_xyxy: list[float]) -> list[list[float]]:
    """把 bbox_xyxy 转成矩形 polygon。"""

    x1_value, y1_value, x2_value, y2_value = bbox_xyxy
    return [
        [x1_value, y1_value],
        [x2_value, y1_value],
        [x2_value, y2_value],
        [x1_value, y2_value],
    ]


def read_optional_text(raw_value: object, *, field_name: str, node_name: str) -> str | None:
    """读取可选字符串参数。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须是字符串")
    normalized_value = raw_value.strip()
    return normalized_value or None


def read_optional_bool(raw_value: object, *, field_name: str, node_name: str) -> bool | None:
    """读取可选布尔参数。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须是布尔值")
    return raw_value


def read_optional_number(raw_value: object, *, field_name: str, node_name: str) -> float | None:
    """读取可选数值参数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须是数值")
    return float(raw_value)


def read_polygon_parameter(raw_value: object, *, field_name: str, node_name: str) -> list[list[float]] | None:
    """读取可选 polygon 参数。"""

    if raw_value is None:
        return None
    return normalize_polygon_xy(raw_value, field_name=field_name, node_id=node_name)


def resolve_roi_canvas_size(
    request: WorkflowNodeExecutionRequest,
    *,
    regions_payload: dict[str, object],
    roi_payload: dict[str, object],
) -> tuple[int, int]:
    """解析 ROI 与 regions 计算所需的画布宽高。"""

    try:
        _source_payload, image_width, image_height = resolve_region_source_image_size(
            request,
            regions_payload=regions_payload,
            image_payload=None,
        )
        return image_width, image_height
    except InvalidRequestError:
        return derive_canvas_size_from_payloads(regions_payload=regions_payload, roi_payload=roi_payload)


def derive_canvas_size_from_payloads(
    *,
    regions_payload: dict[str, object],
    roi_payload: dict[str, object],
) -> tuple[int, int]:
    """从 bbox、polygon 和 mask payload 自行推导画布宽高。"""

    max_x = 1.0
    max_y = 1.0
    for region_item in regions_payload["items"]:
        bbox_xyxy = region_item.get("bbox_xyxy")
        if isinstance(bbox_xyxy, list) and len(bbox_xyxy) == 4:
            max_x = max(max_x, float(bbox_xyxy[2]))
            max_y = max(max_y, float(bbox_xyxy[3]))
        polygon_xy = region_item.get("polygon_xy")
        if isinstance(polygon_xy, list):
            for point_value in polygon_xy:
                if isinstance(point_value, list) and len(point_value) == 2:
                    max_x = max(max_x, float(point_value[0]))
                    max_y = max(max_y, float(point_value[1]))
        mask_payload = region_item.get("mask_image")
        if isinstance(mask_payload, dict):
            width_value = mask_payload.get("width")
            height_value = mask_payload.get("height")
            if isinstance(width_value, int) and width_value > 0:
                max_x = max(max_x, float(width_value))
            if isinstance(height_value, int) and height_value > 0:
                max_y = max(max_y, float(height_value))
    bbox_xyxy = roi_payload["bbox_xyxy"]
    max_x = max(max_x, float(bbox_xyxy[2]))
    max_y = max(max_y, float(bbox_xyxy[3]))
    for point_value in roi_payload["polygon_xy"]:
        max_x = max(max_x, float(point_value[0]))
        max_y = max(max_y, float(point_value[1]))
    return max(1, int(math.ceil(max_x))), max(1, int(math.ceil(max_y)))


def build_roi_mask(
    *,
    roi_payload: dict[str, object],
    image_width: int,
    image_height: int,
) -> np.ndarray:
    """把 roi.v1 转为二值 mask。"""

    if roi_payload["roi_kind"] == "bbox":
        return build_bbox_mask(
            bbox_xyxy=roi_payload["bbox_xyxy"],
            image_width=image_width,
            image_height=image_height,
        )
    return build_polygon_mask(
        polygon_xy=roi_payload["polygon_xy"],
        image_width=image_width,
        image_height=image_height,
    )


def build_region_mask(
    request: WorkflowNodeExecutionRequest,
    *,
    region_item: dict[str, object],
    image_width: int,
    image_height: int,
) -> np.ndarray:
    """把单个 region item 转为二值 mask。"""

    mask_payload = region_item.get("mask_image")
    if isinstance(mask_payload, dict):
        normalized_payload, image_bytes = load_image_bytes_from_payload(
            request,
            image_payload=mask_payload,
        )
        image_matrix = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if image_matrix is None:
            raise InvalidRequestError("region 的 mask_image 无法解码为灰度图")
        if image_matrix.shape[1] != image_width or image_matrix.shape[0] != image_height:
            image_matrix = cv2.resize(
                image_matrix,
                (image_width, image_height),
                interpolation=cv2.INTER_NEAREST,
            )
        threshold_matrix = (image_matrix > 0).astype(np.uint8)
        _ = normalized_payload
        return threshold_matrix
    polygon_xy = region_item.get("polygon_xy")
    if isinstance(polygon_xy, list) and len(polygon_xy) >= 3:
        return build_polygon_mask(
            polygon_xy=normalize_polygon_xy(polygon_xy, field_name="polygon_xy", node_id=None),
            image_width=image_width,
            image_height=image_height,
        )
    return build_bbox_mask(
        bbox_xyxy=normalize_bbox_xyxy(region_item.get("bbox_xyxy"), field_name="bbox_xyxy", node_id=None),
        image_width=image_width,
        image_height=image_height,
    )


def build_bbox_mask(*, bbox_xyxy: list[float], image_width: int, image_height: int) -> np.ndarray:
    """把 bbox 转为二值 mask。"""

    x1_value, y1_value, x2_value, y2_value = bbox_xyxy
    x1_index = max(0, min(image_width, int(math.floor(x1_value))))
    y1_index = max(0, min(image_height, int(math.floor(y1_value))))
    x2_index = max(0, min(image_width, int(math.ceil(x2_value))))
    y2_index = max(0, min(image_height, int(math.ceil(y2_value))))
    mask_matrix = np.zeros((image_height, image_width), dtype=np.uint8)
    if x2_index > x1_index and y2_index > y1_index:
        mask_matrix[y1_index:y2_index, x1_index:x2_index] = 1
    return mask_matrix


def build_polygon_mask(*, polygon_xy: list[list[float]], image_width: int, image_height: int) -> np.ndarray:
    """把 polygon 转为二值 mask。"""

    polygon_array = np.array(
        [[[int(round(point[0])), int(round(point[1]))] for point in polygon_xy]],
        dtype=np.int32,
    )
    mask_matrix = np.zeros((image_height, image_width), dtype=np.uint8)
    cv2.fillPoly(mask_matrix, polygon_array, 1)
    return mask_matrix


def compute_regions_intersection_metrics(
    request: WorkflowNodeExecutionRequest,
    *,
    regions_payload: dict[str, object],
    roi_payload: dict[str, object],
) -> dict[str, object]:
    """计算 regions 与 ROI 的交集、覆盖率和 IoU 指标。"""

    image_width, image_height = resolve_roi_canvas_size(
        request,
        regions_payload=regions_payload,
        roi_payload=roi_payload,
    )
    roi_mask = build_roi_mask(
        roi_payload=roi_payload,
        image_width=image_width,
        image_height=image_height,
    )
    roi_area = int(np.count_nonzero(roi_mask))
    union_region_mask = np.zeros_like(roi_mask)
    metrics_items: list[dict[str, Any]] = []
    best_iou = 0.0
    best_inside_ratio = 0.0
    for region_item in regions_payload["items"]:
        region_mask = build_region_mask(
            request,
            region_item=region_item,
            image_width=image_width,
            image_height=image_height,
        )
        union_region_mask = np.maximum(union_region_mask, region_mask)
        region_area = max(0, int(region_item["area"]))
        intersection_area = int(np.count_nonzero(np.logical_and(region_mask > 0, roi_mask > 0)))
        mask_region_area = int(np.count_nonzero(region_mask))
        effective_region_area = max(region_area, mask_region_area)
        union_area = effective_region_area + roi_area - intersection_area
        inside_ratio = float(intersection_area / effective_region_area) if effective_region_area > 0 else 0.0
        roi_coverage_ratio = float(intersection_area / roi_area) if roi_area > 0 else 0.0
        iou_ratio = float(intersection_area / union_area) if union_area > 0 else 0.0
        best_iou = max(best_iou, iou_ratio)
        best_inside_ratio = max(best_inside_ratio, inside_ratio)
        metrics_items.append(
            {
                "region_id": region_item["region_id"],
                "class_id": region_item.get("class_id"),
                "class_name": region_item.get("class_name"),
                "prompt_id": region_item.get("prompt_id"),
                "track_id": region_item.get("track_id"),
                "state": region_item.get("state"),
                "region_area": effective_region_area,
                "intersection_area": intersection_area,
                "roi_coverage_ratio": roi_coverage_ratio,
                "inside_ratio": inside_ratio,
                "iou": iou_ratio,
            }
        )
    union_region_area = int(np.count_nonzero(union_region_mask))
    union_intersection_area = int(np.count_nonzero(np.logical_and(union_region_mask > 0, roi_mask > 0)))
    return {
        "roi_id": roi_payload["roi_id"],
        "roi_kind": roi_payload["roi_kind"],
        "roi_area": roi_area,
        "region_count": len(regions_payload["items"]),
        "image_width": image_width,
        "image_height": image_height,
        "union_region_area": union_region_area,
        "union_intersection_area": union_intersection_area,
        "roi_coverage_ratio": float(union_intersection_area / roi_area) if roi_area > 0 else 0.0,
        "region_inside_ratio": float(union_intersection_area / union_region_area) if union_region_area > 0 else 0.0,
        "best_iou": best_iou,
        "best_inside_ratio": best_inside_ratio,
        "items": metrics_items,
    }


__all__ = [
    "bbox_area",
    "bbox_to_polygon_xy",
    "build_roi_mask",
    "build_roi_payload",
    "compute_regions_intersection_metrics",
    "normalize_bbox_xyxy",
    "normalize_polygon_xy",
    "polygon_area",
    "polygon_bbox_xyxy",
    "read_optional_bool",
    "read_optional_number",
    "read_optional_text",
    "read_polygon_parameter",
    "require_regions_payload",
    "require_roi_payload",
    "select_best_region_item",
]
