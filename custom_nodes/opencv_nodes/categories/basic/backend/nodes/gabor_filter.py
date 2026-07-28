"""Gabor Filter 节点实现。"""

from __future__ import annotations

import math

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
    ensure_gray,
    read_float,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.gabor-filter"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """使用 Gabor 核增强指定方向和频率的纹理。"""

    cv2_module, _ = require_opencv_imports()
    source_payload, _, image = load_image_matrix(request)
    gray = ensure_gray(image, cv2_module=cv2_module)
    kernel_size = read_int(request.parameters.get("kernel_size"), field_name="kernel_size", default=21, minimum=3)
    if kernel_size % 2 == 0:
        raise InvalidRequestError("kernel_size 必须是奇数")
    sigma = read_float(request.parameters.get("sigma"), field_name="sigma", default=5.0, minimum=0.01)
    theta_deg = read_float(request.parameters.get("theta_deg"), field_name="theta_deg", default=0.0)
    wavelength = read_float(request.parameters.get("wavelength"), field_name="wavelength", default=10.0, minimum=0.01)
    gamma = read_float(request.parameters.get("gamma"), field_name="gamma", default=0.5, minimum=0.01)
    phase_deg = read_float(request.parameters.get("phase_deg"), field_name="phase_deg", default=0.0)
    kernel = cv2_module.getGaborKernel(
        (kernel_size, kernel_size),
        sigma,
        math.radians(theta_deg),
        wavelength,
        gamma,
        math.radians(phase_deg),
        ktype=cv2_module.CV_32F,
    )
    response = cv2_module.filter2D(gray, cv2_module.CV_32F, kernel)
    output = cv2_module.normalize(response, None, 0, 255, cv2_module.NORM_MINMAX).astype("uint8")
    return {
        "image": build_image_output(
            request,
            source_payload=source_payload,
            image_matrix=output,
            variant_name="gabor-filter",
            output_object_key=request.parameters.get("output_object_key"),
        )
    }
