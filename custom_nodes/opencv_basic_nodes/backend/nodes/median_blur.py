"""Median Blur 节点实现。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_payload,
    encode_png_image_bytes,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.validators import (
    normalize_odd_kernel_size,
    normalize_optional_object_key,
)
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.median-blur"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行中值滤波。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)
    raw_kernel_size = request.parameters.get("kernel_size")
    kernel_size = 5 if is_empty_parameter(raw_kernel_size) else normalize_odd_kernel_size(raw_kernel_size)
    blurred_image = cv2_module.medianBlur(image_matrix, kernel_size)
    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=blurred_image,
        error_message="OpenCV median-blur 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="median-blur",
        output_extension=".png",
        width=int(blurred_image.shape[1]),
        height=int(blurred_image.shape[0]),
        media_type="image/png",
    )
    return {"image": output_payload}
