"""Draw Lines 节点实现。"""

from __future__ import annotations

from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_optional_object_key,
    require_non_negative_float,
    require_positive_int,
)
from custom_nodes._opencv_shared.backend.runtime.geometry import normalize_point_xy
from custom_nodes._opencv_shared.backend.runtime.payloads import require_lines_payload
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_TYPE_ID = "custom.opencv.draw-lines"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 line 结果绘制到图片上。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)
    image_matrix = image_matrix.copy()
    lines_payload = require_lines_payload(request.input_values.get("lines"))

    raw_line_thickness = request.parameters.get("line_thickness")
    if raw_line_thickness in (None, ""):
        raw_line_thickness = 2
    line_thickness = require_positive_int(raw_line_thickness, field_name="line_thickness")

    raw_point_radius = request.parameters.get("point_radius")
    if raw_point_radius in (None, ""):
        raw_point_radius = 3
    point_radius = require_positive_int(raw_point_radius, field_name="point_radius")

    raw_font_scale = request.parameters.get("font_scale")
    if raw_font_scale in (None, ""):
        raw_font_scale = 0.5
    font_scale = require_non_negative_float(raw_font_scale, field_name="font_scale")

    draw_indices = True if request.parameters.get("draw_indices") is None else bool(request.parameters.get("draw_indices"))
    draw_angle = True if request.parameters.get("draw_angle") is None else bool(request.parameters.get("draw_angle"))
    draw_length = True if request.parameters.get("draw_length") is None else bool(request.parameters.get("draw_length"))
    draw_midpoint = True if request.parameters.get("draw_midpoint") is None else bool(request.parameters.get("draw_midpoint"))

    for line_item in lines_payload["items"]:
        start_x, start_y = normalize_point_xy(line_item.get("start_xy"), field_name="start_xy")
        end_x, end_y = normalize_point_xy(line_item.get("end_xy"), field_name="end_xy")
        midpoint_x, midpoint_y = normalize_point_xy(line_item.get("midpoint_xy"), field_name="midpoint_xy")
        start_point = (int(round(start_x)), int(round(start_y)))
        end_point = (int(round(end_x)), int(round(end_y)))
        midpoint_point = (int(round(midpoint_x)), int(round(midpoint_y)))
        cv2_module.line(image_matrix, start_point, end_point, (0, 255, 0), line_thickness, cv2_module.LINE_AA)
        cv2_module.circle(image_matrix, start_point, point_radius, (0, 160, 255), thickness=-1)
        cv2_module.circle(image_matrix, end_point, point_radius, (0, 160, 255), thickness=-1)
        if draw_midpoint:
            cv2_module.circle(image_matrix, midpoint_point, point_radius, (255, 255, 0), thickness=-1)

        label_parts: list[str] = []
        if draw_indices:
            label_parts.append(f"L{int(line_item['line_index'])}")
        if draw_angle:
            label_parts.append(f"{float(line_item['angle_deg']):.1f}deg")
        if draw_length:
            label_parts.append(f"{float(line_item['length_pixels']):.1f}px")
        if label_parts:
            cv2_module.putText(
                image_matrix,
                " ".join(label_parts),
                (midpoint_point[0], max(12, midpoint_point[1] - 6)),
                cv2_module.FONT_HERSHEY_SIMPLEX,
                font_scale,
                (0, 255, 0),
                max(1, line_thickness - 1),
                cv2_module.LINE_AA,
            )

    encoded_image_bytes = encode_png_image_bytes(
        request,
        image_matrix=image_matrix,
        error_message="OpenCV 绘制 line 后无法编码输出图片",
    )
    return {
        "image": build_output_image_payload(
            request,
            source_payload=image_payload,
            content=encoded_image_bytes,
            object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
            variant_name="draw-lines",
            output_extension=".png",
            width=int(image_matrix.shape[1]),
            height=int(image_matrix.shape[0]),
            media_type="image/png",
        )
    }
