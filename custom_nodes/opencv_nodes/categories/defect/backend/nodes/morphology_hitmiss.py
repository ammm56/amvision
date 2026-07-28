"""使用包含 -1/0/1 的结构元素执行 MORPH_HITMISS。"""

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.binary_region_runtime import (
    build_mask_result,
    load_binary_image,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.morphology-hitmiss"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行二值形态学 hit-or-miss 模式匹配。"""

    cv2, np = require_opencv_imports()
    image_payload, binary = load_binary_image(
        request,
        cv2_module=cv2,
        np_module=np,
    )
    kernel_value = request.parameters.get(
        "kernel",
        [[-1, -1, -1], [0, 1, 0], [1, 1, 1]],
    )
    if (
        not isinstance(kernel_value, list)
        or not kernel_value
        or not all(isinstance(row, list) for row in kernel_value)
    ):
        raise InvalidRequestError("kernel 必须是非空二维数组")
    width = len(kernel_value[0])
    if width < 1 or any(len(row) != width for row in kernel_value):
        raise InvalidRequestError("kernel 的每一行长度必须一致")
    kernel = np.asarray(kernel_value, dtype=np.int8)
    if not set(int(value) for value in np.unique(kernel)).issubset({-1, 0, 1}):
        raise InvalidRequestError("kernel 只能包含 -1、0、1")
    result = cv2.morphologyEx(
        (binary > 0).astype(np.uint8),
        cv2.MORPH_HITMISS,
        kernel,
    )
    result = np.where(result > 0, 255, 0).astype(np.uint8)
    return build_mask_result(
        request,
        source_payload=image_payload,
        mask=result,
        variant_name="morphology-hitmiss",
        summary={
            "match_pixel_count": int(np.count_nonzero(result)),
            "kernel_shape": list(kernel.shape),
        },
    )


__all__ = ["NODE_TYPE_ID", "handle_node"]
