"""把圆形或环形区域展开到线性或对数极坐标图。"""

from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
    read_bool,
    read_choice,
    read_float,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.warp-polar"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行线性或对数极坐标展开，也支持逆变换。"""

    cv2, _ = require_opencv_imports()
    image_payload, _, image = load_image_matrix(request)
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
    default_radius = min(
        center_x,
        center_y,
        float(image.shape[1]) - center_x,
        float(image.shape[0]) - center_y,
    )
    max_radius = read_float(
        request.parameters.get("max_radius"),
        field_name="max_radius",
        default=max(1.0, default_radius),
        minimum=1e-9,
    )
    output_width = read_int(
        request.parameters.get("output_width"),
        field_name="output_width",
        default=max(1, int(round(max_radius))),
        minimum=1,
    )
    output_height = read_int(
        request.parameters.get("output_height"),
        field_name="output_height",
        default=max(1, int(round(max_radius * 3.141592653589793 * 2.0))),
        minimum=1,
    )
    mode = read_choice(
        request.parameters.get("mode"),
        field_name="mode",
        choices={"linear", "log"},
        default="linear",
    )
    inverse = read_bool(
        request.parameters.get("inverse"),
        field_name="inverse",
        default=False,
    )
    flags = cv2.WARP_POLAR_LOG if mode == "log" else cv2.WARP_POLAR_LINEAR
    if inverse:
        flags |= cv2.WARP_INVERSE_MAP
    flags |= cv2.INTER_LINEAR
    result = cv2.warpPolar(
        image,
        (output_width, output_height),
        (center_x, center_y),
        max_radius,
        flags,
    )
    return {
        "image": build_image_output(
            request,
            source_payload=image_payload,
            image_matrix=result,
            variant_name="warp-polar",
            output_object_key=request.parameters.get("output_object_key"),
        )
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]
