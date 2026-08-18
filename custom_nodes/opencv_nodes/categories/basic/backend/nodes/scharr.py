"""Scharr 节点实现。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import build_image_output, ensure_gray, read_float
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.scharr"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算 Scharr x、y 或梯度幅值。"""

    cv2_module, _ = require_opencv_imports()
    source_payload, _, image = load_image_matrix(request)
    gray = ensure_gray(image, cv2_module=cv2_module)
    direction = str(request.parameters.get("direction") or "magnitude").strip().lower()
    if direction not in {"x", "y", "magnitude"}:
        raise InvalidRequestError("direction 仅支持 x、y 或 magnitude")
    scale = read_float(request.parameters.get("scale"), field_name="scale", default=1.0)
    delta = read_float(request.parameters.get("delta"), field_name="delta", default=0.0)
    gradient_x = cv2_module.Scharr(gray, cv2_module.CV_32F, 1, 0, scale=scale, delta=delta)
    gradient_y = cv2_module.Scharr(gray, cv2_module.CV_32F, 0, 1, scale=scale, delta=delta)
    if direction == "x":
        output = cv2_module.convertScaleAbs(gradient_x)
    elif direction == "y":
        output = cv2_module.convertScaleAbs(gradient_y)
    else:
        output = cv2_module.convertScaleAbs(cv2_module.magnitude(gradient_x, gradient_y))
    return {
        "image": build_image_output(
            request,
            source_payload=source_payload,
            image_matrix=output,
            variant_name=f"scharr-{direction}",
            save_location=request.parameters.get("save_location"),
        )
    }
