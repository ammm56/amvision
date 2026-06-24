"""Draw Contours 节点实现。"""

from __future__ import annotations

from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.geometry import normalize_bbox
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_optional_object_key,
    require_non_negative_float,
    require_positive_int,
)
from custom_nodes._opencv_shared.backend.runtime.payloads import require_contours_payload
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_TYPE_ID = "custom.opencv.draw-contours"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 contour 结果绘制到图片上。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)
    contours_payload = require_contours_payload(request.input_values.get("contours"))

    raw_line_thickness = request.parameters.get("line_thickness")
    if raw_line_thickness in (None, ""):
        raw_line_thickness = 2
    line_thickness = require_positive_int(raw_line_thickness, field_name="line_thickness")

    raw_font_scale = request.parameters.get("font_scale")
    if raw_font_scale in (None, ""):
        raw_font_scale = 0.5
    font_scale = require_non_negative_float(raw_font_scale, field_name="font_scale")

    draw_indices = True if request.parameters.get("draw_indices") is None else bool(request.parameters.get("draw_indices"))
    draw_bbox = False if request.parameters.get("draw_bbox") is None else bool(request.parameters.get("draw_bbox"))

    for contour_item in contours_payload["items"]:
        contour_matrix = np_module.array(contour_item["points"], dtype=np_module.int32).reshape((-1, 1, 2))
        cv2_module.polylines(image_matrix, [contour_matrix], isClosed=True, color=(0, 255, 255), thickness=line_thickness)
        if draw_bbox:
            x1_value, y1_value, x2_value, y2_value = normalize_bbox(contour_item.get("bbox_xyxy"))
            cv2_module.rectangle(image_matrix, (x1_value, y1_value), (x2_value, y2_value), (255, 200, 0), 1)
        if draw_indices:
            anchor_x = int(contour_item["points"][0][0])
            anchor_y = int(contour_item["points"][0][1])
            cv2_module.putText(
                image_matrix,
                f"C{int(contour_item['contour_index'])}",
                (anchor_x, max(12, anchor_y - 4)),
                cv2_module.FONT_HERSHEY_SIMPLEX,
                font_scale,
                (0, 255, 255),
                max(1, line_thickness - 1),
                cv2_module.LINE_AA,
            )

    encoded_image_bytes = encode_png_image_bytes(
        request,
        image_matrix=image_matrix,
        error_message="OpenCV 绘制 contour 后无法编码输出图片",
    )
    return {
        "image": build_output_image_payload(
            request,
            source_payload=image_payload,
            content=encoded_image_bytes,
            object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
            variant_name="draw-contours",
            output_extension=".png",
            width=int(image_matrix.shape[1]),
            height=int(image_matrix.shape[0]),
            media_type="image/png",
        )
    }
