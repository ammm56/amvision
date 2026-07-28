"""Phase Correlation 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import ensure_gray, read_bool
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.phase-correlation"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """使用相位相关计算两张同尺寸图片的亚像素平移。"""

    cv2_module, np_module = require_opencv_imports()
    _, _, reference = load_image_matrix(request, input_name="reference_image")
    _, _, moving = load_image_matrix(request, input_name="moving_image")
    reference_gray = ensure_gray(reference, cv2_module=cv2_module)
    moving_gray = ensure_gray(moving, cv2_module=cv2_module)
    if reference_gray.shape != moving_gray.shape:
        raise InvalidRequestError("phase-correlation 的两张图片尺寸必须一致")
    reference_float = reference_gray.astype(np_module.float32)
    moving_float = moving_gray.astype(np_module.float32)
    window = None
    if read_bool(request.parameters.get("use_hanning_window"), field_name="use_hanning_window", default=True):
        window = cv2_module.createHanningWindow(
            (int(reference_gray.shape[1]), int(reference_gray.shape[0])),
            cv2_module.CV_32F,
        )
    shift_xy, response = cv2_module.phaseCorrelate(reference_float, moving_float, window)
    return {
        "transform": build_value_payload(
            {
                "transform_kind": "translation",
                "shift_xy": [float(shift_xy[0]), float(shift_xy[1])],
                "response": float(response),
                "matrix_3x3": [
                    [1.0, 0.0, float(shift_xy[0])],
                    [0.0, 1.0, float(shift_xy[1])],
                    [0.0, 0.0, 1.0],
                ],
            }
        )
    }
