"""删除面积低于阈值的二值连通域。"""

from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.defect.backend.nodes.binary_region_runtime import (
    build_mask_result,
    load_binary_image,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.remove-small-components"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按连通域面积过滤二值图。"""

    cv2, np = require_opencv_imports()
    image_payload, binary = load_binary_image(
        request,
        cv2_module=cv2,
        np_module=np,
    )
    min_area = read_int(
        request.parameters.get("min_area"),
        field_name="min_area",
        default=16,
        minimum=1,
    )
    connectivity = read_int(
        request.parameters.get("connectivity"),
        field_name="connectivity",
        default=8,
        minimum=4,
        maximum=8,
    )
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary,
        connectivity=connectivity,
    )
    result = np.zeros_like(binary)
    kept = 0
    removed = 0
    for label in range(1, count):
        if int(stats[label, cv2.CC_STAT_AREA]) >= min_area:
            result[labels == label] = 255
            kept += 1
        else:
            removed += 1
    return build_mask_result(
        request,
        source_payload=image_payload,
        mask=result,
        variant_name="remove-small-components",
        summary={
            "kept_component_count": kept,
            "removed_component_count": removed,
            "min_area": min_area,
        },
    )


__all__ = ["NODE_TYPE_ID", "handle_node"]
