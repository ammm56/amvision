"""Gamma Correction 节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import build_image_output, read_float
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.gamma-correction"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """使用 8-bit LUT 执行 gamma 校正。"""

    cv2_module, np_module = require_opencv_imports()
    source_payload, _, image = load_image_matrix(request)
    gamma = read_float(request.parameters.get("gamma"), field_name="gamma", default=1.0, minimum=0.01)
    table = np_module.asarray(
        [round(((index / 255.0) ** gamma) * 255.0) for index in range(256)],
        dtype=np_module.uint8,
    )
    output = cv2_module.LUT(image, table)
    return {
        "image": build_image_output(
            request,
            source_payload=source_payload,
            image_matrix=output,
            variant_name="gamma-correction",
            output_object_key=request.parameters.get("output_object_key"),
        )
    }
