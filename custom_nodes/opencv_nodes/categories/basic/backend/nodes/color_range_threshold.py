"""Color Range Threshold 节点实现。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
    read_bool,
    read_choice,
    read_number_list,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.color-range-threshold"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按颜色空间各通道上下界生成二值 mask。"""

    cv2_module, np_module = require_opencv_imports()
    source_payload, _, image = load_image_matrix(request)
    color_space = read_choice(
        request.parameters.get("color_space"),
        field_name="color_space",
        choices={"bgr", "hsv", "hls", "lab", "ycrcb", "gray"},
        default="hsv",
    )
    converted = image
    if color_space == "gray":
        converted = cv2_module.cvtColor(image, cv2_module.COLOR_BGR2GRAY)
    elif color_space != "bgr":
        conversion_name = {
            "hsv": "COLOR_BGR2HSV",
            "hls": "COLOR_BGR2HLS",
            "lab": "COLOR_BGR2LAB",
            "ycrcb": "COLOR_BGR2YCrCb",
        }[color_space]
        converted = cv2_module.cvtColor(image, getattr(cv2_module, conversion_name))
    channel_count = 1 if len(converted.shape) == 2 else int(converted.shape[2])
    lower = _read_bounds(
        request.parameters.get("lower"),
        field_name="lower",
        channel_count=channel_count,
        default=[0.0] * channel_count,
    )
    upper = _read_bounds(
        request.parameters.get("upper"),
        field_name="upper",
        channel_count=channel_count,
        default=[255.0] * channel_count,
    )
    if any(low > high for low, high in zip(lower, upper, strict=True)):
        raise InvalidRequestError("lower 的每个通道值都不能大于 upper")
    mask = cv2_module.inRange(
        converted,
        np_module.asarray(lower if channel_count > 1 else lower[0], dtype=np_module.uint8),
        np_module.asarray(upper if channel_count > 1 else upper[0], dtype=np_module.uint8),
    )
    if read_bool(request.parameters.get("invert"), field_name="invert", default=False):
        mask = cv2_module.bitwise_not(mask)
    return {
        "mask": build_image_output(
            request,
            source_payload=source_payload,
            image_matrix=mask,
            variant_name="color-range-mask",
            output_object_key=request.parameters.get("output_object_key"),
        )
    }


def _read_bounds(
    value: object,
    *,
    field_name: str,
    channel_count: int,
    default: list[float],
) -> list[float]:
    """读取颜色范围边界；灰度模式兼容界面保留的三通道默认值。"""

    if value is None or value == "":
        return default
    values = read_number_list(value, field_name=field_name)
    if channel_count == 1 and len(values) >= 1:
        return [values[0]]
    if len(values) != channel_count:
        raise InvalidRequestError(f"{field_name} 必须包含 {channel_count} 个通道值")
    return values
