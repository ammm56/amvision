"""按指定边界策略扩展图像画布。"""

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
    read_choice,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.pad-border"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行 copyMakeBorder 并校验边界宽度和值。"""

    cv2, _ = require_opencv_imports()
    image_payload, _, image = load_image_matrix(request)
    top = read_int(
        request.parameters.get("top"),
        field_name="top",
        default=0,
        minimum=0,
    )
    bottom = read_int(
        request.parameters.get("bottom"),
        field_name="bottom",
        default=0,
        minimum=0,
    )
    left = read_int(
        request.parameters.get("left"),
        field_name="left",
        default=0,
        minimum=0,
    )
    right = read_int(
        request.parameters.get("right"),
        field_name="right",
        default=0,
        minimum=0,
    )
    mode = read_choice(
        request.parameters.get("border_mode"),
        field_name="border_mode",
        choices={"constant", "replicate", "reflect", "reflect101", "wrap"},
        default="constant",
    )
    border_type = {
        "constant": cv2.BORDER_CONSTANT,
        "replicate": cv2.BORDER_REPLICATE,
        "reflect": cv2.BORDER_REFLECT,
        "reflect101": cv2.BORDER_REFLECT_101,
        "wrap": cv2.BORDER_WRAP,
    }[mode]
    raw_value = request.parameters.get("border_value", [0, 0, 0])
    if isinstance(raw_value, (int, float)):
        border_value = float(raw_value)
    elif (
        isinstance(raw_value, list)
        and 1 <= len(raw_value) <= 4
        and all(
            isinstance(item, (int, float)) and not isinstance(item, bool)
            for item in raw_value
        )
    ):
        border_value = tuple(float(item) for item in raw_value)
    else:
        raise InvalidRequestError("border_value 必须是数字或包含 1 到 4 个数字的数组")
    result = cv2.copyMakeBorder(
        image,
        top,
        bottom,
        left,
        right,
        border_type,
        value=border_value,
    )
    return {
        "image": build_image_output(
            request,
            source_payload=image_payload,
            image_matrix=result,
            variant_name="pad-border",
            output_object_key=request.parameters.get("output_object_key"),
        )
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]
