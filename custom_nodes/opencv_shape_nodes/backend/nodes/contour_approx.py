"""Contour Approx 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.geometry import (
    build_contour_item_from_cv_contour,
    contour_points_to_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.payloads import (
    build_contours_payload,
    require_contours_payload,
)
from custom_nodes.opencv_shape_nodes.backend.nodes.debug_contours import build_contours_debug_preview_output
from custom_nodes._opencv_shared.backend.runtime.validators import (
    require_non_negative_float,
    require_positive_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.contour-approx"


def _read_epsilon_mode(raw_value: object) -> str:
    """读取 epsilon 模式。"""

    if raw_value in {None, ""}:
        return "perimeter-ratio"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("contour-approx 节点的 epsilon_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"perimeter-ratio", "pixels"}:
        raise InvalidRequestError("contour-approx 节点的 epsilon_mode 仅支持 perimeter-ratio 或 pixels")
    return normalized_value


def _read_epsilon_value(raw_value: object, *, epsilon_mode: str) -> float:
    """读取 epsilon 值。"""

    default_value = 0.02 if epsilon_mode == "perimeter-ratio" else 2.0
    if raw_value in {None, ""}:
        return default_value
    return require_non_negative_float(raw_value, field_name="epsilon_value")


def _read_closed(raw_value: object) -> bool:
    """读取 closed 参数。"""

    if raw_value in {None, ""}:
        return True
    if not isinstance(raw_value, bool):
        raise InvalidRequestError("contour-approx 节点的 closed 必须是布尔值")
    return raw_value


def _read_optional_limit(raw_value: object) -> int | None:
    """读取可选 limit。"""

    if raw_value in {None, ""}:
        return None
    return require_positive_int(raw_value, field_name="limit")


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对 contour 集合执行多边形近似。"""

    cv2_module, np_module = require_opencv_imports()
    contours_payload = require_contours_payload(request.input_values.get("contours"))
    epsilon_mode = _read_epsilon_mode(request.parameters.get("epsilon_mode"))
    epsilon_value = _read_epsilon_value(request.parameters.get("epsilon_value"), epsilon_mode=epsilon_mode)
    closed = _read_closed(request.parameters.get("closed"))
    limit = _read_optional_limit(request.parameters.get("limit"))

    approximated_items: list[dict[str, object]] = []
    reduced_point_ratios: list[float] = []
    for contour_position, contour_item in enumerate(contours_payload["items"], start=1):
        if limit is not None and contour_position > limit:
            break
        contour_matrix = contour_points_to_matrix(points=contour_item["points"], np_module=np_module)
        source_point_count = int(contour_item["point_count"])
        source_perimeter = float(cv2_module.arcLength(contour_matrix, closed))
        epsilon_pixels = float(epsilon_value if epsilon_mode == "pixels" else source_perimeter * epsilon_value)
        approximated_contour = cv2_module.approxPolyDP(contour_matrix, epsilon_pixels, closed)
        approximated_item = build_contour_item_from_cv_contour(
            contour=approximated_contour,
            contour_index=int(contour_item["contour_index"]),
            cv2_module=cv2_module,
            np_module=np_module,
        )
        if approximated_item is None:
            continue
        approximated_point_count = int(approximated_item["point_count"])
        reduced_point_ratio = round(
            float((source_point_count - approximated_point_count) / source_point_count)
            if source_point_count > 0
            else 0.0,
            6,
        )
        reduced_point_ratios.append(reduced_point_ratio)
        approximated_item["source_point_count"] = source_point_count
        approximated_item["source_perimeter"] = round(source_perimeter, 4)
        approximated_item["epsilon_pixels"] = round(epsilon_pixels, 4)
        approximated_item["reduced_point_ratio"] = reduced_point_ratio
        approximated_items.append(approximated_item)

    output_contours_payload = build_contours_payload(
        items=approximated_items,
        source_image=contours_payload.get("source_image"),
        source_object_key=contours_payload.get("source_object_key")
        if isinstance(contours_payload.get("source_object_key"), str)
        else None,
    )
    outputs: dict[str, object] = {
        "contours": output_contours_payload,
        "summary": build_value_payload(
            {
                "count": len(approximated_items),
                "epsilon_mode": epsilon_mode,
                "epsilon_value": round(float(epsilon_value), 6),
                "closed": closed,
                "limit": limit,
                "mean_reduced_point_ratio": round(
                    (
                        sum(reduced_point_ratios) / len(reduced_point_ratios)
                        if reduced_point_ratios
                        else 0.0
                    ),
                    6,
                ),
                "max_reduced_point_ratio": round(max(reduced_point_ratios, default=0.0), 6),
            }
        ),
    }
    outputs.update(
        build_contours_debug_preview_output(
            request,
            contours_payload=output_contours_payload,
            contour_items=approximated_items,
            title="Contour Approx",
            artifact_name="contour-approx-debug-preview",
        )
    )
    return outputs
