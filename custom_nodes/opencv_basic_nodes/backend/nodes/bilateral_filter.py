"""Bilateral Filter 节点实现。"""

from __future__ import annotations

from backend.nodes.parameter_utils import is_empty_parameter

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
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
    filtered_image = cv2_module.bilateralFilter(image_matrix, diameter, sigma_color, sigma_space)
    encoded_image = encode_png_image_bytes(
        request,
        image_matrix=filtered_image,
        error_message="OpenCV bilateral-filter 后无法编码输出图片",
    )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="bilateral-filter",
        output_extension=".png",
        width=int(filtered_image.shape[1]),
        height=int(filtered_image.shape[0]),
        media_type="image/png",
    )
    return {"image": output_payload}
