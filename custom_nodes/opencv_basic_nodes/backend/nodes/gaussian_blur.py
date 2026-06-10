"""Gaussian Blur 节点实现。"""

from __future__ import annotations

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.support import (
    build_output_image_payload,
    load_image_matrix,
    normalize_odd_kernel_size,
    normalize_optional_object_key,
    require_non_negative_float,
    require_opencv_imports,
)


NODE_TYPE_ID = "custom.opencv.gaussian-blur"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行高斯模糊，并输出新的图片引用。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)

    raw_kernel_size = request.parameters.get("kernel_size")
    kernel_size = 5 if raw_kernel_size in {None, ""} else normalize_odd_kernel_size(raw_kernel_size)
    raw_sigma_x = request.parameters.get("sigma_x")
    sigma_x = 0.0 if raw_sigma_x in {None, ""} else require_non_negative_float(raw_sigma_x, field_name="sigma_x")
    blurred_image = cv2_module.GaussianBlur(image_matrix, (kernel_size, kernel_size), sigma_x)
    success, encoded_image = cv2_module.imencode(".png", blurred_image)
    if success is not True:
        raise ServiceConfigurationError(
            "OpenCV 高斯模糊后无法编码输出图片",
            details={"node_id": request.node_id},
        )
    output_payload = build_output_image_payload(
        request,
        source_payload=image_payload,
        content=encoded_image.tobytes(),
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="gaussian-blur",
        output_extension=".png",
        width=int(blurred_image.shape[1]),
        height=int(blurred_image.shape[0]),
        media_type="image/png",
    )
    return {"image": output_payload}