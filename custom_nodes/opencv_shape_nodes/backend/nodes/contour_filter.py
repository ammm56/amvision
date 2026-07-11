"""Contour Filter 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.payloads import (
    build_contours_payload,
    require_contours_payload,
)
from custom_nodes.opencv_shape_nodes.backend.nodes.debug_contours import build_contours_debug_preview_output
from custom_nodes._opencv_shared.backend.runtime.geometry import compute_contour_metrics_from_points
from custom_nodes._opencv_shared.backend.runtime.validators import (
    require_non_negative_float,
    require_non_negative_int,
    require_positive_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.contour-filter"


def _read_optional_non_negative_float(raw_value: object, *, field_name: str) -> float | None:
    """读取可选非负浮点参数。"""

    if raw_value in {None, ""}:
        return None
    return require_non_negative_float(raw_value, field_name=field_name)


def _read_optional_non_negative_int(raw_value: object, *, field_name: str) -> int | None:
    """读取可选非负整数参数。"""

    if raw_value in {None, ""}:
        return None
    return require_non_negative_int(raw_value, field_name=field_name)


def _read_optional_positive_int(raw_value: object, *, field_name: str) -> int | None:
    """读取可选正整数参数。"""

    if raw_value in {None, ""}:
        return None
    return require_positive_int(raw_value, field_name=field_name)


def _normalize_sort_by(value: object) -> str:
    """规范化 contour-filter 的排序字段。"""

    if not isinstance(value, str) or not value.strip():
        return "contour_index"
    normalized_value = value.strip().lower()
    if normalized_value not in {
        "contour_index",
        "point_count",
        "area",
        "width",
        "height",
        "perimeter",
    }:
        raise InvalidRequestError("sort_by 不在支持的 contour-filter 排序字段列表中")
    return normalized_value


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按面积、宽高和点数过滤 contour 集合。"""

    cv2_module, np_module = require_opencv_imports()
    contours_payload = require_contours_payload(request.input_values.get("contours"))
    min_area = _read_optional_non_negative_float(request.parameters.get("min_area"), field_name="min_area")
    max_area = _read_optional_non_negative_float(request.parameters.get("max_area"), field_name="max_area")
    min_width = _read_optional_non_negative_float(request.parameters.get("min_width"), field_name="min_width")
    max_width = _read_optional_non_negative_float(request.parameters.get("max_width"), field_name="max_width")
    min_height = _read_optional_non_negative_float(request.parameters.get("min_height"), field_name="min_height")
    max_height = _read_optional_non_negative_float(request.parameters.get("max_height"), field_name="max_height")
    min_point_count = _read_optional_non_negative_int(
        request.parameters.get("min_point_count"),
        field_name="min_point_count",
    )
    max_point_count = _read_optional_non_negative_int(
        request.parameters.get("max_point_count"),
        field_name="max_point_count",
    )
    sort_by = _normalize_sort_by(request.parameters.get("sort_by"))
    descending = bool(request.parameters.get("descending", False))
    raw_limit = request.parameters.get("limit")
    limit = None if raw_limit in {None, ""} else require_positive_int(raw_limit, field_name="limit")
    selected_contour_index = _read_optional_positive_int(
        request.parameters.get("selected_contour_index"),
        field_name="selected_contour_index",
    )

    filtered_items: list[tuple[dict[str, object], dict[str, object]]] = []
    for contour_item in contours_payload["items"]:
        contour_index = int(contour_item["contour_index"])
        if selected_contour_index is not None and contour_index != selected_contour_index:
            continue
        contour_metrics = compute_contour_metrics_from_points(
            points=contour_item["points"],
            cv2_module=cv2_module,
            np_module=np_module,
        )
        contour_area = float(contour_metrics["area"])
        contour_width = float(contour_metrics["width"])
        contour_height = float(contour_metrics["height"])
        contour_perimeter = float(contour_metrics["perimeter"])
        point_count = int(contour_item["point_count"])
        if min_area is not None and contour_area < min_area:
            continue
        if max_area is not None and contour_area > max_area:
            continue
        if min_width is not None and contour_width < min_width:
            continue
        if max_width is not None and contour_width > max_width:
            continue
        if min_height is not None and contour_height < min_height:
            continue
        if max_height is not None and contour_height > max_height:
            continue
        if min_point_count is not None and point_count < min_point_count:
            continue
        if max_point_count is not None and point_count > max_point_count:
            continue
        filtered_items.append(
            (
                dict(contour_item),
                {
                    "contour_index": int(contour_item["contour_index"]),
                    "point_count": point_count,
                    "area": contour_area,
                    "width": contour_width,
                    "height": contour_height,
                    "perimeter": contour_perimeter,
                },
            )
        )

    filtered_items.sort(key=lambda current_item: current_item[1][sort_by], reverse=descending)
    if limit is not None:
        filtered_items = filtered_items[:limit]

    contour_items = [item for item, _metrics in filtered_items]
    summary_metrics = [metrics for _item, metrics in filtered_items]
    output_contours_payload = build_contours_payload(
        items=contour_items,
        source_image=contours_payload.get("source_image"),
        source_object_key=contours_payload.get("source_object_key")
        if isinstance(contours_payload.get("source_object_key"), str)
        else None,
    )
    outputs: dict[str, object] = {
        "contours": output_contours_payload,
        "summary": build_value_payload(
            {
                "original_count": len(contours_payload["items"]),
                "filtered_count": len(contour_items),
                "rejected_count": len(contours_payload["items"]) - len(contour_items),
                "sort_by": sort_by,
                "descending": descending,
                "limit": limit,
                "selected_contour_index": selected_contour_index,
                "total_area": round(sum(float(item["area"]) for item in summary_metrics), 4),
                "max_area": round(max((float(item["area"]) for item in summary_metrics), default=0.0), 4),
                "min_area": round(min((float(item["area"]) for item in summary_metrics), default=0.0), 4),
            }
        ),
    }
    outputs.update(
        build_contours_debug_preview_output(
            request,
            contours_payload=output_contours_payload,
            contour_items=contour_items,
            title="Contour Filter",
            artifact_name="contour-filter-debug-preview",
            selected_contour_index=selected_contour_index,
        )
    )
    return outputs
