"""基于矩形或可选初始 mask 执行 GrabCut 前景分割。"""

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    build_image_output,
    ensure_bgr,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.grabcut"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """执行 GrabCut 并输出前景图、二值 mask 和统计信息。"""

    cv2, np = require_opencv_imports()
    image_payload, _, image = load_image_matrix(request)
    bgr = ensure_bgr(image, cv2_module=cv2)
    height, width = bgr.shape[:2]
    x = read_int(
        request.parameters.get("x"),
        field_name="x",
        default=max(0, width // 10),
        minimum=0,
        maximum=width - 1,
    )
    y = read_int(
        request.parameters.get("y"),
        field_name="y",
        default=max(0, height // 10),
        minimum=0,
        maximum=height - 1,
    )
    rect_width = read_int(
        request.parameters.get("width"),
        field_name="width",
        default=max(1, width - 2 * x),
        minimum=1,
    )
    rect_height = read_int(
        request.parameters.get("height"),
        field_name="height",
        default=max(1, height - 2 * y),
        minimum=1,
    )
    rect_width = min(rect_width, width - x)
    rect_height = min(rect_height, height - y)
    iterations = read_int(
        request.parameters.get("iterations"),
        field_name="iterations",
        default=5,
        minimum=1,
    )
    mask = np.zeros((height, width), dtype=np.uint8)
    mode = cv2.GC_INIT_WITH_RECT
    if request.input_values.get("mask") is not None:
        _, _, initial = load_image_matrix(
            request,
            input_name="mask",
            imdecode_flags=cv2.IMREAD_GRAYSCALE,
        )
        if initial.shape != mask.shape:
            raise InvalidRequestError("grabcut 的 mask 与 image 尺寸必须一致")
        mask[initial == 0] = cv2.GC_BGD
        mask[initial > 0] = cv2.GC_PR_FGD
        mode = cv2.GC_INIT_WITH_MASK
    background = np.zeros((1, 65), dtype=np.float64)
    foreground = np.zeros((1, 65), dtype=np.float64)
    cv2.grabCut(
        bgr,
        mask,
        (x, y, rect_width, rect_height),
        background,
        foreground,
        iterations,
        mode,
    )
    binary = np.where(
        (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD),
        255,
        0,
    ).astype(np.uint8)
    segmented = cv2.bitwise_and(bgr, bgr, mask=binary)
    return {
        "image": build_image_output(
            request,
            source_payload=image_payload,
            image_matrix=segmented,
            variant_name="grabcut-image",
            save_location=request.parameters.get("save_location"),
        ),
        "mask": build_image_output(
            request,
            source_payload=image_payload,
            image_matrix=binary,
            variant_name="grabcut-mask",
        ),
        "summary": build_value_payload(
            {
                "foreground_pixel_count": int(np.count_nonzero(binary)),
                "bbox_xywh": [x, y, rect_width, rect_height],
                "iterations": iterations,
                "initialization": "mask" if mode == cv2.GC_INIT_WITH_MASK else "rect",
            }
        ),
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]
