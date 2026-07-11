"""Convex Hull 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.geometry import (
    build_contour_item_from_cv_contour,
    compute_contour_metrics_from_points,
    contour_points_to_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.payloads import (
    build_contours_payload,
    require_contours_payload,
)
from custom_nodes.opencv_shape_nodes.backend.nodes.debug_contours import build_contours_debug_preview_output
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.validators import require_positive_int


NODE_TYPE_ID = "custom.opencv.convex-hull"


def _read_optional_limit(raw_value: object) -> int | None:
    """读取可选 limit。"""

    if raw_value in {None, ""}:
        return None
    return require_positive_int(raw_value, field_name="limit")


def _read_optional_selected_contour_index(raw_value: object) -> int | None:
    """读取可选点选 contour 序号。"""

    if raw_value in {None, ""}:
        return None
    return require_positive_int(raw_value, field_name="selected_contour_index")


def _read_sort_by(raw_value: object) -> str:
    """读取排序字段。"""

    if raw_value in {None, ""}:
        return "contour_index"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("convex-hull 节点的 sort_by 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"contour_index", "contour_area", "hull_area", "solidity", "point_count"}:
        raise InvalidRequestError("convex-hull 节点的 sort_by 不在支持列表中")
    return normalized_value


def _read_descending(raw_value: object) -> bool:
    """读取 descending。"""

    if raw_value in {None, ""}:
        return False
    if not isinstance(raw_value, bool):
        raise InvalidRequestError("convex-hull 节点的 descending 必须是布尔值")
    return raw_value


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对 contour 集合计算凸包。"""

    cv2_module, np_module = require_opencv_imports()
    contours_payload = require_contours_payload(request.input_values.get("contours"))
    sort_by = _read_sort_by(request.parameters.get("sort_by"))
    descending = _read_descending(request.parameters.get("descending"))
    limit = _read_optional_limit(request.parameters.get("limit"))
    selected_contour_index = _read_optional_selected_contour_index(request.parameters.get("selected_contour_index"))

    hull_items: list[dict[str, object]] = []
    for contour_item in contours_payload["items"]:
        if selected_contour_index is not None and int(contour_item["contour_index"]) != selected_contour_index:
            continue
        contour_matrix = contour_points_to_matrix(points=contour_item["points"], np_module=np_module)
        convex_hull = cv2_module.convexHull(contour_matrix)
        hull_item = build_contour_item_from_cv_contour(
            contour=convex_hull,
            contour_index=int(contour_item["contour_index"]),
            cv2_module=cv2_module,
            np_module=np_module,
        )
        if hull_item is None:
            continue
        contour_metrics = compute_contour_metrics_from_points(
            points=contour_item["points"],
            cv2_module=cv2_module,
            np_module=np_module,
        )
        hull_metrics = compute_contour_metrics_from_points(
            points=hull_item["points"],
            cv2_module=cv2_module,
            np_module=np_module,
        )
        contour_area = round(float(contour_metrics["area"]), 4)
        hull_area = round(float(hull_metrics["area"]), 4)
        solidity = round(float(contour_area / hull_area), 6) if hull_area > 0 else 0.0
        hull_item["source_point_count"] = int(contour_item["point_count"])
        hull_item["contour_area"] = contour_area
        hull_item["hull_area"] = hull_area
        hull_item["solidity"] = solidity
        hull_items.append(hull_item)

    hull_items.sort(key=lambda current_item: current_item[sort_by], reverse=descending)
    if limit is not None:
        hull_items = hull_items[:limit]

    output_contours_payload = build_contours_payload(
        items=hull_items,
        source_image=contours_payload.get("source_image"),
        source_object_key=contours_payload.get("source_object_key")
        if isinstance(contours_payload.get("source_object_key"), str)
        else None,
    )
    outputs: dict[str, object] = {
        "contours": output_contours_payload,
        "summary": build_value_payload(
            {
                "count": len(hull_items),
                "sort_by": sort_by,
                "descending": descending,
                "limit": limit,
                "selected_contour_index": selected_contour_index,
                "mean_solidity": round(
                    (
                        sum(float(item["solidity"]) for item in hull_items) / len(hull_items)
                        if hull_items
                        else 0.0
                    ),
                    6,
                ),
                "max_hull_area": round(max((float(item["hull_area"]) for item in hull_items), default=0.0), 4),
            }
        ),
    }
    outputs.update(
        build_contours_debug_preview_output(
            request,
            contours_payload=output_contours_payload,
            contour_items=hull_items,
            title="Convex Hull",
            artifact_name="convex-hull-debug-preview",
        )
    )
    return outputs
