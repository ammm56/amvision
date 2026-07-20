"""Hough Circles 节点实现。"""

from __future__ import annotations

import math

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.debug_image_panel import (
    build_checkbox_control,
    build_circle_overlay,
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_interaction_tool,
    build_numeric_control,
    build_select_control,
)
from backend.nodes.parameter_utils import is_empty_parameter
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.circle_measurement import (
    fit_circle_robust,
    sample_radial_edges,
)
from custom_nodes._opencv_shared.backend.runtime.images import load_image_matrix
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.payloads import build_circles_payload
from custom_nodes._opencv_shared.backend.runtime.performance import (
    build_processing_image,
    build_processing_summary,
    read_find_result_limit,
    read_processing_max_long_edge,
    require_bounded_circle_search,
)
from custom_nodes._opencv_shared.backend.runtime.search_roi import (
    ResolvedSearchRoi,
    build_search_roi_overlay,
    build_search_roi_summary,
    resolve_search_roi,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_odd_kernel_size,
    require_boolean,
    require_non_negative_float,
)
from custom_nodes.opencv_shape_nodes.backend.nodes.hough_circle_contract import (
    build_circle_item as _build_circle_item,
    normalize_sort_by as _normalize_sort_by,
    read_choice as _read_choice,
    read_non_negative_int as _read_non_negative_int,
    read_optional_point as _read_optional_point,
    read_positive_float as _read_positive_float,
)


NODE_TYPE_ID = "custom.opencv.hough-circles"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行 Hough 圆检测。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, source_object_key, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    image_height = int(image_matrix.shape[0])
    image_width = int(image_matrix.shape[1])
    search_roi = resolve_search_roi(request, image_matrix=image_matrix)
    accumulator_resolution_ratio = _read_positive_float(
        request.parameters.get("accumulator_resolution_ratio"),
        field_name="accumulator_resolution_ratio",
        default_value=1.0,
    )
    minimum_center_distance_px = _read_positive_float(
        request.parameters.get("minimum_center_distance_px"),
        field_name="minimum_center_distance_px",
        default_value=20.0,
    )
    canny_high_threshold = _read_positive_float(
        request.parameters.get("canny_high_threshold"),
        field_name="canny_high_threshold",
        default_value=100.0,
    )
    center_vote_threshold = _read_positive_float(
        request.parameters.get("center_vote_threshold"),
        field_name="center_vote_threshold",
        default_value=20.0,
    )
    minimum_radius_px = _read_non_negative_int(
        request.parameters.get("minimum_radius_px"),
        field_name="minimum_radius_px",
        default_value=0,
    )
    maximum_radius_px = _read_non_negative_int(
        request.parameters.get("maximum_radius_px"),
        field_name="maximum_radius_px",
        default_value=0,
    )
    if maximum_radius_px > 0 and maximum_radius_px < minimum_radius_px:
        raise InvalidRequestError("maximum_radius_px 不能小于 minimum_radius_px")
    raw_median_blur_kernel_size = request.parameters.get("median_blur_kernel_size")
    median_blur_kernel_size = (
        5
        if is_empty_parameter(raw_median_blur_kernel_size)
        else normalize_odd_kernel_size(raw_median_blur_kernel_size)
    )
    if median_blur_kernel_size > 31:
        raise InvalidRequestError("median_blur_kernel_size 不能大于 31")
    reference_center_xy = _read_optional_point(
        request.parameters.get("reference_center_xy"),
        field_name="reference_center_xy",
    )
    raw_reference_radius = request.parameters.get("reference_radius_px")
    reference_radius_px = (
        None
        if is_empty_parameter(raw_reference_radius)
        else _read_positive_float(raw_reference_radius, field_name="reference_radius_px", default_value=1.0)
    )
    if (reference_center_xy is None) != (reference_radius_px is None):
        raise InvalidRequestError("reference_center_xy 和 reference_radius_px 必须同时设置或同时留空")
    center_tolerance_px = _read_positive_float(
        request.parameters.get("center_tolerance_px"),
        field_name="center_tolerance_px",
        default_value=50.0,
    )
    radius_tolerance_px = _read_positive_float(
        request.parameters.get("radius_tolerance_px"),
        field_name="radius_tolerance_px",
        default_value=10.0,
    )
    refine_candidates = require_boolean(
        request.parameters.get("refine_candidates", True),
        field_name="refine_candidates",
    )
    edge_polarity = _read_choice(
        request.parameters.get("edge_polarity"),
        field_name="edge_polarity",
        default_value="any",
        choices={"any", "dark-to-bright", "bright-to-dark"},
    )
    radial_sample_count = _read_non_negative_int(
        request.parameters.get("radial_sample_count"),
        field_name="radial_sample_count",
        default_value=180,
    )
    if radial_sample_count < 12 or radial_sample_count > 720:
        raise InvalidRequestError("radial_sample_count 必须在 12 到 720 之间")
    gradient_threshold = float(
        require_non_negative_float(
            5.0
            if is_empty_parameter(request.parameters.get("gradient_threshold"))
            else request.parameters.get("gradient_threshold"),
            field_name="gradient_threshold",
        )
    )
    robust_loss = _read_choice(
        request.parameters.get("robust_loss"),
        field_name="robust_loss",
        default_value="huber",
        choices={"huber", "tukey"},
    )
    ransac_iterations = _read_non_negative_int(
        request.parameters.get("ransac_iterations"),
        field_name="ransac_iterations",
        default_value=32,
    )
    if ransac_iterations < 1 or ransac_iterations > 256:
        raise InvalidRequestError("ransac_iterations 必须在 1 到 256 之间")
    fit_inlier_threshold_px = _read_positive_float(
        request.parameters.get("fit_inlier_threshold_px"),
        field_name="fit_inlier_threshold_px",
        default_value=2.0,
    )
    minimum_arc_coverage = float(
        require_non_negative_float(
            0.2
            if is_empty_parameter(request.parameters.get("minimum_arc_coverage"))
            else request.parameters.get("minimum_arc_coverage"),
            field_name="minimum_arc_coverage",
        )
    )
    if minimum_arc_coverage > 1.0:
        raise InvalidRequestError("minimum_arc_coverage 不能大于 1")
    maximum_fit_error_px = _read_positive_float(
        request.parameters.get("maximum_fit_error_px"),
        field_name="maximum_fit_error_px",
        default_value=3.0,
    )
    sort_by = _normalize_sort_by(request.parameters.get("sort_by"))
    descending = require_boolean(
        request.parameters.get("descending", True),
        field_name="descending",
    )
    max_results = read_find_result_limit(
        request.parameters.get("max_results"),
        field_name="max_results",
    )
    maximum_candidates = _read_non_negative_int(
        request.parameters.get("maximum_candidates"),
        field_name="maximum_candidates",
        default_value=40,
    )
    if maximum_candidates < 1 or maximum_candidates > 200:
        raise InvalidRequestError("maximum_candidates 必须在 1 到 200 之间")
    if max_results > maximum_candidates:
        raise InvalidRequestError("max_results 不能大于 maximum_candidates")
    processing_max_long_edge = read_processing_max_long_edge(
        request.parameters.get("processing_max_long_edge_px")
    )
    search_height, search_width = [int(value) for value in search_roi.image_matrix.shape[:2]]
    if reference_center_xy is not None and not (
        float(search_roi.offset_x) <= reference_center_xy[0] < float(search_roi.offset_x + search_width)
        and float(search_roi.offset_y) <= reference_center_xy[1] < float(search_roi.offset_y + search_height)
    ):
        raise InvalidRequestError("reference_center_xy 必须位于 Search ROI 内")
    search_center_x = float(search_roi.offset_x) + float(search_width) / 2.0
    search_center_y = float(search_roi.offset_y) + float(search_height) / 2.0
    require_bounded_circle_search(
        source_width=search_width,
        source_height=search_height,
        min_radius=minimum_radius_px,
        max_radius=maximum_radius_px,
    )
    processing_image = build_processing_image(
        search_roi.image_matrix,
        cv2_module=cv2_module,
        max_long_edge=processing_max_long_edge,
    )
    processing_scale = min(
        float(processing_image.processing_width) / float(processing_image.source_width),
        float(processing_image.processing_height) / float(processing_image.source_height),
    )

    circle_input_image = (
        cv2_module.medianBlur(processing_image.image_matrix, median_blur_kernel_size)
        if median_blur_kernel_size > 1
        else processing_image.image_matrix
    )
    raw_circles = cv2_module.HoughCircles(
        circle_input_image,
        method=cv2_module.HOUGH_GRADIENT,
        dp=accumulator_resolution_ratio,
        minDist=max(1.0, minimum_center_distance_px * processing_scale),
        param1=canny_high_threshold,
        param2=center_vote_threshold,
        minRadius=int(round(minimum_radius_px * processing_scale)) if minimum_radius_px > 0 else 0,
        maxRadius=max(1, int(round(maximum_radius_px * processing_scale))) if maximum_radius_px > 0 else 0,
    )
    circle_items: list[dict[str, object]] = []
    rejected_items: list[dict[str, object]] = []
    candidate_processing_limit = maximum_candidates
    if raw_circles is not None:
        for circle_index, raw_circle in enumerate(
            raw_circles[0][:candidate_processing_limit],
            start=1,
        ):
            local_center_x = float(raw_circle[0])
            local_center_y = float(raw_circle[1])
            local_radius = float(raw_circle[2])
            radius_scale = (processing_image.scale_x_to_source + processing_image.scale_y_to_source) / 2.0
            fit_metrics: dict[str, object] = {
                "refined": False,
                "arc_coverage": 0.0,
                "fit_rmse_px": 0.0,
                "max_residual_px": 0.0,
                "edge_sample_count": 0,
                "ransac_inlier_count": 0,
                "edge_inlier_count": 0,
            }
            rejection_reasons: list[str] = []
            if refine_candidates:
                try:
                    radial_samples = sample_radial_edges(
                        circle_input_image,
                        center_x=local_center_x,
                        center_y=local_center_y,
                        reference_radius_px=local_radius,
                        radius_tolerance_px=max(2.0, radius_tolerance_px * processing_scale),
                        sample_count=radial_sample_count,
                        gradient_threshold=gradient_threshold,
                        edge_polarity=edge_polarity,
                        cv2_module=cv2_module,
                        np_module=np_module,
                    )
                    fitted = fit_circle_robust(
                        radial_samples.points_xy,
                        np_module=np_module,
                        robust_loss=robust_loss,
                        inlier_threshold_px=max(0.5, fit_inlier_threshold_px * processing_scale),
                        ransac_iterations=ransac_iterations,
                    )
                    local_center_x = fitted.center_x
                    local_center_y = fitted.center_y
                    local_radius = fitted.radius
                    fit_metrics = {
                        "refined": True,
                        "arc_coverage": round(fitted.arc_coverage, 6),
                        "fit_rmse_px": round(fitted.fit_rmse_px * radius_scale, 4),
                        "max_residual_px": round(fitted.max_residual_px * radius_scale, 4),
                        "edge_sample_count": fitted.sample_count,
                        "ransac_inlier_count": fitted.ransac_inlier_count,
                        "edge_inlier_count": fitted.inlier_count,
                        "mean_edge_strength": round(
                            float(np_module.mean(radial_samples.edge_strengths))
                            if radial_samples.accepted_count > 0
                            else 0.0,
                            4,
                        ),
                    }
                except (InvalidRequestError, ValueError, ArithmeticError):
                    rejection_reasons.append("circle_refinement_failed")
            center_x = local_center_x * processing_image.scale_x_to_source + float(search_roi.offset_x)
            center_y = local_center_y * processing_image.scale_y_to_source + float(search_roi.offset_y)
            radius = local_radius * radius_scale
            if reference_center_xy is not None and math.hypot(
                center_x - reference_center_xy[0], center_y - reference_center_xy[1]
            ) > center_tolerance_px:
                rejection_reasons.append("center_tolerance_exceeded")
            if reference_radius_px is not None and abs(radius - reference_radius_px) > radius_tolerance_px:
                rejection_reasons.append("radius_tolerance_exceeded")
            if refine_candidates and float(fit_metrics["arc_coverage"]) < minimum_arc_coverage:
                rejection_reasons.append("insufficient_arc_coverage")
            if refine_candidates and float(fit_metrics["fit_rmse_px"]) > maximum_fit_error_px:
                rejection_reasons.append("fit_error_exceeded")
            item = _build_circle_item(
                circle_index=circle_index,
                center_x=center_x,
                center_y=center_y,
                radius=radius,
                search_center_xy=(search_center_x, search_center_y),
                reference_center_xy=reference_center_xy,
                reference_radius_px=reference_radius_px,
                fit_metrics=fit_metrics,
            )
            if rejection_reasons:
                item["rejection_reasons"] = rejection_reasons
                rejected_items.append(item)
            else:
                circle_items.append(item)

    circle_items.sort(
        key=lambda current_item: (
            -float(current_item[sort_by]) if descending else float(current_item[sort_by]),
            float(current_item["center_y"]),
            float(current_item["center_x"]),
            float(current_item["radius"]),
        )
    )
    circle_items = circle_items[:max_results]
    for selected_index, item in enumerate(circle_items, start=1):
        item["circle_index"] = selected_index
        item["selected"] = selected_index == 1

    outputs: dict[str, object] = {
        "circles": build_circles_payload(
            items=circle_items,
            source_image=image_payload,
            source_object_key=source_object_key,
        ),
        "summary": build_value_payload(
            {
                "count": len(circle_items),
                "rejected_count": len(rejected_items),
                "sort_by": sort_by,
                "descending": descending,
                "max_results": max_results,
                "maximum_candidates": maximum_candidates,
                "accumulator_resolution_ratio": accumulator_resolution_ratio,
                "minimum_center_distance_px": minimum_center_distance_px,
                "canny_high_threshold": canny_high_threshold,
                "center_vote_threshold": center_vote_threshold,
                "minimum_radius_px": minimum_radius_px,
                "maximum_radius_px": maximum_radius_px,
                "median_blur_kernel_size": median_blur_kernel_size,
                "processing_max_long_edge_px": processing_max_long_edge,
                "reference_center_xy": reference_center_xy,
                "reference_radius_px": reference_radius_px,
                "center_tolerance_px": center_tolerance_px,
                "radius_tolerance_px": radius_tolerance_px,
                "refine_candidates": refine_candidates,
                "edge_polarity": edge_polarity,
                "radial_sample_count": radial_sample_count,
                "gradient_threshold": gradient_threshold,
                "robust_loss": robust_loss,
                "ransac_iterations": ransac_iterations,
                "fit_inlier_threshold_px": fit_inlier_threshold_px,
                "minimum_arc_coverage": minimum_arc_coverage,
                "maximum_fit_error_px": maximum_fit_error_px,
                "max_radius_detected": round(
                    max((float(item["radius"]) for item in circle_items), default=0.0),
                    4,
                ),
                "mean_radius_detected": round(
                    (
                        sum(float(item["radius"]) for item in circle_items) / len(circle_items)
                        if circle_items
                        else 0.0
                    ),
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
            title="Hough Circles",
            artifact_name="hough-circles-debug-preview",
            overlays=_build_circle_overlays(
                circle_items,
                rejected_items=rejected_items,
                search_roi=search_roi,
                reference_center_xy=reference_center_xy,
                reference_radius_px=reference_radius_px,
            ),
            interaction=_build_circle_interaction(
                accumulator_resolution_ratio=accumulator_resolution_ratio,
                minimum_center_distance_px=minimum_center_distance_px,
                canny_high_threshold=canny_high_threshold,
                center_vote_threshold=center_vote_threshold,
                minimum_radius_px=minimum_radius_px,
                maximum_radius_px=maximum_radius_px,
                median_blur_kernel_size=median_blur_kernel_size,
                processing_max_long_edge=processing_max_long_edge,
                reference_center_xy=reference_center_xy,
                reference_radius_px=reference_radius_px,
                center_tolerance_px=center_tolerance_px,
                radius_tolerance_px=radius_tolerance_px,
                refine_candidates=refine_candidates,
                edge_polarity=edge_polarity,
                radial_sample_count=radial_sample_count,
                gradient_threshold=gradient_threshold,
                robust_loss=robust_loss,
                ransac_iterations=ransac_iterations,
                fit_inlier_threshold_px=fit_inlier_threshold_px,
                minimum_arc_coverage=minimum_arc_coverage,
                maximum_fit_error_px=maximum_fit_error_px,
                sort_by=sort_by,
                descending=descending,
                max_results=max_results,
                maximum_candidates=maximum_candidates,
                image_width=image_width,
                image_height=image_height,
            ),
        )
    )
    return outputs


def _build_circle_interaction(
    *,
    accumulator_resolution_ratio: float,
    minimum_center_distance_px: float,
    canny_high_threshold: float,
    center_vote_threshold: float,
    minimum_radius_px: int,
    maximum_radius_px: int,
    median_blur_kernel_size: int,
    processing_max_long_edge: int,
    reference_center_xy: list[float] | None,
    reference_radius_px: float | None,
    center_tolerance_px: float,
    radius_tolerance_px: float,
    refine_candidates: bool,
    edge_polarity: str,
    radial_sample_count: int,
    gradient_threshold: float,
    robust_loss: str,
    ransac_iterations: int,
    fit_inlier_threshold_px: float,
    minimum_arc_coverage: float,
    maximum_fit_error_px: float,
    sort_by: str,
    descending: bool,
    max_results: int,
    maximum_candidates: int,
    image_width: int,
    image_height: int,
) -> dict[str, object]:
    """声明 Hough Circles 在图片面板中的取参和调参能力。"""

    long_edge, diagonal_length, radius_max = _build_circle_control_ranges(
        image_width=image_width,
        image_height=image_height,
    )
    return build_debug_panel_interaction(
        tools=[
            build_interaction_tool("rect", "Search ROI", ["search_bbox_xyxy"]),
            build_interaction_tool(
                "circle",
                "Reference Circle",
                [
                    "reference_center_xy",
                    "reference_radius_px",
                    "center_tolerance_px",
                    "radius_tolerance_px",
                ],
            ),
        ],
        controls=[
            build_numeric_control(
                "accumulator_resolution_ratio",
                "Accumulator Resolution Ratio",
                accumulator_resolution_ratio,
                min_value=0.1,
                max_value=4.0,
                step=0.1,
            ),
            build_numeric_control(
                "minimum_center_distance_px",
                "Minimum Center Distance (px)",
                minimum_center_distance_px,
                min_value=1.0,
                max_value=diagonal_length,
                step=1.0,
            ),
            build_numeric_control(
                "canny_high_threshold",
                "Canny High Threshold",
                canny_high_threshold,
                min_value=1.0,
                max_value=300.0,
                step=1.0,
            ),
            build_numeric_control(
                "center_vote_threshold",
                "Center Vote Threshold",
                center_vote_threshold,
                min_value=1.0,
                max_value=200.0,
                step=1.0,
            ),
            build_numeric_control(
                "minimum_radius_px",
                "Minimum Radius (px)",
                minimum_radius_px,
                min_value=0.0,
                max_value=radius_max,
                step=1.0,
            ),
            build_numeric_control(
                "maximum_radius_px",
                "Maximum Radius (px)",
                maximum_radius_px,
                min_value=0.0,
                max_value=long_edge,
                step=1.0,
            ),
            build_numeric_control(
                "median_blur_kernel_size",
                "Median Blur Kernel Size",
                median_blur_kernel_size,
                min_value=1.0,
                max_value=31.0,
                step=2.0,
            ),
            build_numeric_control(
                "processing_max_long_edge_px",
                "Processing Max Long Edge (px)",
                processing_max_long_edge,
                min_value=256.0,
                max_value=32768.0,
                step=256.0,
            ),
            build_numeric_control(
                "center_tolerance_px",
                "Center Tolerance (px)",
                center_tolerance_px,
                min_value=1.0,
                max_value=diagonal_length,
                step=1.0,
            ),
            build_numeric_control(
                "radius_tolerance_px",
                "Radius Tolerance (px)",
                radius_tolerance_px,
                min_value=1.0,
                max_value=radius_max,
                step=1.0,
            ),
            build_checkbox_control("refine_candidates", "Refine Candidates", refine_candidates),
            build_select_control(
                "edge_polarity",
                "Edge Polarity",
                edge_polarity,
                options=[
                    ("any", "Any"),
                    ("dark-to-bright", "Dark To Bright"),
                    ("bright-to-dark", "Bright To Dark"),
                ],
            ),
            build_numeric_control(
                "radial_sample_count",
                "Radial Sample Count",
                radial_sample_count,
                min_value=12.0,
                max_value=720.0,
                step=1.0,
            ),
            build_numeric_control(
                "gradient_threshold",
                "Gradient Threshold",
                gradient_threshold,
                min_value=0.0,
                max_value=255.0,
                step=1.0,
            ),
            build_select_control(
                "robust_loss",
                "Robust Loss",
                robust_loss,
                options=[("huber", "Huber"), ("tukey", "Tukey")],
            ),
            build_numeric_control(
                "ransac_iterations",
                "RANSAC Iterations",
                ransac_iterations,
                min_value=1.0,
                max_value=256.0,
                step=1.0,
            ),
            build_numeric_control(
                "fit_inlier_threshold_px",
                "Fit Inlier Threshold (px)",
                fit_inlier_threshold_px,
                min_value=0.1,
                max_value=20.0,
                step=0.1,
            ),
            build_numeric_control(
                "minimum_arc_coverage",
                "Minimum Arc Coverage",
                minimum_arc_coverage,
                min_value=0.0,
                max_value=1.0,
                step=0.01,
            ),
            build_numeric_control(
                "maximum_fit_error_px",
                "Maximum Fit Error (px)",
                maximum_fit_error_px,
                min_value=0.1,
                max_value=20.0,
                step=0.1,
            ),
            build_select_control(
                "sort_by",
                "Sort By",
                sort_by,
                options=[
                    ("circle_index", "Circle Index"),
                    ("radius", "Radius"),
                    ("diameter", "Diameter"),
                    ("area", "Area"),
                    ("center_x", "Center X"),
                    ("center_y", "Center Y"),
                    ("search_center_distance", "Search Center Distance"),
                    ("reference_center_distance", "Reference Center Distance"),
                    ("reference_radius_deviation", "Reference Radius Deviation"),
                    ("quality_score", "Quality Score"),
                ],
            ),
            build_checkbox_control("descending", "Descending", descending),
            build_numeric_control(
                "max_results",
                "Max Results",
                max_results,
                min_value=1.0,
                max_value=1000.0,
                step=1.0,
            ),
            build_numeric_control(
                "maximum_candidates",
                "Maximum Candidates",
                maximum_candidates,
                min_value=1.0,
                max_value=200.0,
                step=1.0,
            ),
        ],
    )


def _build_circle_control_ranges(*, image_width: int, image_height: int) -> tuple[float, float, float]:
    """按原图尺寸生成 Hough Circles 调参范围，避免 20MP/8K 图像被固定上限卡住。"""

    normalized_width = max(1, int(image_width))
    normalized_height = max(1, int(image_height))
    long_edge = float(max(800, normalized_width, normalized_height))
    diagonal_length = float(max(600, math.ceil(math.hypot(normalized_width, normalized_height))))
    radius_max = float(max(400, math.ceil(min(normalized_width, normalized_height) / 2)))
    return long_edge, diagonal_length, radius_max


def _build_circle_overlays(
    circle_items: list[dict[str, object]],
    *,
    rejected_items: list[dict[str, object]],
    search_roi: ResolvedSearchRoi,
    reference_center_xy: list[float] | None,
    reference_radius_px: float | None,
) -> list[dict[str, object]]:
    """把 Hough 圆检测结果转换为图片面板 overlay。"""

    overlays: list[dict[str, object]] = []
    search_roi_overlay = build_search_roi_overlay(search_roi)
    if search_roi_overlay is not None:
        overlays.append(search_roi_overlay)
    if reference_center_xy is not None and reference_radius_px is not None:
        overlays.append(
            build_circle_overlay(
                overlay_id="reference-circle",
                label="Reference Circle",
                center_x=reference_center_xy[0],
                center_y=reference_center_xy[1],
                radius=reference_radius_px,
                kind="reference-circle",
                target_parameters=[
                    "reference_center_xy",
                    "reference_radius_px",
                    "center_tolerance_px",
                    "radius_tolerance_px",
                ],
            )
        )
    for circle_item in circle_items:
        center_xy = circle_item.get("center_xy")
        radius = circle_item.get("radius")
        if not isinstance(center_xy, list) or len(center_xy) < 2 or not isinstance(radius, (int, float)):
            continue
        circle_index = circle_item.get("circle_index", len(overlays) + 1)
        overlays.append(
            build_circle_overlay(
                overlay_id=f"circle-{circle_index}",
                label=f"circle {circle_index}",
                center_x=float(center_xy[0]),
                center_y=float(center_xy[1]),
                radius=float(radius),
                kind="selected-circle" if bool(circle_item.get("selected")) else "detected-circle",
            )
        )
    for rejected_index, circle_item in enumerate(rejected_items[:10], start=1):
        center_xy = circle_item.get("center_xy")
        radius = circle_item.get("radius")
        if not isinstance(center_xy, list) or len(center_xy) < 2 or not isinstance(radius, (int, float)):
            continue
        overlays.append(
            build_circle_overlay(
                overlay_id=f"rejected-circle-{rejected_index}",
                label=f"rejected circle {rejected_index}",
                center_x=float(center_xy[0]),
                center_y=float(center_xy[1]),
                radius=float(radius),
                kind="rejected-circle",
            )
        )
    return overlays
