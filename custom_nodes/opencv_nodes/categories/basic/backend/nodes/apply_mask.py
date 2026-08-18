"""Apply Mask 节点实现。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
    ensure_gray,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.apply-mask"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """使用单通道 mask 保留图片前景。"""

    cv2_module, _ = require_opencv_imports()
    source_payload, _, image = load_image_matrix(request)
    _, _, mask = load_image_matrix(request, input_name="mask")
    mask = ensure_gray(mask, cv2_module=cv2_module)
    if mask.shape[:2] != image.shape[:2]:
        raise InvalidRequestError("mask 尺寸必须与 image 一致")
    output = cv2_module.bitwise_and(image, image, mask=mask)
    return {
        "image": build_image_output(
            request,
            source_payload=source_payload,
            image_matrix=output,
            variant_name="apply-mask",
            save_location=request.parameters.get("save_location"),
        )
    }
