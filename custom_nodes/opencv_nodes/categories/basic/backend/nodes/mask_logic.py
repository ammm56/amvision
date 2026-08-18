"""Mask Logic 节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
    ensure_gray,
    read_choice,
    require_same_shape,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.mask-logic"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对一个或两个 mask 执行布尔运算。"""

    cv2_module, _ = require_opencv_imports()
    source_payload, _, mask_a = load_image_matrix(request, input_name="mask_a")
    mask_a = ensure_gray(mask_a, cv2_module=cv2_module)
    operation = read_choice(
        request.parameters.get("operation"),
        field_name="operation",
        choices={"and", "or", "xor", "not"},
        default="and",
    )
    if operation == "not":
        output = cv2_module.bitwise_not(mask_a)
    else:
        _, _, mask_b = load_image_matrix(request, input_name="mask_b")
        mask_b = ensure_gray(mask_b, cv2_module=cv2_module)
        require_same_shape(mask_a, mask_b, field_name="masks")
        output = {
            "and": cv2_module.bitwise_and,
            "or": cv2_module.bitwise_or,
            "xor": cv2_module.bitwise_xor,
        }[operation](mask_a, mask_b)
    return {
        "mask": build_image_output(
            request,
            source_payload=source_payload,
            image_matrix=output,
            variant_name=f"mask-{operation}",
            save_location=request.parameters.get("save_location"),
        )
    }
