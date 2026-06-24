"""Grayscale 节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.validators import normalize_optional_object_key
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.grayscale"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把输入图片转为灰度图，并输出新的图片引用。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=image_matrix,
        error_message="OpenCV 灰度化后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="grayscale",
        output_extension=".png",
        width=int(image_matrix.shape[1]),
        height=int(image_matrix.shape[0]),
        media_type="image/png",
    )
    return {"image": output_payload}
