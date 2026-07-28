"""围绕浮点中心提取可越界的亚像素矩形 patch。"""

from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
    read_float,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.get-rect-subpix"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按浮点中心和目标尺寸提取亚像素 patch。"""

    cv2, _ = require_opencv_imports()
    image_payload, _, image = load_image_matrix(request)
    width = read_int(
        request.parameters.get("width"),
        field_name="width",
        default=64,
        minimum=1,
    )
    height = read_int(
        request.parameters.get("height"),
        field_name="height",
        default=64,
        minimum=1,
    )
    center_x = read_float(
        request.parameters.get("center_x"),
        field_name="center_x",
        default=(float(image.shape[1]) - 1.0) / 2.0,
    )
    center_y = read_float(
        request.parameters.get("center_y"),
        field_name="center_y",
        default=(float(image.shape[0]) - 1.0) / 2.0,
    )
    patch = cv2.getRectSubPix(image, (width, height), (center_x, center_y))
    return {
        "image": build_image_output(
            request,
            source_payload=image_payload,
            image_matrix=patch,
            variant_name="get-rect-subpix",
            output_object_key=request.parameters.get("output_object_key"),
        )
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]
