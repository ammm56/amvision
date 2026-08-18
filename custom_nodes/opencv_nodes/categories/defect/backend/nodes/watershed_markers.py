"""使用显式 marker label 图执行 watershed。"""

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
    ensure_bgr,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.watershed-markers"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按 marker 标签执行 watershed 并输出区域和边界。"""

    cv2, np = require_opencv_imports()
    image_payload, _, image = load_image_matrix(request)
    _, _, marker_image = load_image_matrix(
        request,
        input_name="markers",
        imdecode_flags=cv2.IMREAD_GRAYSCALE,
    )
    if marker_image.shape[:2] != image.shape[:2]:
        raise InvalidRequestError("markers 与 image 尺寸必须一致")
    markers = marker_image.astype(np.int32)
    labels = cv2.watershed(
        ensure_bgr(image, cv2_module=cv2).copy(),
        markers,
    )
    boundary = np.where(labels == -1, 255, 0).astype(np.uint8)
    foreground = np.where(labels > 1, 255, 0).astype(np.uint8)
    region_labels = [int(value) for value in np.unique(labels) if int(value) > 1]
    return {
        "mask": build_image_output(
            request,
            source_payload=image_payload,
            image_matrix=foreground,
            variant_name="watershed-markers-mask",
            save_location=request.parameters.get("save_location"),
        ),
        "boundary": build_image_output(
            request,
            source_payload=image_payload,
            image_matrix=boundary,
            variant_name="watershed-markers-boundary",
        ),
        "summary": build_value_payload(
            {
                "region_count": len(region_labels),
                "labels": region_labels,
                "boundary_pixel_count": int(np.count_nonzero(boundary)),
            }
        ),
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]
