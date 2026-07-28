"""Box Blur 节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import build_image_output, read_bool, read_int
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.box-blur"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行归一化或非归一化方框滤波。"""

    cv2_module, _ = require_opencv_imports()
    source_payload, _, image = load_image_matrix(request)
    kernel_width = read_int(request.parameters.get("kernel_width"), field_name="kernel_width", default=3, minimum=1)
    kernel_height = read_int(request.parameters.get("kernel_height"), field_name="kernel_height", default=3, minimum=1)
    normalize = read_bool(request.parameters.get("normalize"), field_name="normalize", default=True)
    output = cv2_module.boxFilter(
        image,
        ddepth=-1,
        ksize=(kernel_width, kernel_height),
        normalize=normalize,
    )
    return {
        "image": build_image_output(
            request,
            source_payload=source_payload,
            image_matrix=output,
            variant_name="box-blur",
            output_object_key=request.parameters.get("output_object_key"),
        )
    }
