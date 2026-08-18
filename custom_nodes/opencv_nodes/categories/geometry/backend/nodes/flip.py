"""水平、垂直或双轴翻转图片。"""

from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
    read_choice,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.flip"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按 direction 参数调用 OpenCV flip。"""

    cv2, _ = require_opencv_imports()
    image_payload, _, image = load_image_matrix(request)
    direction = read_choice(
        request.parameters.get("direction"),
        field_name="direction",
        choices={"horizontal", "vertical", "both"},
        default="horizontal",
    )
    code = {"horizontal": 1, "vertical": 0, "both": -1}[direction]
    return {
        "image": build_image_output(
            request,
            source_payload=image_payload,
            image_matrix=cv2.flip(image, code),
            variant_name=f"flip-{direction}",
            save_location=request.parameters.get("save_location"),
        )
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]
