"""Canny 节点实现。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.debug_image_panel import (
    build_checkbox_control,
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_interaction_tool,
    build_numeric_control,
    build_select_control,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_matrix_payload,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.search_roi import (
    build_search_roi_overlay,
    build_search_roi_summary,
    resolve_search_roi,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_odd_kernel_size,
    normalize_optional_object_key,
    require_aperture_size,
    require_non_negative_float,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.canny"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行 Canny 边缘检测，并输出新的图片引用。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )

    raw_threshold1 = request.parameters.get("threshold1")
    threshold1 = 50 if is_empty_parameter(raw_threshold1) else require_non_negative_float(raw_threshold1, field_name="threshold1")
    raw_threshold2 = request.parameters.get("threshold2")
    threshold2 = 150 if is_empty_parameter(raw_threshold2) else require_non_negative_float(raw_threshold2, field_name="threshold2")
    if threshold1 > 255 or threshold2 > 255:
        raise InvalidRequestError("Canny threshold1/threshold2 不能大于 255")
    if threshold2 <= threshold1:
        raise InvalidRequestError("Canny threshold2 必须大于 threshold1")
    raw_aperture_size = request.parameters.get("aperture_size")
    aperture_size = 3 if is_empty_parameter(raw_aperture_size) else require_aperture_size(raw_aperture_size)
    l2_gradient = bool(request.parameters.get("l2_gradient", False))
    raw_blur_kernel_size = request.parameters.get("pre_blur_kernel_size")
    pre_blur_kernel_size = (
        3 if is_empty_parameter(raw_blur_kernel_size) else normalize_odd_kernel_size(raw_blur_kernel_size)
    )
    search_roi = resolve_search_roi(request, image_matrix=image_matrix)
    processing_matrix = search_roi.image_matrix
    if pre_blur_kernel_size > 1:
        processing_matrix = cv2_module.GaussianBlur(
            processing_matrix,
            (pre_blur_kernel_size, pre_blur_kernel_size),
            0,
        )
    edge_matrix = cv2_module.Canny(
        processing_matrix,
        threshold1,
        threshold2,
        apertureSize=aperture_size,
        L2gradient=l2_gradient,
    )
    if search_roi.bbox_xyxy is None:
        output_image = edge_matrix
    else:
        output_image = np_module.zeros_like(image_matrix)
        x1_value, y1_value, x2_value, y2_value = search_roi.bbox_xyxy
        output_image[y1_value:y2_value, x1_value:x2_value] = edge_matrix
    output_payload = build_output_image_matrix_payload(
        request,
        source_payload=image_payload,
        image_matrix=output_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="canny",
        error_message="OpenCV Canny 后无法编码输出图片",
    )
    outputs: dict[str, object] = {
        "image": output_payload,
        "summary": build_value_payload(
            {
                "threshold1": threshold1,
                "threshold2": threshold2,
                "aperture_size": aperture_size,
                "l2_gradient": l2_gradient,
                "pre_blur_kernel_size": pre_blur_kernel_size,
                "edge_pixel_count": int(np_module.count_nonzero(output_image)),
                **build_search_roi_summary(search_roi),
            }
        ),
    }
    search_overlay = build_search_roi_overlay(search_roi)
    outputs.update(
        build_debug_image_preview_output(
            request,
            image_payload=output_payload,
            title="Canny Edge",
            artifact_name="canny-debug-preview",
            overlays=[search_overlay] if search_overlay is not None else [],
            interaction=build_debug_panel_interaction(
                tools=[build_interaction_tool("rect", "Search ROI", ["search_bbox_xyxy"])],
                controls=[
                    build_numeric_control("threshold1", "Threshold 1", threshold1, min_value=0.0, max_value=255.0, step=1.0),
                    build_numeric_control("threshold2", "Threshold 2", threshold2, min_value=0.0, max_value=255.0, step=1.0),
                    build_select_control(
                        "pre_blur_kernel_size",
                        "Pre Blur Kernel Size",
                        str(pre_blur_kernel_size),
                        options=[("1", "1"), ("3", "3"), ("5", "5"), ("7", "7"), ("9", "9")],
                    ),
                    build_select_control(
                        "aperture_size",
                        "Aperture Size",
                        str(aperture_size),
                        options=[("3", "3"), ("5", "5"), ("7", "7")],
                    ),
                    build_checkbox_control("l2_gradient", "L2 Gradient", l2_gradient),
                ],
            ),
        )
    )
    return outputs
