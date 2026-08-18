"""Brightness Contrast 节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import build_image_output, read_float
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.brightness-contrast"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按 dst = src * alpha + beta 调整亮度和对比度。"""

    _, np_module = require_opencv_imports()
    source_payload, _, image = load_image_matrix(request)
    alpha = read_float(request.parameters.get("alpha"), field_name="alpha", default=1.0, minimum=0.0)
    beta = read_float(request.parameters.get("beta"), field_name="beta", default=0.0, minimum=-255.0, maximum=255.0)
    output = np_module.clip(
        image.astype(np_module.float32) * alpha + beta,
        0,
        255,
    ).astype(np_module.uint8)
    return {
        "image": build_image_output(
            request,
            source_payload=source_payload,
            image_matrix=output,
            variant_name="brightness-contrast",
            save_location=request.parameters.get("save_location"),
        )
    }
