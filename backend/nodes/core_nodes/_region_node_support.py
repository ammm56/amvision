"""regions.v1 core 节点共享 helper。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
import io
from statistics import median

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


__all__ = [
    "build_class_distribution",
    "build_regions_payload",
    "build_score_summary",
    "compute_region_bbox_metrics",
    "filter_region_items",
    "read_optional_int",
    "read_optional_int_set",
    "read_optional_number",
    "read_optional_str_set",
    "require_regions_payload",
    "resolve_region_source_image_payload",
    "resolve_region_source_image_size",
    "select_best_region_item",
]
