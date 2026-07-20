"""Circle Measure 工业圆形精定位节点实现。"""

from __future__ import annotations

import math

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.debug_image_panel import (
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
    read_processing_max_long_edge,
)
from custom_nodes._opencv_shared.backend.runtime.search_roi import (
    build_search_roi_overlay,
    build_search_roi_summary,
    resolve_search_roi,
)
from custom_nodes._opencv_shared.backend.runtime.validators import require_non_negative_float


NODE_TYPE_ID = "custom.opencv.circle-measure"


def _read_positive_float(raw_value: object, *, field_name: str, default: float | None = None) -> float:
    """读取必填或带默认值的正浮点参数。"""

    if is_empty_parameter(raw_value):
        if default is None:
            raise InvalidRequestError(f"{field_name} 不能为空")
        return float(default)
    value = float(require_non_negative_float(raw_value, field_name=field_name))
    if value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return value


def _read_reference_center(raw_value: object) -> list[float]:
    """读取原图坐标系中的参考圆心。"""

    if not isinstance(raw_value, list) or len(raw_value) != 2:
        raise InvalidRequestError("reference_center_xy 必须是 [x, y]")
    values: list[float] = []
    for item in raw_value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise InvalidRequestError("reference_center_xy 坐标必须是有限数值")
        values.append(float(item))
    return values


def _read_choice(raw_value: object, *, field_name: str, default: str, choices: set[str]) -> str:
    """读取字符串枚举参数。"""

    if is_empty_parameter(raw_value):
        return default
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    value = raw_value.strip().lower()
    if value not in choices:
        raise InvalidRequestError(f"{field_name} 仅支持 {', '.join(sorted(choices))}")
    return value


def _build_circle_item(*, center_x: float, center_y: float, radius: float, metrics: dict[str, object]) -> dict[str, object]:
    """构造 Circle Measure 输出的 circles.v1 item。"""

    center_x = round(center_x, 4)
    center_y = round(center_y, 4)
    radius = round(radius, 4)
    return {
        "circle_index": 1,
        "center_xy": [center_x, center_y],
        "center_x": center_x,
        "center_y": center_y,
        "radius": radius,
        "diameter": round(radius * 2.0, 4),
        "area": round(math.pi * radius * radius, 4),
        "circumference": round(2.0 * math.pi * radius, 4),
        "bbox_xyxy": [
            round(center_x - radius, 4),
            round(center_y - radius, 4),
            round(center_x + radius, 4),
            round(center_y + radius, 4),
        ],
        "selected": True,
        "subpixel": True,
        **metrics,
    }


def _build_circle_measure_interaction(
    *,
    image_width: int,
    image_height: int,
    center_tolerance_px: float,
    radius_tolerance_px: float,
    radial_sample_count: int,
    gradient_threshold: float,
    edge_polarity: str,
    robust_loss: str,
    ransac_iterations: int,
    fit_inlier_threshold_px: float,
    minimum_arc_coverage: float,
    maximum_fit_error_px: float,
    processing_max_long_edge_px: int,
) -> dict[str, object]:
    """构造 Circle Measure 图片交互声明。"""

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
            build_numeric_control("center_tolerance_px", "Center Tolerance (px)", center_tolerance_px, min_value=0.1, max_value=float(max(image_width, image_height)), step=0.5),
            build_numeric_control("radius_tolerance_px", "Radius Tolerance (px)", radius_tolerance_px, min_value=0.1, max_value=float(min(image_width, image_height) / 2), step=0.5),
            build_numeric_control("radial_sample_count", "Radial Sample Count", radial_sample_count, min_value=12, max_value=720, step=1),
            build_numeric_control("gradient_threshold", "Gradient Threshold", gradient_threshold, min_value=0, max_value=255, step=1),
            build_select_control("edge_polarity", "Edge Polarity", edge_polarity, options=[("any", "Any"), ("dark-to-bright", "Dark To Bright"), ("bright-to-dark", "Bright To Dark")]),
            build_select_control("robust_loss", "Robust Loss", robust_loss, options=[("huber", "Huber"), ("tukey", "Tukey")]),
            build_numeric_control("ransac_iterations", "RANSAC Iterations", ransac_iterations, min_value=1, max_value=256, step=1),
            build_numeric_control("fit_inlier_threshold_px", "Fit Inlier Threshold (px)", fit_inlier_threshold_px, min_value=0.1, max_value=20, step=0.1),
            build_numeric_control("minimum_arc_coverage", "Minimum Arc Coverage", minimum_arc_coverage, min_value=0, max_value=1, step=0.01),
            build_numeric_control("maximum_fit_error_px", "Maximum Fit Error (px)", maximum_fit_error_px, min_value=0.1, max_value=20, step=0.1),
            build_numeric_control("processing_max_long_edge_px", "Processing Max Long Edge (px)", processing_max_long_edge_px, min_value=256, max_value=32768, step=256),
        ],
    )


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """在 Search ROI 中按参考圆执行径向边缘采样和 robust circle fitting。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, source_object_key, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    image_height, image_width = [int(value) for value in image_matrix.shape[:2]]
    search_roi = resolve_search_roi(request, image_matrix=image_matrix)
    reference_center_xy = _read_reference_center(request.parameters.get("reference_center_xy"))
    reference_radius_px = _read_positive_float(
        request.parameters.get("reference_radius_px"),
        field_name="reference_radius_px",
    )
    center_tolerance_px = _read_positive_float(
        request.parameters.get("center_tolerance_px"),
        field_name="center_tolerance_px",
        default=20.0,
    )
    radius_tolerance_px = _read_positive_float(
        request.parameters.get("radius_tolerance_px"),
        field_name="radius_tolerance_px",
        default=10.0,
    )
    radial_sample_count = int(
        _read_positive_float(
            request.parameters.get("radial_sample_count"),
            field_name="radial_sample_count",
            default=180.0,
        )
    )
    if radial_sample_count < 12 or radial_sample_count > 720:
        raise InvalidRequestError("radial_sample_count 必须在 12 到 720 之间")
    gradient_threshold = float(
        require_non_negative_float(
            5.0 if is_empty_parameter(request.parameters.get("gradient_threshold")) else request.parameters.get("gradient_threshold"),
            field_name="gradient_threshold",
        )
    )
    edge_polarity = _read_choice(
        request.parameters.get("edge_polarity"),
        field_name="edge_polarity",
        default="any",
        choices={"any", "dark-to-bright", "bright-to-dark"},
    )
    robust_loss = _read_choice(
        request.parameters.get("robust_loss"),
        field_name="robust_loss",
        default="huber",
        choices={"huber", "tukey"},
    )
    ransac_iterations = int(
        _read_positive_float(
            request.parameters.get("ransac_iterations"),
            field_name="ransac_iterations",
            default=64.0,
        )
    )
    if ransac_iterations > 256:
        raise InvalidRequestError("ransac_iterations 不能大于 256")
    fit_inlier_threshold_px = _read_positive_float(
        request.parameters.get("fit_inlier_threshold_px"),
        field_name="fit_inlier_threshold_px",
        default=2.0,
    )
    minimum_arc_coverage = float(
        require_non_negative_float(
            0.5 if is_empty_parameter(request.parameters.get("minimum_arc_coverage")) else request.parameters.get("minimum_arc_coverage"),
            field_name="minimum_arc_coverage",
        )
    )
    if minimum_arc_coverage > 1:
        raise InvalidRequestError("minimum_arc_coverage 不能大于 1")
    maximum_fit_error_px = _read_positive_float(
        request.parameters.get("maximum_fit_error_px"),
        field_name="maximum_fit_error_px",
        default=2.0,
    )
    processing_max_long_edge_px = read_processing_max_long_edge(
        request.parameters.get("processing_max_long_edge_px")
    )

    local_reference_x = reference_center_xy[0] - float(search_roi.offset_x)
    local_reference_y = reference_center_xy[1] - float(search_roi.offset_y)
    search_height, search_width = [int(value) for value in search_roi.image_matrix.shape[:2]]
    if not (0.0 <= local_reference_x < search_width and 0.0 <= local_reference_y < search_height):
        raise InvalidRequestError("reference_center_xy 必须位于 Search ROI 内")
    processing_image = build_processing_image(
        search_roi.image_matrix,
        cv2_module=cv2_module,
        max_long_edge=processing_max_long_edge_px,
    )
    radius_scale = (processing_image.scale_x_to_source + processing_image.scale_y_to_source) / 2.0
    processing_center_x = local_reference_x / processing_image.scale_x_to_source
    processing_center_y = local_reference_y / processing_image.scale_y_to_source
    processing_reference_radius = reference_radius_px / radius_scale
    processing_radius_tolerance = max(1.0, radius_tolerance_px / radius_scale)
    radial_samples = sample_radial_edges(
        processing_image.image_matrix,
        center_x=processing_center_x,
        center_y=processing_center_y,
        reference_radius_px=processing_reference_radius,
        radius_tolerance_px=processing_radius_tolerance,
        sample_count=radial_sample_count,
        gradient_threshold=gradient_threshold,
        edge_polarity=edge_polarity,
        cv2_module=cv2_module,
        np_module=np_module,
    )
    rejection_reasons: list[str] = []
    try:
        fitted = fit_circle_robust(
            radial_samples.points_xy,
            np_module=np_module,
            robust_loss=robust_loss,
            inlier_threshold_px=max(0.25, fit_inlier_threshold_px / radius_scale),
            ransac_iterations=ransac_iterations,
        )
    except (InvalidRequestError, ValueError, ArithmeticError):
        fitted = None
        rejection_reasons.append(
            "insufficient_edge_samples"
            if radial_samples.accepted_count < 3
            else "circle_fit_failed"
        )

    metrics: dict[str, object] = {
        "arc_coverage": 0.0,
        "fit_rmse_px": None,
        "max_residual_px": None,
        "center_deviation_px": None,
        "radius_deviation_px": None,
        "edge_sample_count": radial_samples.accepted_count,
        "ransac_inlier_count": 0,
        "edge_inlier_count": 0,
        "mean_edge_strength": round(
            float(np_module.mean(radial_samples.edge_strengths))
            if radial_samples.accepted_count > 0
            else 0.0,
            4,
        ),
    }
    measured_circle: tuple[float, float, float] | None = None
    output_items: list[dict[str, object]] = []
    if fitted is not None:
        center_x = fitted.center_x * processing_image.scale_x_to_source + float(search_roi.offset_x)
        center_y = fitted.center_y * processing_image.scale_y_to_source + float(search_roi.offset_y)
        radius = fitted.radius * radius_scale
        center_deviation_px = math.hypot(
            center_x - reference_center_xy[0],
            center_y - reference_center_xy[1],
        )
        radius_deviation_px = abs(radius - reference_radius_px)
        fit_rmse_px = fitted.fit_rmse_px * radius_scale
        if center_deviation_px > center_tolerance_px:
            rejection_reasons.append("center_tolerance_exceeded")
        if radius_deviation_px > radius_tolerance_px:
            rejection_reasons.append("radius_tolerance_exceeded")
        if fitted.arc_coverage < minimum_arc_coverage:
            rejection_reasons.append("insufficient_arc_coverage")
        if fit_rmse_px > maximum_fit_error_px:
            rejection_reasons.append("fit_error_exceeded")
        metrics.update(
            {
                "arc_coverage": round(fitted.arc_coverage, 6),
                "fit_rmse_px": round(fit_rmse_px, 4),
                "max_residual_px": round(fitted.max_residual_px * radius_scale, 4),
                "center_deviation_px": round(center_deviation_px, 4),
                "radius_deviation_px": round(radius_deviation_px, 4),
                "edge_sample_count": fitted.sample_count,
                "ransac_inlier_count": fitted.ransac_inlier_count,
                "edge_inlier_count": fitted.inlier_count,
            }
        )
        circle_item = _build_circle_item(
            center_x=center_x,
            center_y=center_y,
            radius=radius,
            metrics=metrics,
        )
        measured_circle = (center_x, center_y, radius)
        if rejection_reasons:
            circle_item["selected"] = False
            circle_item["rejection_reasons"] = rejection_reasons
        else:
            output_items.append(circle_item)
    accepted = fitted is not None and not rejection_reasons
    summary = {
        "accepted": accepted,
        "rejection_reasons": rejection_reasons,
        "reference_center_xy": reference_center_xy,
        "reference_radius_px": reference_radius_px,
        "center_tolerance_px": center_tolerance_px,
        "radius_tolerance_px": radius_tolerance_px,
        "radial_sample_count": radial_sample_count,
        "gradient_threshold": gradient_threshold,
        "edge_polarity": edge_polarity,
        "robust_loss": robust_loss,
        "ransac_iterations": ransac_iterations,
        "fit_inlier_threshold_px": fit_inlier_threshold_px,
        "minimum_arc_coverage": minimum_arc_coverage,
        "maximum_fit_error_px": maximum_fit_error_px,
        **metrics,
        **build_search_roi_summary(search_roi),
        **build_processing_summary(processing_image),
    }
    overlays: list[dict[str, object]] = []
    search_overlay = build_search_roi_overlay(search_roi)
    if search_overlay is not None:
        overlays.append(search_overlay)
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
    if measured_circle is not None:
        overlays.append(
            build_circle_overlay(
                overlay_id="measured-circle",
                label="Measured Circle" if accepted else "Rejected Circle",
                center_x=measured_circle[0],
                center_y=measured_circle[1],
                radius=measured_circle[2],
                kind="selected-circle" if accepted else "rejected-circle",
            )
        )
    outputs: dict[str, object] = {
        "circles": build_circles_payload(
            items=output_items,
            source_image=image_payload,
            source_object_key=source_object_key,
        ),
        "summary": build_value_payload(summary),
    }
    outputs.update(
        build_debug_image_preview_output(
            request,
            image_payload=image_payload,
            title="Circle Measure",
            artifact_name="circle-measure-debug-preview",
            overlays=overlays,
            interaction=_build_circle_measure_interaction(
                image_width=image_width,
                image_height=image_height,
                center_tolerance_px=center_tolerance_px,
                radius_tolerance_px=radius_tolerance_px,
                radial_sample_count=radial_sample_count,
                gradient_threshold=gradient_threshold,
                edge_polarity=edge_polarity,
                robust_loss=robust_loss,
                ransac_iterations=ransac_iterations,
                fit_inlier_threshold_px=fit_inlier_threshold_px,
                minimum_arc_coverage=minimum_arc_coverage,
                maximum_fit_error_px=maximum_fit_error_px,
                processing_max_long_edge_px=processing_max_long_edge_px,
            ),
        )
    )
    return outputs
