"""Channel Merge 节点实现。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
    ensure_gray,
    require_same_shape,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.channel-merge"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把三个或四个单通道输入合并为图片。"""

    cv2_module, _ = require_opencv_imports()
    source_payload, _, channel_0 = load_image_matrix(request, input_name="channel_0")
    _, _, channel_1 = load_image_matrix(request, input_name="channel_1")
    _, _, channel_2 = load_image_matrix(request, input_name="channel_2")
    channels = [
        ensure_gray(channel_0, cv2_module=cv2_module),
        ensure_gray(channel_1, cv2_module=cv2_module),
        ensure_gray(channel_2, cv2_module=cv2_module),
    ]
    if request.input_values.get("channel_3") is not None:
        _, _, channel_3 = load_image_matrix(request, input_name="channel_3")
        channels.append(ensure_gray(channel_3, cv2_module=cv2_module))
    require_same_shape(*channels, field_name="channels")
    if len(channels) not in {3, 4}:
        raise InvalidRequestError("channel-merge 仅支持合并三个或四个通道")
    output = cv2_module.merge(channels)
    return {
        "image": build_image_output(
            request,
            source_payload=source_payload,
            image_matrix=output,
            variant_name="channel-merge",
            save_location=request.parameters.get("save_location"),
        )
    }
