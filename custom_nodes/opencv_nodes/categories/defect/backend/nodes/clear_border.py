"""删除与图像边界相接的二值连通域。"""

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

NODE_TYPE_ID = "custom.opencv.clear-border"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """定位并清除所有接触四边的连通域。"""

    cv2, np = require_opencv_imports()
    image_payload, binary = load_binary_image(
        request,
        cv2_module=cv2,
        np_module=np,
    )
    count, labels = cv2.connectedComponents(binary, connectivity=8)
    border_labels = set(
        int(value)
        for value in np.unique(
            np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
        )
    )
    result = binary.copy()
    for label in border_labels:
        if label > 0:
            result[labels == label] = 0
    return build_mask_result(
        request,
        source_payload=image_payload,
        mask=result,
        variant_name="clear-border",
        summary={
            "removed_component_count": len(border_labels - {0}),
            "component_count": max(0, count - 1),
        },
    )


__all__ = ["NODE_TYPE_ID", "handle_node"]
