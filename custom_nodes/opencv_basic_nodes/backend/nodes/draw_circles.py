"""Draw Circles 节点实现。"""

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
from custom_nodes._opencv_shared.backend.runtime.payloads import require_circles_payload
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_TYPE_ID = "custom.opencv.draw-circles"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 circle 结果绘制到图片上。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)
    image_matrix = image_matrix.copy()
    circles_payload = require_circles_payload(request.input_values.get("circles"))

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
    draw_radius = False if request.parameters.get("draw_radius") is None else bool(request.parameters.get("draw_radius"))
    draw_diameter = True if request.parameters.get("draw_diameter") is None else bool(request.parameters.get("draw_diameter"))
    draw_center = True if request.parameters.get("draw_center") is None else bool(request.parameters.get("draw_center"))

    for circle_item in circles_payload["items"]:
        center_x, center_y = normalize_point_xy(circle_item.get("center_xy"), field_name="center_xy")
        center_point = (int(round(center_x)), int(round(center_y)))
        radius_pixels = int(round(float(circle_item["radius"])))
        cv2_module.circle(image_matrix, center_point, max(1, radius_pixels), (0, 200, 255), line_thickness, cv2_module.LINE_AA)
        if draw_center:
            cv2_module.circle(image_matrix, center_point, point_radius, (255, 255, 0), thickness=-1)

        label_parts: list[str] = []
        if draw_indices:
            label_parts.append(f"O{int(circle_item['circle_index'])}")
        if draw_diameter:
            label_parts.append(f"D={float(circle_item['diameter']):.1f}px")
        if draw_radius:
            label_parts.append(f"R={float(circle_item['radius']):.1f}px")
        if label_parts:
            cv2_module.putText(
                image_matrix,
                " ".join(label_parts),
                (center_point[0], max(12, center_point[1] - radius_pixels - 6)),
                cv2_module.FONT_HERSHEY_SIMPLEX,
                font_scale,
                (0, 200, 255),
                max(1, line_thickness - 1),
                cv2_module.LINE_AA,
            )

    encoded_image_bytes = encode_png_image_bytes(
        request,
        image_matrix=image_matrix,
        error_message="OpenCV 绘制 circle 后无法编码输出图片",
    )
    return {
        "image": build_output_image_payload(
            request,
            source_payload=image_payload,
            content=encoded_image_bytes,
            object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
            variant_name="draw-circles",
            output_extension=".png",
            width=int(image_matrix.shape[1]),
            height=int(image_matrix.shape[0]),
            media_type="image/png",
        )
    }
