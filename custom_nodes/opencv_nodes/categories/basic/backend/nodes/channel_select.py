"""Channel Select 节点实现。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import build_image_output, read_int
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.channel-select"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按零起始通道序号提取单通道图片。"""

    cv2_module, _ = require_opencv_imports()
    source_payload, _, image = load_image_matrix(request, imdecode_flags=cv2_module.IMREAD_UNCHANGED)
    channels = cv2_module.split(image) if len(image.shape) == 3 else (image,)
    channel_index = read_int(
        request.parameters.get("channel_index"),
        field_name="channel_index",
        default=0,
        minimum=0,
        maximum=3,
    )
    if channel_index >= len(channels):
        raise InvalidRequestError(
            "channel_index 超出输入图片通道数",
            details={"channel_index": channel_index, "channel_count": len(channels)},
        )
    return {
        "image": build_image_output(
            request,
            source_payload=source_payload,
            image_matrix=channels[channel_index],
            variant_name=f"channel-{channel_index}",
            output_object_key=request.parameters.get("output_object_key"),
        )
    }
