"""Contour 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.debug_image_panel import build_debug_image_preview_output
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.geometry import build_contour_item_from_cv_contour
from custom_nodes._opencv_shared.backend.runtime.payloads import build_contours_payload
from custom_nodes._opencv_shared.backend.runtime.images import load_image_matrix
from custom_nodes._opencv_shared.backend.runtime.search_roi import (
    ResolvedSearchRoi,
    build_search_roi_overlay,
    build_search_roi_summary,
    resolve_search_roi,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_contour_approximation,
    normalize_contour_retrieval_mode,
    require_non_negative_float,
    require_positive_int,
    require_uint8_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.contour"


def _normalize_threshold_mode(raw_value: object) -> str:
    """读取 contour 二值化模式。"""

    if raw_value in {None, ""}:
        return "binary"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("threshold_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"binary", "binary-inverse", "otsu", "otsu-inverse"}:
        raise InvalidRequestError("threshold_mode 仅支持 binary、binary-inverse、otsu、otsu-inverse")
    return normalized_value


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行 contour 提取，并输出结构化 contour 集合。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, image_object_key, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    search_roi = resolve_search_roi(request, image_matrix=image_matrix)

    raw_threshold = request.parameters.get("threshold")
    threshold_value = 127 if raw_threshold in {None, ""} else require_uint8_int(raw_threshold, field_name="threshold")
    threshold_mode = _normalize_threshold_mode(request.parameters.get("threshold_mode"))
    raw_min_area = request.parameters.get("min_area")
    min_area = 0 if raw_min_area in {None, ""} else require_non_negative_float(raw_min_area, field_name="min_area")
    max_contours_raw = request.parameters.get("max_contours")
    if max_contours_raw == "":
        max_contours_raw = None
    max_contours = require_positive_int(max_contours_raw, field_name="max_contours") if max_contours_raw is not None else None
    selected_contour_index_raw = request.parameters.get("selected_contour_index")
    selected_contour_index = (
        require_positive_int(selected_contour_index_raw, field_name="selected_contour_index")
        if selected_contour_index_raw not in {None, ""}
        else None
    )
    raw_retrieval_mode = request.parameters.get("retrieval_mode")
    retrieval_mode = normalize_contour_retrieval_mode(
        "external" if raw_retrieval_mode in {None, ""} else raw_retrieval_mode,
        cv2_module=cv2_module,
    )
    raw_approximation = request.parameters.get("approximation")
    approximation = normalize_contour_approximation(
        "simple" if raw_approximation in {None, ""} else raw_approximation,
        cv2_module=cv2_module,
    )

    threshold_flags = cv2_module.THRESH_BINARY
    if threshold_mode == "binary-inverse":
        threshold_flags = cv2_module.THRESH_BINARY_INV
    elif threshold_mode == "otsu":
        threshold_flags = cv2_module.THRESH_BINARY | cv2_module.THRESH_OTSU
    elif threshold_mode == "otsu-inverse":
        threshold_flags = cv2_module.THRESH_BINARY_INV | cv2_module.THRESH_OTSU
    resolved_threshold, binary_image = cv2_module.threshold(
        search_roi.image_matrix,
        threshold_value,
        255,
        threshold_flags,
    )
    find_contours_result = cv2_module.findContours(binary_image, retrieval_mode, approximation)
    if len(find_contours_result) == 2:
        raw_contours, _ = find_contours_result
    else:
        _, raw_contours, _ = find_contours_result

    contour_items: list[dict[str, object]] = []
    for contour in raw_contours:
        contour_area = float(cv2_module.contourArea(contour))
        if contour_area < min_area:
            continue
        if search_roi.offset_x or search_roi.offset_y:
            contour = contour.copy()
            contour[:, 0, 0] += search_roi.offset_x
            contour[:, 0, 1] += search_roi.offset_y
        contour_item = build_contour_item_from_cv_contour(
            contour=contour,
            contour_index=len(contour_items) + 1,
            cv2_module=cv2_module,
            np_module=np_module,
        )
        if contour_item is None:
            continue
        contour_items.append(contour_item)
        if max_contours is not None and len(contour_items) >= max_contours:
            break
    if selected_contour_index is not None:
        contour_items = [
            item
            for item in contour_items
            if int(item.get("contour_index", -1)) == selected_contour_index
        ]

    outputs: dict[str, object] = {
        "contours": build_contours_payload(
            items=contour_items,
            source_image=image_payload,
            source_object_key=image_object_key,
        ),
        "summary": build_value_payload(
            {
                "count": len(contour_items),
                "threshold": int(round(float(resolved_threshold))),
                "threshold_mode": threshold_mode,
                "requested_threshold": threshold_value,
                "retrieval_mode": str(raw_retrieval_mode or "external"),
                "approximation": str(raw_approximation or "simple"),
                "min_area": min_area,
                "max_contours": max_contours,
                "selected_contour_index": selected_contour_index,
                "max_area": round(max((float(item.get("area", 0.0)) for item in contour_items), default=0.0), 4),
                **build_search_roi_summary(search_roi),
            }
        ),
    }
    outputs.update(
        build_debug_image_preview_output(
            request,
            image_payload=image_payload,
            title="Contour",
            artifact_name="contour-debug-preview",
            overlays=_build_contour_overlays(contour_items, search_roi=search_roi),
            interaction=_build_contour_interaction(
                threshold_value=threshold_value,
                min_area=min_area,
                max_contours=max_contours,
            ),
        )
    )
    return outputs


def _build_contour_interaction(
    *,
    threshold_value: int,
    min_area: float,
    max_contours: int | None,
) -> dict[str, object]:
    """声明 Contour 在图片面板中的取参和调参能力。"""

    return {
        "mode": "edit",
        "coordinate_space": "source-image",
        "tools": [
            {
                "tool": "rect",
                "label": "搜索 ROI",
                "target_parameters": ["search_bbox_xyxy"],
            },
            {
                "tool": "contour",
                "label": "轮廓点选",
                "target_parameters": ["search_bbox_xyxy", "selected_contour_index"],
                "min_points": 3,
            },
        ],
        "controls": [
            _build_numeric_control("threshold", "Threshold", threshold_value, min_value=0.0, max_value=255.0, step=1.0),
            _build_numeric_control("min_area", "Min Area", min_area, min_value=0.0, max_value=20000.0, step=10.0),
            _build_numeric_control("max_contours", "Max Contours", max_contours or 100, min_value=1.0, max_value=500.0, step=1.0),
        ],
    }


def _build_numeric_control(
    parameter_name: str,
    label: str,
    value: float | int,
    *,
    min_value: float,
    max_value: float,
    step: float,
) -> dict[str, object]:
    """构造图片面板实时调参使用的数值控件声明。"""

    return {
        "parameter_name": parameter_name,
        "label": label,
        "control": "slider",
        "min": min_value,
        "max": max_value,
        "step": step,
        "value": value,
        "default_value": value,
    }


def _build_contour_overlays(
    contour_items: list[dict[str, object]],
    *,
    search_roi: ResolvedSearchRoi,
) -> list[dict[str, object]]:
    """把 contour 结果转换为图片面板 overlay。"""

    overlays: list[dict[str, object]] = []
    search_roi_overlay = build_search_roi_overlay(search_roi)
    if search_roi_overlay is not None:
        overlays.append(search_roi_overlay)
    for contour_item in contour_items[:80]:
        raw_points = contour_item.get("points")
        if not isinstance(raw_points, list) or len(raw_points) < 3:
            continue
        contour_index = int(contour_item.get("contour_index", len(overlays) + 1))
        overlays.append(
            {
                "kind": "polygon",
                "id": f"contour-{contour_index}",
                "label": f"contour {contour_index}",
                "points_xy": _decimate_points(raw_points, max_points=160),
                "target_parameters": ["search_bbox_xyxy", "selected_contour_index"],
                "parameters": {"selected_contour_index": contour_index},
            }
        )
    return overlays


def _decimate_points(raw_points: list[object], *, max_points: int) -> list[list[float]]:
    """限制 overlay 点数，避免调试图在大轮廓上过重。"""

    if len(raw_points) <= max_points:
        selected_points = raw_points
    else:
        step = max(1, int(len(raw_points) / max_points))
        selected_points = raw_points[::step][:max_points]
    points_xy: list[list[float]] = []
    for point in selected_points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        points_xy.append([float(point[0]), float(point[1])])
    return points_xy
