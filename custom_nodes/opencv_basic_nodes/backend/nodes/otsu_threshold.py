"""Otsu Threshold 节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.support import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
    normalize_binary_threshold_mode,
    normalize_optional_object_key,
    require_opencv_imports,
    require_uint8_int,
)


NODE_TYPE_ID = "custom.opencv.otsu-threshold"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入灰度图执行 Otsu threshold。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    raw_max_value = request.parameters.get("max_value")
    max_value = 255 if raw_max_value in {None, ""} else require_uint8_int(raw_max_value, field_name="max_value")
    raw_threshold_type = request.parameters.get("threshold_type")
    threshold_type = normalize_binary_threshold_mode(
        "binary" if raw_threshold_type in {None, ""} else raw_threshold_type,
        cv2_module=cv2_module,
    )
    _, threshold_image = cv2_module.threshold(
        image_matrix,
        0,
        max_value,
        threshold_type | cv2_module.THRESH_OTSU,
    )
    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=threshold_image,
        error_message="OpenCV otsu-threshold 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="otsu-threshold",
        output_extension=".png",
        width=int(threshold_image.shape[1]),
        height=int(threshold_image.shape[0]),
        media_type="image/png",
    )
    return {"image": output_payload}
