"""Image Arithmetic 节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
    read_choice,
    read_float,
    require_same_shape,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.image-arithmetic"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对两张同形状图片执行饱和算术或绝对差。"""

    cv2_module, _ = require_opencv_imports()
    source_payload, _, image_a = load_image_matrix(request, input_name="image_a")
    _, _, image_b = load_image_matrix(request, input_name="image_b")
    require_same_shape(image_a, image_b)
    operation = read_choice(
        request.parameters.get("operation"),
        field_name="operation",
        choices={"add", "subtract", "multiply", "divide", "absdiff", "weighted-add"},
        default="absdiff",
    )
    if operation == "weighted-add":
        alpha = read_float(request.parameters.get("alpha"), field_name="alpha", default=0.5)
        beta = read_float(request.parameters.get("beta"), field_name="beta", default=0.5)
        gamma = read_float(request.parameters.get("gamma"), field_name="gamma", default=0.0)
        output = cv2_module.addWeighted(image_a, alpha, image_b, beta, gamma)
    else:
        output = {
            "add": cv2_module.add,
            "subtract": cv2_module.subtract,
            "multiply": cv2_module.multiply,
            "divide": cv2_module.divide,
            "absdiff": cv2_module.absdiff,
        }[operation](image_a, image_b)
    return {
        "image": build_image_output(
            request,
            source_payload=source_payload,
            image_matrix=output,
            variant_name=f"image-{operation}",
            save_location=request.parameters.get("save_location"),
        )
    }
