"""交换图像的行列轴。"""

from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.transpose"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """转置图像矩阵并输出新的图像引用。"""

    cv2, _ = require_opencv_imports()
    image_payload, _, image = load_image_matrix(request)
    return {
        "image": build_image_output(
            request,
            source_payload=image_payload,
            image_matrix=cv2.transpose(image),
            variant_name="transpose",
            output_object_key=request.parameters.get("output_object_key"),
        )
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]
