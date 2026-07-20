"""Contour 节点实现。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.debug_image_panel import (
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_interaction_tool,
    build_number_control,
    build_numeric_control,
    build_polygon_overlay,
    build_select_control,
)
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
from custom_nodes._opencv_shared.backend.runtime.performance import (
    build_processing_image,
    build_processing_summary,
    read_find_result_limit,
    read_processing_max_long_edge,
)


NODE_TYPE_ID = "custom.opencv.contour"


def _normalize_threshold_mode(raw_value: object) -> str:
    """读取 contour 二值化模式。"""

    if is_empty_parameter(raw_value):
        return "binary"
    if not isinstance(raw_value, str):
        raise InvalidRequestError("threshold_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"binary", "binary-inverse", "otsu", "otsu-inverse"}:
        raise InvalidRequestError("threshold_mode 仅支持 binary、binary-inverse、otsu、otsu-inverse")
    return normalized_value


def _read_optional_non_negative_float(raw_value: object, *, field_name: str) -> float | None:
    """读取可选非负浮点过滤参数。"""

    if is_empty_parameter(raw_value):
        return None
    return float(require_non_negative_float(raw_value, field_name=field_name))


def _validate_optional_range(
    minimum: float | None,
    maximum: float | None,
    *,
    minimum_name: str,
    maximum_name: str,
) -> None:
    """验证一组可选最小值和最大值。"""

    if minimum is not None and maximum is not None and minimum > maximum:
        raise InvalidRequestError(f"{minimum_name} 不能大于 {maximum_name}")


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行 contour 提取，并输出结构化 contour 集合。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, image_object_key, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    search_roi = resolve_search_roi(request, image_matrix=image_matrix)

    raw_threshold = request.parameters.get("threshold")
    threshold_value = 127 if is_empty_parameter(raw_threshold) else require_uint8_int(raw_threshold, field_name="threshold")
    threshold_mode = _normalize_threshold_mode(request.parameters.get("threshold_mode"))
    raw_min_area = request.parameters.get("min_area")
    min_area = 0 if is_empty_parameter(raw_min_area) else require_non_negative_float(raw_min_area, field_name="min_area")
    max_area = _read_optional_non_negative_float(request.parameters.get("max_area"), field_name="max_area")
    min_width = _read_optional_non_negative_float(request.parameters.get("min_width"), field_name="min_width")
    max_width = _read_optional_non_negative_float(request.parameters.get("max_width"), field_name="max_width")
    min_height = _read_optional_non_negative_float(request.parameters.get("min_height"), field_name="min_height")
    max_height = _read_optional_non_negative_float(request.parameters.get("max_height"), field_name="max_height")
    min_aspect_ratio = _read_optional_non_negative_float(
        request.parameters.get("min_aspect_ratio"), field_name="min_aspect_ratio"
    )
    max_aspect_ratio = _read_optional_non_negative_float(
        request.parameters.get("max_aspect_ratio"), field_name="max_aspect_ratio"
    )
    min_rectangularity = _read_optional_non_negative_float(
        request.parameters.get("min_rectangularity"), field_name="min_rectangularity"
    )
    max_rectangularity = _read_optional_non_negative_float(
        request.parameters.get("max_rectangularity"), field_name="max_rectangularity"
    )
    if min_rectangularity is not None and min_rectangularity > 1.0:
        raise InvalidRequestError("min_rectangularity 不能大于 1")
    if max_rectangularity is not None and max_rectangularity > 1.0:
        raise InvalidRequestError("max_rectangularity 不能大于 1")
    for minimum, maximum, minimum_name, maximum_name in (
        (float(min_area), max_area, "min_area", "max_area"),
        (min_width, max_width, "min_width", "max_width"),
        (min_height, max_height, "min_height", "max_height"),
        (min_aspect_ratio, max_aspect_ratio, "min_aspect_ratio", "max_aspect_ratio"),
        (min_rectangularity, max_rectangularity, "min_rectangularity", "max_rectangularity"),
    ):
        _validate_optional_range(
            minimum,
            maximum,
            minimum_name=minimum_name,
            maximum_name=maximum_name,
        )
    max_contours = read_find_result_limit(
        request.parameters.get("max_contours"),
        field_name="max_contours",
    )
    processing_max_long_edge = read_processing_max_long_edge(
        request.parameters.get("processing_max_long_edge")
    )
    selected_contour_index_raw = request.parameters.get("selected_contour_index")
    selected_contour_index = (
        require_positive_int(selected_contour_index_raw, field_name="selected_contour_index")
        if not is_empty_parameter(selected_contour_index_raw)
        else None
    )
    raw_retrieval_mode = request.parameters.get("retrieval_mode")
    retrieval_mode = normalize_contour_retrieval_mode(
        "external" if is_empty_parameter(raw_retrieval_mode) else raw_retrieval_mode,
        cv2_module=cv2_module,
    )
    raw_approximation = request.parameters.get("approximation")
    approximation = normalize_contour_approximation(
        "simple" if is_empty_parameter(raw_approximation) else raw_approximation,
        cv2_module=cv2_module,
    )

    threshold_flags = cv2_module.THRESH_BINARY
    if threshold_mode == "binary-inverse":
        threshold_flags = cv2_module.THRESH_BINARY_INV
    elif threshold_mode == "otsu":
        threshold_flags = cv2_module.THRESH_BINARY | cv2_module.THRESH_OTSU
    elif threshold_mode == "otsu-inverse":
        threshold_flags = cv2_module.THRESH_BINARY_INV | cv2_module.THRESH_OTSU
    processing_image = build_processing_image(
        search_roi.image_matrix,
        cv2_module=cv2_module,
        max_long_edge=processing_max_long_edge,
    )
    resolved_threshold, binary_image = cv2_module.threshold(
        processing_image.image_matrix,
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
        contour = _restore_contour_to_source(
            contour,
            processing_image=processing_image,
            offset_x=search_roi.offset_x,
            offset_y=search_roi.offset_y,
            np_module=np_module,
        )
        contour_area = float(cv2_module.contourArea(contour))
        if contour_area < min_area:
            continue
        if max_area is not None and contour_area > max_area:
            continue
        _bbox_x, _bbox_y, bbox_width, bbox_height = cv2_module.boundingRect(contour)
        aspect_ratio = float(bbox_width / bbox_height) if bbox_height > 0 else 0.0
        bbox_area = float(bbox_width * bbox_height)
        rectangularity = contour_area / bbox_area if bbox_area > 0 else 0.0
        if min_width is not None and bbox_width < min_width:
            continue
        if max_width is not None and bbox_width > max_width:
            continue
        if min_height is not None and bbox_height < min_height:
            continue
        if max_height is not None and bbox_height > max_height:
            continue
        if min_aspect_ratio is not None and aspect_ratio < min_aspect_ratio:
            continue
        if max_aspect_ratio is not None and aspect_ratio > max_aspect_ratio:
            continue
        if min_rectangularity is not None and rectangularity < min_rectangularity:
            continue
        if max_rectangularity is not None and rectangularity > max_rectangularity:
            continue
        contour_item = build_contour_item_from_cv_contour(
            contour=contour,
            contour_index=len(contour_items) + 1,
            cv2_module=cv2_module,
            np_module=np_module,
        )
        if contour_item is None:
            continue
        contour_item["rectangularity"] = round(rectangularity, 6)
        contour_items.append(contour_item)
    # findContours 返回顺序不稳定；按面积和原始序号排序后再执行输出上限。
    contour_items.sort(
        key=lambda item: (-float(item.get("area", 0.0)), int(item.get("contour_index", 0)))
    )
    contour_items = contour_items[:max_contours]
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
                "max_area": max_area,
                "min_width": min_width,
                "max_width": max_width,
                "min_height": min_height,
                "max_height": max_height,
                "min_aspect_ratio": min_aspect_ratio,
                "max_aspect_ratio": max_aspect_ratio,
                "min_rectangularity": min_rectangularity,
                "max_rectangularity": max_rectangularity,
                "max_contours": max_contours,
                "processing_max_long_edge": processing_max_long_edge,
                "selected_contour_index": selected_contour_index,
                "result_max_area": round(
                    max((float(item.get("area", 0.0)) for item in contour_items), default=0.0),
                    4,
                ),
                **build_search_roi_summary(search_roi),
                **build_processing_summary(processing_image),
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
                threshold_mode=threshold_mode,
                retrieval_mode=str(raw_retrieval_mode or "external"),
                approximation=str(raw_approximation or "simple"),
                min_area=min_area,
                max_area=max_area,
                min_width=min_width,
                max_width=max_width,
                min_height=min_height,
                max_height=max_height,
                min_aspect_ratio=min_aspect_ratio,
                max_aspect_ratio=max_aspect_ratio,
                min_rectangularity=min_rectangularity,
                max_rectangularity=max_rectangularity,
                max_contours=max_contours,
                processing_max_long_edge=processing_max_long_edge,
                image_width=int(image_matrix.shape[1]),
                image_height=int(image_matrix.shape[0]),
            ),
        )
    )
    return outputs


def _build_contour_interaction(
    *,
    threshold_value: int,
    threshold_mode: str,
    retrieval_mode: str,
    approximation: str,
    min_area: float,
    max_area: float | None,
    min_width: float | None,
    max_width: float | None,
    min_height: float | None,
    max_height: float | None,
    min_aspect_ratio: float | None,
    max_aspect_ratio: float | None,
    min_rectangularity: float | None,
    max_rectangularity: float | None,
    max_contours: int,
    processing_max_long_edge: int,
    image_width: int,
    image_height: int,
) -> dict[str, object]:
    """声明 Contour 在图片面板中的取参和调参能力。"""

    area_max, area_step = _build_area_control_range(image_width=image_width, image_height=image_height)
    return build_debug_panel_interaction(
        tools=[
            build_interaction_tool("rect", "Search ROI", ["search_bbox_xyxy"]),
            build_interaction_tool(
                "contour",
                "Contour",
                ["search_bbox_xyxy", "selected_contour_index"],
                extra={"min_points": 3},
            ),
        ],
        controls=[
            build_numeric_control("threshold", "Threshold", threshold_value, min_value=0.0, max_value=255.0, step=1.0),
            build_select_control(
                "threshold_mode",
                "Threshold Mode",
                threshold_mode,
                options=[
                    ("binary", "Binary"),
                    ("binary-inverse", "Binary Inverse"),
                    ("otsu", "Otsu"),
                    ("otsu-inverse", "Otsu Inverse"),
                ],
            ),
            build_select_control(
                "retrieval_mode",
                "Retrieval Mode",
                retrieval_mode,
                options=[
                    ("external", "External"),
                    ("list", "List"),
                    ("tree", "Tree"),
                    ("ccomp", "CComp"),
                ],
            ),
            build_select_control(
                "approximation",
                "Approximation",
                approximation,
                options=[
                    ("simple", "Simple"),
                    ("none", "None"),
                    ("tc89-l1", "TC89 L1"),
                    ("tc89-kcos", "TC89 KCOS"),
                ],
            ),
            build_numeric_control("min_area", "Min Area", min_area, min_value=0.0, max_value=area_max, step=area_step),
            build_number_control("max_area", "Max Area", max_area, min_value=0.0, max_value=area_max, step=area_step),
            build_number_control("min_width", "Min Width", min_width, min_value=0.0, max_value=float(image_width), step=1.0),
            build_number_control("max_width", "Max Width", max_width, min_value=0.0, max_value=float(image_width), step=1.0),
            build_number_control("min_height", "Min Height", min_height, min_value=0.0, max_value=float(image_height), step=1.0),
            build_number_control("max_height", "Max Height", max_height, min_value=0.0, max_value=float(image_height), step=1.0),
            build_number_control("min_aspect_ratio", "Min Aspect Ratio", min_aspect_ratio, min_value=0.0, max_value=20.0, step=0.05),
            build_number_control("max_aspect_ratio", "Max Aspect Ratio", max_aspect_ratio, min_value=0.0, max_value=20.0, step=0.05),
            build_number_control("min_rectangularity", "Min Rectangularity", min_rectangularity, min_value=0.0, max_value=1.0, step=0.01),
            build_number_control("max_rectangularity", "Max Rectangularity", max_rectangularity, min_value=0.0, max_value=1.0, step=0.01),
            build_number_control("max_contours", "Max Contours", max_contours, min_value=1.0, max_value=1000.0, step=1.0),
            build_numeric_control(
                "processing_max_long_edge",
                "Processing Max Long Edge",
                processing_max_long_edge,
                min_value=256.0,
                max_value=32768.0,
                step=256.0,
            ),
        ],
    )


def _restore_contour_to_source(
    contour: object,
    *,
    processing_image: object,
    offset_x: int,
    offset_y: int,
    np_module: object,
) -> object:
    """把处理图中的 contour 坐标还原到原图坐标系。"""

    restored = np_module.asarray(contour, dtype=np_module.float64).copy()
    restored[:, 0, 0] = (
        restored[:, 0, 0] * float(processing_image.scale_x_to_source) + float(offset_x)
    )
    restored[:, 0, 1] = (
        restored[:, 0, 1] * float(processing_image.scale_y_to_source) + float(offset_y)
    )
    return np_module.rint(restored).astype(np_module.int32)


def _build_area_control_range(*, image_width: int, image_height: int) -> tuple[float, float]:
    """根据当前原图尺寸生成面积调参范围，适配 20MP/8K 工业图像。"""

    image_area = max(1, int(image_width) * int(image_height))
    area_max = float(max(20_000, image_area))
    area_step = float(max(10, round(image_area / 20_000)))
    return area_max, area_step


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
            build_polygon_overlay(
                kind="contour",
                overlay_id=f"contour-{contour_index}",
                label=f"contour {contour_index}",
                polygon_xy=_decimate_points(raw_points, max_points=160),
                target_parameters=["search_bbox_xyxy", "selected_contour_index"],
                parameters={"selected_contour_index": contour_index},
            )
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
