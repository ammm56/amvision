"""regions.v1 core 节点共享 helper。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
import io
import math
from statistics import median

import cv2
import numpy as np
from PIL import Image

from backend.nodes.core_nodes._video_track_node_support import require_regions_payload
from backend.nodes.runtime_support import load_image_bytes_from_payload, require_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


def build_regions_payload(
    *,
    source_image: object,
    selected_frame_index: int | None,
    items: Iterable[dict[str, object]],
) -> dict[str, object]:
    """构建规范化后的 regions.v1 payload。"""

    normalized_items = [dict(item) for item in items]
    payload: dict[str, object] = {
        "count": len(normalized_items),
        "items": normalized_items,
    }
    if isinstance(source_image, dict):
        payload["source_image"] = dict(source_image)
    if selected_frame_index is not None:
        payload["selected_frame_index"] = int(selected_frame_index)
    return payload


def filter_region_items(
    items: Iterable[dict[str, object]],
    *,
    min_score: float | None,
    max_score: float | None,
    min_area: int | None,
    max_area: int | None,
    class_ids: set[int] | None,
    class_names: set[str] | None,
    prompt_ids: set[str] | None,
    track_ids: set[str] | None,
    states: set[str] | None,
) -> list[dict[str, object]]:
    """按给定规则过滤 region item 列表。"""

    filtered_items: list[dict[str, object]] = []
    for item in items:
        score = float(item["score"])
        if min_score is not None and score < min_score:
            continue
        if max_score is not None and score > max_score:
            continue
        area = int(item["area"])
        if min_area is not None and area < min_area:
            continue
        if max_area is not None and area > max_area:
            continue
        class_id = item.get("class_id")
        if class_ids is not None and class_id not in class_ids:
            continue
        class_name = item.get("class_name")
        if class_names is not None and class_name not in class_names:
            continue
        prompt_id = item.get("prompt_id")
        if prompt_ids is not None and prompt_id not in prompt_ids:
            continue
        track_id = item.get("track_id")
        if track_ids is not None and track_id not in track_ids:
            continue
        state = item.get("state")
        if states is not None and state not in states:
            continue
        filtered_items.append(dict(item))
    return filtered_items


def select_best_region_item(
    items: Iterable[dict[str, object]],
    *,
    strategy: str,
) -> dict[str, object] | None:
    """按策略挑选最优 region。"""

    normalized_items = list(items)
    if not normalized_items:
        return None
    if strategy == "first":
        return dict(normalized_items[0])
    if strategy == "largest-area":
        return dict(max(normalized_items, key=lambda item: (int(item["area"]), float(item["score"]))))
    if strategy == "highest-score":
        return dict(max(normalized_items, key=lambda item: (float(item["score"]), int(item["area"]))))
    raise InvalidRequestError(
        "不支持的 regions-select-best strategy",
        details={"strategy": strategy},
    )


def derive_region_canvas_size(*, regions_payload: dict[str, object]) -> tuple[int, int]:
    """从 regions.v1 自身推导连通域分析所需的画布宽高。"""

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
    return max(1, int(math.ceil(max_x))), max(1, int(math.ceil(max_y)))


def resolve_region_canvas_size(
    request: WorkflowNodeExecutionRequest,
    *,
    regions_payload: dict[str, object],
) -> tuple[int, int]:
    """解析 region 二值化分析所需的画布宽高。"""

    try:
        _resolved_payload, image_width, image_height = resolve_region_source_image_size(
            request,
            regions_payload=regions_payload,
            image_payload=None,
        )
        return image_width, image_height
    except InvalidRequestError:
        return derive_region_canvas_size(regions_payload=regions_payload)


def build_bbox_mask(*, bbox_xyxy: list[float], image_width: int, image_height: int) -> np.ndarray:
    """把 bbox_xyxy 栅格化为二值 mask。"""

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
    """把 polygon_xy 栅格化为二值 mask。"""

    polygon_array = np.array(
        [[[int(round(point[0])), int(round(point[1]))] for point in polygon_xy]],
        dtype=np.int32,
    )
    mask_matrix = np.zeros((image_height, image_width), dtype=np.uint8)
    cv2.fillPoly(mask_matrix, polygon_array, 1)
    return mask_matrix


def build_region_binary_mask(
    request: WorkflowNodeExecutionRequest,
    *,
    region_item: dict[str, object],
    image_width: int,
    image_height: int,
) -> np.ndarray:
    """把单个 region item 解析成二值 mask。"""

    mask_payload = region_item.get("mask_image")
    if isinstance(mask_payload, dict):
        _normalized_payload, image_bytes = load_image_bytes_from_payload(
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
        return (image_matrix > 0).astype(np.uint8)
    polygon_xy = region_item.get("polygon_xy")
    if isinstance(polygon_xy, list) and len(polygon_xy) >= 3:
        return build_polygon_mask(
            polygon_xy=_normalize_polygon_xy(polygon_xy),
            image_width=image_width,
            image_height=image_height,
        )
    return build_bbox_mask(
        bbox_xyxy=_normalize_bbox_xyxy(region_item.get("bbox_xyxy")),
        image_width=image_width,
        image_height=image_height,
    )


def compute_regions_integrity_metrics(
    request: WorkflowNodeExecutionRequest,
    *,
    regions_payload: dict[str, object],
) -> dict[str, object]:
    """计算 regions.v1 的连通域、主体占比和空洞原子指标。"""

    image_width, image_height = resolve_region_canvas_size(request, regions_payload=regions_payload)
    metrics_items: list[dict[str, object]] = []
    for region_item in regions_payload["items"]:
        region_mask = build_region_binary_mask(
            request,
            region_item=region_item,
            image_width=image_width,
            image_height=image_height,
        )
        mask_area = int(np.count_nonzero(region_mask))
        component_areas = _compute_component_areas(region_mask)
        hole_areas = _compute_hole_areas(region_mask)
        largest_component_area = component_areas[0] if component_areas else 0
        largest_component_ratio = float(largest_component_area / mask_area) if mask_area > 0 else 0.0
        metrics_items.append(
            {
                "region_id": str(region_item["region_id"]),
                "class_id": _normalize_optional_int(region_item.get("class_id")),
                "class_name": _normalize_optional_text(region_item.get("class_name")),
                "prompt_id": _normalize_optional_text(region_item.get("prompt_id")),
                "track_id": _normalize_optional_text(region_item.get("track_id")),
                "state": _normalize_optional_text(region_item.get("state")),
                "score": float(region_item["score"]),
                "declared_area": int(region_item["area"]),
                "mask_area": mask_area,
                "component_count": len(component_areas),
                "component_areas": component_areas,
                "largest_component_area": largest_component_area,
                "largest_component_ratio": largest_component_ratio,
                "hole_count": len(hole_areas),
                "hole_areas": hole_areas,
            }
        )
    return {
        "count": len(metrics_items),
        "image_width": image_width,
        "image_height": image_height,
        "items": metrics_items,
    }


def compute_regions_span_metrics(
    request: WorkflowNodeExecutionRequest,
    *,
    regions_payload: dict[str, object],
) -> dict[str, object]:
    """计算 regions.v1 的跨度、主方向和细长度等量测指标。"""

    image_width, image_height = resolve_region_canvas_size(request, regions_payload=regions_payload)
    metrics_items: list[dict[str, object]] = []
    for region_item in regions_payload["items"]:
        region_mask = build_region_binary_mask(
            request,
            region_item=region_item,
            image_width=image_width,
            image_height=image_height,
        )
        mask_area = int(np.count_nonzero(region_mask))
        span_metrics = _compute_span_metrics(region_mask)
        metrics_items.append(
            {
                "region_id": str(region_item["region_id"]),
                "class_id": _normalize_optional_int(region_item.get("class_id")),
                "class_name": _normalize_optional_text(region_item.get("class_name")),
                "prompt_id": _normalize_optional_text(region_item.get("prompt_id")),
                "track_id": _normalize_optional_text(region_item.get("track_id")),
                "state": _normalize_optional_text(region_item.get("state")),
                "score": float(region_item["score"]),
                "declared_area": int(region_item["area"]),
                "mask_area": mask_area,
                **span_metrics,
            }
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


def build_score_summary(items: Iterable[dict[str, object]]) -> dict[str, object]:
    """统计 region score 摘要。"""

    scores = [float(item["score"]) for item in items]
    if not scores:
        return {
            "count": 0,
            "min_score": None,
            "max_score": None,
            "avg_score": None,
            "median_score": None,
        }
    return {
        "count": len(scores),
        "min_score": min(scores),
        "max_score": max(scores),
        "avg_score": sum(scores) / len(scores),
        "median_score": float(median(scores)),
    }


def build_class_distribution(items: Iterable[dict[str, object]]) -> dict[str, int]:
    """统计类别名称分布。"""

    counter = Counter(str(item.get("class_name") or "") for item in items)
    return dict(sorted(counter.items(), key=lambda pair: pair[0]))


def resolve_region_source_image_payload(
    request: WorkflowNodeExecutionRequest,
    *,
    regions_payload: dict[str, object],
    image_payload: object | None,
) -> dict[str, object]:
    """解析 regions 相关图像 payload。"""

    if image_payload is not None:
        return require_image_payload(image_payload)
    source_image = regions_payload.get("source_image")
    if isinstance(source_image, dict):
        return require_image_payload(source_image)
    raise InvalidRequestError(
        "当前节点要求提供 image 输入，或 regions.v1 内必须包含 source_image",
        details={"node_id": request.node_id},
    )


def resolve_region_source_image_size(
    request: WorkflowNodeExecutionRequest,
    *,
    regions_payload: dict[str, object],
    image_payload: object | None,
) -> tuple[dict[str, object], int, int]:
    """解析区域来源图像的宽高。"""

    resolved_payload = resolve_region_source_image_payload(
        request,
        regions_payload=regions_payload,
        image_payload=image_payload,
    )
    width_value = resolved_payload.get("width")
    height_value = resolved_payload.get("height")
    if isinstance(width_value, int) and width_value > 0 and isinstance(height_value, int) and height_value > 0:
        return resolved_payload, width_value, height_value
    _normalized_payload, image_bytes = load_image_bytes_from_payload(
        request,
        image_payload=resolved_payload,
    )
    with Image.open(io.BytesIO(image_bytes)) as image_obj:
        width_value, height_value = image_obj.size
    return resolved_payload, int(width_value), int(height_value)


def read_optional_number(raw_value: object, *, field_name: str, node_name: str) -> float | None:
    """读取可选数值参数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须是数值")
    return float(raw_value)


def read_optional_int(raw_value: object, *, field_name: str, node_name: str) -> int | None:
    """读取可选整数参数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须是整数")
    return int(raw_value)


def read_optional_int_set(raw_value: object, *, field_name: str, node_name: str) -> set[int] | None:
    """读取可选整数集合参数。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, list):
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须是整数数组")
    normalized_values: set[int] = set()
    for item_index, item_value in enumerate(raw_value, start=1):
        if isinstance(item_value, bool) or not isinstance(item_value, int):
            raise InvalidRequestError(
                f"{node_name} 节点的 {field_name} 必须全部是整数",
                details={"field_name": field_name, "item_index": item_index},
            )
        normalized_values.add(int(item_value))
    return normalized_values


def read_optional_str_set(raw_value: object, *, field_name: str, node_name: str) -> set[str] | None:
    """读取可选字符串集合参数。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, list):
        raise InvalidRequestError(f"{node_name} 节点的 {field_name} 必须是字符串数组")
    normalized_values: set[str] = set()
    for item_index, item_value in enumerate(raw_value, start=1):
        if not isinstance(item_value, str):
            raise InvalidRequestError(
                f"{node_name} 节点的 {field_name} 必须全部是字符串",
                details={"field_name": field_name, "item_index": item_index},
            )
        normalized_values.add(item_value)
    return normalized_values


def _normalize_bbox_xyxy(raw_value: object) -> list[float]:
    """规范化 region 内的 bbox_xyxy。"""

    if not isinstance(raw_value, list) or len(raw_value) != 4:
        raise InvalidRequestError("region 的 bbox_xyxy 必须是长度为 4 的数值数组")
    normalized_values: list[float] = []
    for item_value in raw_value:
        if isinstance(item_value, bool) or not isinstance(item_value, (int, float)):
            raise InvalidRequestError("region 的 bbox_xyxy 必须全部是数值")
        normalized_values.append(float(item_value))
    x1_value, y1_value, x2_value, y2_value = normalized_values
    if x2_value < x1_value or y2_value < y1_value:
        raise InvalidRequestError("region 的 bbox_xyxy 要求 x2>=x1 且 y2>=y1")
    return normalized_values


def _normalize_polygon_xy(raw_value: object) -> list[list[float]]:
    """规范化 region 内的 polygon_xy。"""

    if not isinstance(raw_value, list) or len(raw_value) < 3:
        raise InvalidRequestError("region 的 polygon_xy 必须是至少 3 个点的数组")
    normalized_points: list[list[float]] = []
    for point_value in raw_value:
        if not isinstance(point_value, list) or len(point_value) != 2:
            raise InvalidRequestError("region 的 polygon_xy 中的点必须是长度为 2 的数组")
        x_value, y_value = point_value
        if isinstance(x_value, bool) or isinstance(y_value, bool) or not isinstance(x_value, (int, float)) or not isinstance(y_value, (int, float)):
            raise InvalidRequestError("region 的 polygon_xy 中的点坐标必须是数值")
        normalized_points.append([float(x_value), float(y_value)])
    return normalized_points


def _compute_component_areas(mask_matrix: np.ndarray) -> list[int]:
    """计算前景连通域面积列表，按面积从大到小排序。"""

    binary_mask = (mask_matrix > 0).astype(np.uint8)
    if int(np.count_nonzero(binary_mask)) <= 0:
        return []
    label_count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(binary_mask, connectivity=8)
    component_areas = [
        int(stats[label_index, cv2.CC_STAT_AREA])
        for label_index in range(1, label_count)
        if int(stats[label_index, cv2.CC_STAT_AREA]) > 0
    ]
    component_areas.sort(reverse=True)
    return component_areas


def _compute_hole_count(mask_matrix: np.ndarray) -> int:
    """计算二值前景中的空洞数量。"""

    return len(_compute_hole_areas(mask_matrix))


def _compute_hole_areas(mask_matrix: np.ndarray) -> list[int]:
    """计算空洞面积列表，按面积从大到小排序。"""

    binary_mask = (mask_matrix > 0).astype(np.uint8)
    padded_mask = np.pad(binary_mask, pad_width=1, mode="constant", constant_values=0)
    background_mask = (padded_mask == 0).astype(np.uint8)
    label_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(background_mask, connectivity=8)
    hole_areas = [
        int(stats[label_index, cv2.CC_STAT_AREA])
        for label_index in range(1, label_count)
        if int(stats[label_index, cv2.CC_STAT_AREA]) > 0 and not _touches_outer_border(labels == label_index)
    ]
    hole_areas.sort(reverse=True)
    return hole_areas


def _touches_outer_border(label_mask: np.ndarray) -> bool:
    """判断一个背景连通域是否接触外边界。"""

    return bool(
        np.any(label_mask[0, :])
        or np.any(label_mask[-1, :])
        or np.any(label_mask[:, 0])
        or np.any(label_mask[:, -1])
    )


def _compute_span_metrics(mask_matrix: np.ndarray) -> dict[str, object]:
    """计算单个二值区域的跨度、方向和细长度。"""

    foreground_points = np.column_stack(np.nonzero(mask_matrix > 0))
    if foreground_points.size <= 0:
        return {
            "x_span_pixels": 0,
            "y_span_pixels": 0,
            "long_span_pixels": 0.0,
            "short_span_pixels": 0.0,
            "elongation_ratio": None,
            "orientation_deg": None,
            "axis_aligned_fill_ratio": None,
        }
    y_values = foreground_points[:, 0]
    x_values = foreground_points[:, 1]
    x_span_pixels = int(np.max(x_values) - np.min(x_values) + 1)
    y_span_pixels = int(np.max(y_values) - np.min(y_values) + 1)
    if foreground_points.shape[0] == 1:
        long_span_pixels = 1.0
        short_span_pixels = 1.0
        orientation_deg = 0.0
    else:
        point_cloud = np.column_stack((x_values.astype(np.float32), y_values.astype(np.float32)))
        _center, size, angle = cv2.minAreaRect(point_cloud)
        width_value = max(1.0, float(size[0]))
        height_value = max(1.0, float(size[1]))
        if width_value >= height_value:
            long_span_pixels = width_value
            short_span_pixels = height_value
            orientation_deg = float(angle)
        else:
            long_span_pixels = height_value
            short_span_pixels = width_value
            orientation_deg = float(angle + 90.0)
        orientation_deg = float(orientation_deg % 180.0)
        if orientation_deg >= 90.0:
            orientation_deg -= 180.0
    axis_aligned_area = max(1, x_span_pixels * y_span_pixels)
    elongation_ratio = float(long_span_pixels / short_span_pixels) if short_span_pixels > 0 else None
    return {
        "x_span_pixels": x_span_pixels,
        "y_span_pixels": y_span_pixels,
        "long_span_pixels": float(long_span_pixels),
        "short_span_pixels": float(short_span_pixels),
        "elongation_ratio": elongation_ratio,
        "orientation_deg": orientation_deg,
        "axis_aligned_fill_ratio": float(int(foreground_points.shape[0]) / axis_aligned_area),
    }


def _normalize_optional_int(raw_value: object) -> int | None:
    """规范化可选整数值。"""

    if isinstance(raw_value, bool) or raw_value is None:
        return None
    if not isinstance(raw_value, int):
        return None
    return int(raw_value)


def _normalize_optional_text(raw_value: object) -> str | None:
    """规范化可选文本值。"""

    if not isinstance(raw_value, str):
        return None
    normalized_value = raw_value.strip()
    return normalized_value or None


__all__ = [
    "build_bbox_mask",
    "build_class_distribution",
    "build_polygon_mask",
    "build_region_binary_mask",
    "build_regions_payload",
    "build_score_summary",
    "compute_regions_integrity_metrics",
    "compute_regions_span_metrics",
    "compute_region_bbox_metrics",
    "derive_region_canvas_size",
    "filter_region_items",
    "read_optional_int",
    "read_optional_int_set",
    "read_optional_number",
    "read_optional_str_set",
    "require_regions_payload",
    "resolve_region_canvas_size",
    "resolve_region_source_image_payload",
    "resolve_region_source_image_size",
    "select_best_region_item",
]
