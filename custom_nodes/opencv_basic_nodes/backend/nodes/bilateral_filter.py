"""Bilateral Filter 节点实现。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.debug_image_panel import (
    build_debug_image_preview_output,
    build_debug_panel_interaction,
    build_interaction_tool,
    build_numeric_control,
)
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
    normalize_optional_object_key,
    require_non_negative_float,
    require_positive_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.bilateral-filter"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行双边滤波。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)
    raw_diameter = request.parameters.get("diameter")
    diameter = 9 if is_empty_parameter(raw_diameter) else require_positive_int(raw_diameter, field_name="diameter")
    raw_sigma_color = request.parameters.get("sigma_color")
    sigma_color = 75.0 if is_empty_parameter(raw_sigma_color) else require_non_negative_float(raw_sigma_color, field_name="sigma_color")
    raw_sigma_space = request.parameters.get("sigma_space")
    sigma_space = 75.0 if is_empty_parameter(raw_sigma_space) else require_non_negative_float(raw_sigma_space, field_name="sigma_space")
    search_roi = resolve_search_roi(request, image_matrix=image_matrix)
    filtered_roi = cv2_module.bilateralFilter(
        search_roi.image_matrix,
        diameter,
        sigma_color,
        sigma_space,
    )
    if search_roi.bbox_xyxy is None:
        output_image = filtered_roi
    else:
        # 输出仍保持完整 BGR24 坐标空间；仅复制一次原图并替换 ROI，避免破坏下游。
        output_image = image_matrix.copy()
        x1_value, y1_value, x2_value, y2_value = search_roi.bbox_xyxy
        output_image[y1_value:y2_value, x1_value:x2_value] = filtered_roi
    output_payload = build_output_image_matrix_payload(
        request,
        source_payload=image_payload,
        image_matrix=output_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="bilateral-filter",
        error_message="OpenCV bilateral-filter 后无法编码输出图片",
    )
    processing_height, processing_width = search_roi.image_matrix.shape[:2]
    outputs: dict[str, object] = {
        "image": output_payload,
        "summary": build_value_payload(
            {
                "diameter": diameter,
                "sigma_color": sigma_color,
                "sigma_space": sigma_space,
                "processing_width": int(processing_width),
                "processing_height": int(processing_height),
                "processing_pixel_count": int(processing_width) * int(processing_height),
                **build_search_roi_summary(search_roi),
            }
        ),
    }
    search_overlay = build_search_roi_overlay(search_roi)
    outputs.update(
        build_debug_image_preview_output(
            request,
            image_payload=output_payload,
            title="Bilateral Filter",
            artifact_name="bilateral-filter-debug-preview",
            overlays=[search_overlay] if search_overlay is not None else [],
            interaction=build_debug_panel_interaction(
                tools=[build_interaction_tool("rect", "Processing ROI", ["search_bbox_xyxy"])],
                controls=[
                    build_numeric_control(
                        "diameter",
                        "Diameter",
                        diameter,
                        min_value=1,
                        max_value=31,
                        step=2,
                    ),
                    build_numeric_control(
                        "sigma_color",
                        "Sigma Color",
                        sigma_color,
                        min_value=0.0,
                        max_value=255.0,
                        step=1.0,
                    ),
                    build_numeric_control(
                        "sigma_space",
                        "Sigma Space",
                        sigma_space,
                        min_value=0.0,
                        max_value=255.0,
                        step=1.0,
                    ),
                ],
            ),
        )
    )
    return outputs
