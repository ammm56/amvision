"""计算区域 A 减区域 B。"""

from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.binary_region_runtime import (
    build_mask_result,
    load_binary_image,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    require_same_shape,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.region-difference"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """保留 region_a 中不属于 region_b 的像素。"""

    cv2, np = require_opencv_imports()
    payload_a, mask_a = load_binary_image(
        request,
        cv2_module=cv2,
        np_module=np,
        input_name="region_a",
    )
    _, mask_b = load_binary_image(
        request,
        cv2_module=cv2,
        np_module=np,
        input_name="region_b",
    )
    require_same_shape(mask_a, mask_b, field_name="regions")
    result = cv2.bitwise_and(mask_a, cv2.bitwise_not(mask_b))
    return build_mask_result(
        request,
        source_payload=payload_a,
        mask=result,
        variant_name="region-difference",
        summary={"operation": "difference"},
    )


__all__ = ["NODE_TYPE_ID", "handle_node"]
