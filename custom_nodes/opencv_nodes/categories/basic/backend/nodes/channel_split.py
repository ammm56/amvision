"""Channel Split 节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import build_image_output
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.channel-split"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把图片拆成最多四个单通道 image-ref。"""

    cv2_module, _ = require_opencv_imports()
    source_payload, _, image = load_image_matrix(request, imdecode_flags=cv2_module.IMREAD_UNCHANGED)
    channels = cv2_module.split(image) if len(image.shape) == 3 else (image,)
    outputs: dict[str, object] = {}
    for index, channel in enumerate(channels[:4]):
        outputs[f"channel_{index}"] = build_image_output(
            request,
            source_payload=source_payload,
            image_matrix=channel,
            variant_name=f"channel-{index}",
        )
    return outputs
