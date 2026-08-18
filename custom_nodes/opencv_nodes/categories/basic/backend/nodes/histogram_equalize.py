"""Histogram Equalize 节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
    read_bool,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.histogram-equalize"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行全局直方图均衡化。"""

    cv2_module, _ = require_opencv_imports()
    source_payload, _, image = load_image_matrix(request)
    luminance_only = read_bool(
        request.parameters.get("luminance_only"),
        field_name="luminance_only",
        default=True,
    )
    if len(image.shape) == 2:
        output = cv2_module.equalizeHist(image)
    elif luminance_only:
        ycrcb = cv2_module.cvtColor(image, cv2_module.COLOR_BGR2YCrCb)
        channels = list(cv2_module.split(ycrcb))
        channels[0] = cv2_module.equalizeHist(channels[0])
        output = cv2_module.cvtColor(cv2_module.merge(channels), cv2_module.COLOR_YCrCb2BGR)
    else:
        output = cv2_module.merge([cv2_module.equalizeHist(channel) for channel in cv2_module.split(image)])
    return {
        "image": build_image_output(
            request,
            source_payload=source_payload,
            image_matrix=output,
            variant_name="histogram-equalize",
            save_location=request.parameters.get("save_location"),
        )
    }
