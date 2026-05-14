"""Draw Detections 节点实现。"""

from __future__ import annotations

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.support import (
    build_output_image_payload,
    build_detection_label,
    iter_detection_items,
    load_image_matrix,
    normalize_bbox,
    normalize_optional_object_key,
    require_non_negative_float,
    require_opencv_imports,
    require_positive_int,
)


NODE_TYPE_ID = "custom.opencv.draw-detections"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 detection 结果绘制到图片上，并输出新的图片引用。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)

    line_thickness = require_positive_int(request.parameters.get("line_thickness", 2), field_name="line_thickness")
    font_scale = require_non_negative_float(request.parameters.get("font_scale", 0.5), field_name="font_scale")
    draw_scores = bool(request.parameters.get("draw_scores", True))
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

    success, encoded_image = cv2_module.imencode(".png", image_matrix)
    if success is not True:
        raise ServiceConfigurationError(
            "OpenCV 绘制 detection 后无法编码输出图片",
            details={"node_id": request.node_id},
        )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image.tobytes(),
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="draw-detections",
        output_extension=".png",
        width=int(image_matrix.shape[1]),
        height=int(image_matrix.shape[0]),
        media_type="image/png",
    )
    return {"image": output_payload}