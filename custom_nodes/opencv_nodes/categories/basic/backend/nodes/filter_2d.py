"""Filter 2D 节点实现。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import build_image_output, read_float
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.filter-2d"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """使用二维自定义卷积核执行 filter2D。"""

    cv2_module, np_module = require_opencv_imports()
    source_payload, _, image = load_image_matrix(request)
    raw_kernel = request.parameters.get("kernel")
    if not isinstance(raw_kernel, list) or not raw_kernel or not all(isinstance(row, list) for row in raw_kernel):
        raise InvalidRequestError("kernel 必须是非空二维数字数组")
    row_lengths = {len(row) for row in raw_kernel}
    if len(row_lengths) != 1 or 0 in row_lengths:
        raise InvalidRequestError("kernel 的每一行长度必须一致且非空")
    try:
        kernel = np_module.asarray(raw_kernel, dtype=np_module.float32)
    except (TypeError, ValueError) as error:
        raise InvalidRequestError("kernel 必须只包含数字") from error
    delta = read_float(request.parameters.get("delta"), field_name="delta", default=0.0)
    output = cv2_module.filter2D(image, ddepth=-1, kernel=kernel, delta=delta)
    return {
        "image": build_image_output(
            request,
            source_payload=source_payload,
            image_matrix=output,
            variant_name="filter-2d",
            output_object_key=request.parameters.get("output_object_key"),
        )
    }
