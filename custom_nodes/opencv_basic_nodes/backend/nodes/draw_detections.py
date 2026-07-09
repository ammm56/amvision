"""Draw Detections 节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_matrix_payload,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.payloads import (
    build_detection_label,
    iter_detection_items,
)
from custom_nodes._opencv_shared.backend.runtime.geometry import normalize_bbox
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_optional_object_key,
    require_non_negative_float,
    require_positive_int,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.draw-detections"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 detection 结果绘制到图片上，并输出新的图片引用。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)

    raw_line_thickness = request.parameters.get("line_thickness")
    if raw_line_thickness in (None, ""):
        raw_line_thickness = 2
    line_thickness = require_positive_int(raw_line_thickness, field_name="line_thickness")

    raw_font_scale = request.parameters.get("font_scale")
    if raw_font_scale in (None, ""):
        raw_font_scale = 0.5
    font_scale = require_non_negative_float(raw_font_scale, field_name="font_scale")

    raw_draw_scores = request.parameters.get("draw_scores")
    draw_scores = True if raw_draw_scores is None else bool(raw_draw_scores)
    for item in iter_detection_items(request.input_values.get("detections")):
        x1, y1, x2, y2 = normalize_bbox(item.get("bbox_xyxy"))
        cv2_module.rectangle(image_matrix, (x1, y1), (x2, y2), (0, 255, 0), line_thickness)
        label_text = build_detection_label(item=item, draw_scores=draw_scores)
        if label_text:
            cv2_module.putText(
                image_matrix,
                label_text,
                (x1, max(12, y1 - 6)),
                cv2_module.FONT_HERSHEY_SIMPLEX,
                font_scale,
                (0, 255, 0),
                max(1, line_thickness - 1),
                cv2_module.LINE_AA,
            )

    output_payload = build_output_image_matrix_payload(
        request,
        source_payload=image_payload,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="draw-detections",
        image_matrix=image_matrix,
        error_message="OpenCV 绘制 detection 后无法编码输出图片",
    )
    return {"image": output_payload}
