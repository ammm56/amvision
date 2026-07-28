"""使用 LSD 检测亚像素直线段。"""

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    ensure_gray,
    read_float,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.line-segment-detect"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """检测线段并输出端点、长度和方向。"""

    cv2, np = require_opencv_imports()
    image_payload, source_key, image = load_image_matrix(request)
    gray = ensure_gray(image, cv2_module=cv2)
    refine_name = str(request.parameters.get("refine", "standard")).strip().lower()
    refine = {
        "none": cv2.LSD_REFINE_NONE,
        "standard": cv2.LSD_REFINE_STD,
        "advanced": cv2.LSD_REFINE_ADV,
    }.get(refine_name)
    if refine is None:
        raise InvalidRequestError("refine 仅支持 none、standard 或 advanced")
    detector = cv2.createLineSegmentDetector(
        refine,
        scale=read_float(
            request.parameters.get("scale"),
            field_name="scale",
            default=0.8,
            minimum=0.1,
            maximum=1.0,
        ),
        sigma_scale=read_float(
            request.parameters.get("sigma_scale"),
            field_name="sigma_scale",
            default=0.6,
            minimum=0.01,
        ),
    )
    detected = detector.detect(gray)
    lines = detected[0] if detected else None
    min_length = read_float(
        request.parameters.get("min_length"),
        field_name="min_length",
        default=10.0,
        minimum=0.0,
    )
    items: list[dict[str, object]] = []
    if lines is not None:
        for raw in lines.reshape(-1, 4):
            x1, y1, x2, y2 = [float(value) for value in raw]
            length = float(np.hypot(x2 - x1, y2 - y1))
            if length < min_length:
                continue
            items.append(
                {
                    "line_index": len(items) + 1,
                    "start_xy": [x1, y1],
                    "end_xy": [x2, y2],
                    "length_pixels": length,
                    "angle_deg": float(np.degrees(np.arctan2(y2 - y1, x2 - x1))),
                }
            )
    return {
        "lines": {
            "source_image": image_payload,
            "source_object_key": source_key,
            "count": len(items),
            "items": items,
        }
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]
