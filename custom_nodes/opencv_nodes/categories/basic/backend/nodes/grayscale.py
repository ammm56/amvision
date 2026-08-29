"""Grayscale 节点实现。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.images import (
    build_output_image_matrix_payload,
    load_image_matrix,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.grayscale"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把输入图片转为灰度图，并输出新的图片引用。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_UNCHANGED,
    )
    if len(image_matrix.shape) == 2:
        grayscale_matrix = image_matrix
    elif len(image_matrix.shape) == 3 and int(image_matrix.shape[2]) == 1:
        grayscale_matrix = image_matrix[:, :, 0]
    elif len(image_matrix.shape) == 3 and int(image_matrix.shape[2]) == 3:
        grayscale_matrix = cv2_module.cvtColor(image_matrix, cv2_module.COLOR_BGR2GRAY)
    elif len(image_matrix.shape) == 3 and int(image_matrix.shape[2]) == 4:
        grayscale_matrix = cv2_module.cvtColor(image_matrix, cv2_module.COLOR_BGRA2GRAY)
    else:
        raise InvalidRequestError(
            "Grayscale 不支持当前输入图片布局",
            details={"shape": [int(item) for item in image_matrix.shape]},
        )
    save_location = request.parameters.get("save_location")
    if (
        grayscale_matrix is image_matrix
        and (not isinstance(save_location, str) or not save_location.strip())
    ):
        return {"image": image_payload}
    output_payload = build_output_image_matrix_payload(
        request,
        source_payload=image_payload,
        image_matrix=grayscale_matrix,
        save_location=save_location,
        variant_name="grayscale",
        error_message="OpenCV 灰度化后无法编码输出图片",
    )
    return {"image": output_payload}
