"""Barcode 结果绘制节点实现。"""

from __future__ import annotations

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.barcode_protocol_nodes.backend.support import (
    _read_bool_parameter,
    build_barcode_label,
    build_output_image_payload,
    iter_barcode_result_items,
    load_image_matrix,
    normalize_optional_object_key,
    require_barcode_runtime_imports,
    require_non_negative_float,
    require_positive_int,
)
from custom_nodes.barcode_protocol_nodes.specs import DRAW_BARCODE_RESULTS_NODE_TYPE_ID, NODE_PACK_ID, NODE_PACK_VERSION


NODE_TYPE_ID = DRAW_BARCODE_RESULTS_NODE_TYPE_ID

NODE_DEFINITION_PAYLOAD = {
    "format_id": "amvision.node-definition.v1",
    "node_type_id": NODE_TYPE_ID,
    "display_name": "Draw Barcode Results",
    "category": "barcode.render",
    "description": "把 barcode-results 中的 position 轮廓和文本叠加回原图，输出新的图片引用。",
    "implementation_kind": "custom-node",
    "runtime_kind": "python-callable",
    "input_ports": [
        {
            "name": "image",
            "display_name": "Image",
            "payload_type_id": "image-ref.v1",
        },
        {
            "name": "results",
            "display_name": "Results",
            "payload_type_id": "barcode-results.v1",
        },
    ],
    "output_ports": [
        {
            "name": "image",
            "display_name": "Image",
            "payload_type_id": "image-ref.v1",
        }
    ],
    "parameter_schema": {
        "type": "object",
        "properties": {
            "line_thickness": {"type": "integer", "minimum": 1},
            "font_scale": {"type": "number", "minimum": 0},
            "draw_polygon": {"type": "boolean"},
            "draw_text": {"type": "boolean"},
            "draw_format": {"type": "boolean"},
            "draw_index": {"type": "boolean"},
            "output_object_key": {"type": "string"},
        },
    },
    "capability_tags": ["barcode.render", "barcode.draw"],
    "runtime_requirements": {"python_packages": ["opencv-python", "numpy"]},
    "node_pack_id": NODE_PACK_ID,
    "node_pack_version": NODE_PACK_VERSION,
    "metadata": {
        "input_kind": "barcode-results.v1",
        "position_field": "position",
    },
}


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把 barcode-results 中的 position 轮廓和文本叠加回原图。"""

    cv2_module, np_module, _ = require_barcode_runtime_imports()
    image_payload, _, image_matrix = load_image_matrix(request)

    line_thickness = require_positive_int(request.parameters.get("line_thickness", 2), field_name="line_thickness")
    font_scale = require_non_negative_float(request.parameters.get("font_scale", 0.5), field_name="font_scale")
    draw_polygon = _read_bool_parameter(request, field_name="draw_polygon", default=True)
    draw_text = _read_bool_parameter(request, field_name="draw_text", default=True)
    draw_format = _read_bool_parameter(request, field_name="draw_format", default=False)
    draw_index = _read_bool_parameter(request, field_name="draw_index", default=False)

    for item in iter_barcode_result_items(request.input_values.get("results")):
        polygon_xy = item["position"]["polygon_xy"]
        if draw_polygon:
            polygon_points = np_module.array(polygon_xy, dtype=np_module.int32).reshape((-1, 1, 2))
            cv2_module.polylines(image_matrix, [polygon_points], True, (0, 255, 0), line_thickness)

        label_text = build_barcode_label(
            item=item,
            draw_text=draw_text,
            draw_format=draw_format,
            draw_index=draw_index,
        )
        if label_text:
            _draw_label(
                image_matrix=image_matrix,
                label_text=label_text,
                anchor_xy=polygon_xy[0],
                line_thickness=line_thickness,
                font_scale=font_scale,
                cv2_module=cv2_module,
            )

    success, encoded_image = cv2_module.imencode(".png", image_matrix)
    if success is not True:
        raise ServiceConfigurationError(
            "Barcode 结果绘制后无法编码输出图片",
            details={"node_id": request.node_id},
        )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image.tobytes(),
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="draw-barcode-results",
        output_extension=".png",
        width=int(image_matrix.shape[1]),
        height=int(image_matrix.shape[0]),
        media_type="image/png",
    )
    return {"image": output_payload}


def _draw_label(
    *,
    image_matrix: object,
    label_text: str,
    anchor_xy: list[int],
    line_thickness: int,
    font_scale: float,
    cv2_module: object,
) -> None:
    """在指定锚点附近绘制条码标签。"""

    text_size, baseline = cv2_module.getTextSize(
        label_text,
        cv2_module.FONT_HERSHEY_SIMPLEX,
        font_scale,
        max(1, line_thickness - 1),
    )
    image_height, image_width = image_matrix.shape[:2]
    anchor_x = max(0, min(int(anchor_xy[0]), image_width - 1))
    anchor_y = max(0, min(int(anchor_xy[1]), image_height - 1))
    text_width, text_height = text_size
    padding = 3
    background_left = anchor_x
    background_top = max(0, anchor_y - text_height - baseline - padding * 2)
    background_right = min(image_width - 1, anchor_x + text_width + padding * 2)
    background_bottom = min(image_height - 1, background_top + text_height + baseline + padding * 2)
    cv2_module.rectangle(
        image_matrix,
        (background_left, background_top),
        (background_right, background_bottom),
        (0, 255, 0),
        thickness=-1,
    )
    cv2_module.putText(
        image_matrix,
        label_text,
        (background_left + padding, background_bottom - baseline - padding),
        cv2_module.FONT_HERSHEY_SIMPLEX,
        font_scale,
        (0, 0, 0),
        max(1, line_thickness - 1),
        cv2_module.LINE_AA,
    )
