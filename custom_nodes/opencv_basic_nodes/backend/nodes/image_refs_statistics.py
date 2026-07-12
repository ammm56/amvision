"""Image refs 批量统计节点。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.parameter_utils import is_empty_parameter
from backend.nodes.runtime_support import load_image_matrix_from_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.payloads import require_image_refs_payload
from custom_nodes._opencv_shared.backend.runtime.validators import require_positive_int, require_uint8_int


NODE_TYPE_ID = "custom.opencv.image-refs-statistics"

SUPPORTED_DECISION_METRICS = {
    "none",
    "mean_gray",
    "std_gray",
    "dark_ratio",
    "bright_ratio",
    "edge_density",
}


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """统计 image-refs.v1 中每张图片的 OpenCV 灰度指标，并按可选阈值判定。"""

    cv2_module, np_module = require_opencv_imports()
    image_refs_payload = require_image_refs_payload(request.input_values.get("images"))
    max_items = _read_optional_positive_int(request.parameters.get("max_items"), field_name="max_items")
    dark_threshold = _read_uint8_with_default(
        request.parameters.get("dark_threshold"),
        field_name="dark_threshold",
        default_value=64,
    )
    bright_threshold = _read_uint8_with_default(
        request.parameters.get("bright_threshold"),
        field_name="bright_threshold",
        default_value=192,
    )
    canny_low_threshold = _read_uint8_with_default(
        request.parameters.get("canny_low_threshold"),
        field_name="canny_low_threshold",
        default_value=50,
    )
    canny_high_threshold = _read_uint8_with_default(
        request.parameters.get("canny_high_threshold"),
        field_name="canny_high_threshold",
        default_value=150,
    )
    if canny_high_threshold < canny_low_threshold:
        raise InvalidRequestError("image-refs-statistics 节点的 canny_high_threshold 必须大于等于 canny_low_threshold")
    decision_metric = _read_decision_metric(request.parameters.get("decision_metric"))
    empty_min = _read_optional_float(request.parameters.get("empty_min"), field_name="empty_min")
    empty_max = _read_optional_float(request.parameters.get("empty_max"), field_name="empty_max")
    if empty_min is not None and empty_max is not None and empty_max < empty_min:
        raise InvalidRequestError("image-refs-statistics 节点的 empty_max 必须大于等于 empty_min")

    stats_items: list[dict[str, object]] = []
    source_items = image_refs_payload["items"]
    if max_items is not None:
        source_items = source_items[:max_items]
    for item_index, image_item in enumerate(source_items, start=1):
        image_payload, image_matrix = load_image_matrix_from_payload(
            request,
            image_payload=image_item,
            cv2_module=cv2_module,
            np_module=np_module,
            copy_raw=False,
        )
        stats_item = _build_stats_item(
            cv2_module=cv2_module,
            np_module=np_module,
            image_payload=image_payload,
            image_matrix=image_matrix,
            item_index=item_index,
            dark_threshold=dark_threshold,
            bright_threshold=bright_threshold,
            canny_low_threshold=canny_low_threshold,
            canny_high_threshold=canny_high_threshold,
            decision_metric=decision_metric,
            empty_min=empty_min,
            empty_max=empty_max,
        )
        stats_items.append(stats_item)

    decided_items = [item for item in stats_items if item.get("is_empty") is not None]
    empty_count = sum(1 for item in decided_items if item.get("is_empty") is True)
    non_empty_count = sum(1 for item in decided_items if item.get("is_empty") is False)
    payload = {
        "format_id": "amvision.image-refs-statistics.v1",
        "count": len(stats_items),
        "total_count": int(image_refs_payload.get("count", len(image_refs_payload["items"]))),
        "decision_metric": decision_metric,
        "decision_enabled": decision_metric != "none" and (empty_min is not None or empty_max is not None),
        "empty_min": empty_min,
        "empty_max": empty_max,
        "empty_count": empty_count,
        "non_empty_count": non_empty_count,
        "items": stats_items,
    }
    return {
        "summary": build_value_payload(payload),
        "body": {
            "type": "image-refs-statistics",
            **payload,
        },
    }


def _build_stats_item(
    *,
    cv2_module: object,
    np_module: object,
    image_payload: dict[str, object],
    image_matrix: object,
    item_index: int,
    dark_threshold: int,
    bright_threshold: int,
    canny_low_threshold: int,
    canny_high_threshold: int,
    decision_metric: str,
    empty_min: float | None,
    empty_max: float | None,
) -> dict[str, object]:
    """计算单张图片的灰度、亮暗和边缘统计。"""

    if len(image_matrix.shape) == 2:
        gray_image = image_matrix
    else:
        gray_image = cv2_module.cvtColor(image_matrix, cv2_module.COLOR_BGR2GRAY)
    pixel_count = int(gray_image.size)
    if pixel_count <= 0:
        raise InvalidRequestError("image-refs-statistics 节点读取到空图片")
    edge_image = cv2_module.Canny(gray_image, canny_low_threshold, canny_high_threshold)
    mean_gray = float(np_module.mean(gray_image))
    std_gray = float(np_module.std(gray_image))
    min_gray = int(np_module.min(gray_image))
    max_gray = int(np_module.max(gray_image))
    dark_ratio = float(np_module.count_nonzero(gray_image <= dark_threshold) / pixel_count)
    bright_ratio = float(np_module.count_nonzero(gray_image >= bright_threshold) / pixel_count)
    edge_density = float(np_module.count_nonzero(edge_image) / pixel_count)
    metric_values = {
        "mean_gray": mean_gray,
        "std_gray": std_gray,
        "dark_ratio": dark_ratio,
        "bright_ratio": bright_ratio,
        "edge_density": edge_density,
    }
    decision_value = metric_values.get(decision_metric)
    is_empty = _evaluate_empty_decision(decision_value, empty_min=empty_min, empty_max=empty_max)
    result = {
        "index": item_index,
        "width": int(image_payload.get("width") or image_matrix.shape[1]),
        "height": int(image_payload.get("height") or image_matrix.shape[0]),
        "pixel_count": pixel_count,
        "mean_gray": round(mean_gray, 6),
        "std_gray": round(std_gray, 6),
        "min_gray": min_gray,
        "max_gray": max_gray,
        "dark_ratio": round(dark_ratio, 8),
        "bright_ratio": round(bright_ratio, 8),
        "edge_density": round(edge_density, 8),
        "decision_value": round(float(decision_value), 8) if decision_value is not None else None,
        "is_empty": is_empty,
    }
    for passthrough_key in ("crop_index", "roi_id", "roi_kind", "bbox_xyxy"):
        if passthrough_key in image_payload:
            result[passthrough_key] = image_payload[passthrough_key]
    return result


def _evaluate_empty_decision(
    decision_value: float | None,
    *,
    empty_min: float | None,
    empty_max: float | None,
) -> bool | None:
    """根据可选上下限判断当前图片是否满足 empty 条件。"""

    if decision_value is None or (empty_min is None and empty_max is None):
        return None
    if empty_min is not None and decision_value < empty_min:
        return False
    if empty_max is not None and decision_value > empty_max:
        return False
    return True


def _read_uint8_with_default(raw_value: object, *, field_name: str, default_value: int) -> int:
    """读取 0-255 阈值，空值使用默认值。"""

    if is_empty_parameter(raw_value):
        return default_value
    return require_uint8_int(raw_value, field_name=field_name)


def _read_optional_positive_int(raw_value: object, *, field_name: str) -> int | None:
    """读取可选正整数。"""

    if is_empty_parameter(raw_value):
        return None
    return require_positive_int(raw_value, field_name=field_name)


def _read_optional_float(raw_value: object, *, field_name: str) -> float | None:
    """读取可选浮点数。"""

    if is_empty_parameter(raw_value):
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"image-refs-statistics 节点的 {field_name} 必须是数值")
    return float(raw_value)


def _read_decision_metric(raw_value: object) -> str:
    """读取用于 empty 判定的指标。"""

    if is_empty_parameter(raw_value):
        return "none"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("image-refs-statistics 节点的 decision_metric 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in SUPPORTED_DECISION_METRICS:
        raise InvalidRequestError(
            "image-refs-statistics 节点的 decision_metric 仅支持 none、mean_gray、std_gray、dark_ratio、bright_ratio 或 edge_density"
        )
    return normalized_value
