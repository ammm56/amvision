"""Grayscale 节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.images import (
    build_output_image_matrix_payload,
    load_image_matrix,
)
from custom_nodes._opencv_shared.backend.runtime.validators import normalize_optional_object_key
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports


NODE_TYPE_ID = "custom.opencv.grayscale"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把输入图片转为灰度图，并输出新的图片引用。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, _, image_matrix = load_image_matrix(request)
    grayscale_matrix = cv2_module.cvtColor(image_matrix, cv2_module.COLOR_BGR2GRAY)
    output_payload = build_output_image_matrix_payload(
        request,
        source_payload=image_payload,
        image_matrix=grayscale_matrix,
        object_key=normalize_optional_object_key(request.parameters.get("output_object_key")),
        variant_name="grayscale",
        error_message="OpenCV 灰度化后无法编码输出图片",
    )
    return {"image": output_payload}
