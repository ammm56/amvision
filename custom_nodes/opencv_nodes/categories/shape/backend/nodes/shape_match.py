"""Shape Match 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import read_choice, read_int
from custom_nodes.opencv_nodes.shared.backend.runtime.geometry import contour_points_to_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import require_contours_payload

NODE_TYPE_ID = "custom.opencv.shape-match"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """使用 Hu 矩比较两个 contour 集合中的指定轮廓。"""

    cv2_module, np_module = require_opencv_imports()
    contours_a = require_contours_payload(request.input_values.get("contours_a"))
    contours_b = require_contours_payload(request.input_values.get("contours_b"))
    index_a = read_int(request.parameters.get("contour_index_a"), field_name="contour_index_a", default=1, minimum=1)
    index_b = read_int(request.parameters.get("contour_index_b"), field_name="contour_index_b", default=1, minimum=1)
    item_a = _find_contour(contours_a["items"], index_a)
    item_b = _find_contour(contours_b["items"], index_b)
    method_name = read_choice(
        request.parameters.get("method"),
        field_name="method",
        choices={"i1", "i2", "i3"},
        default="i1",
    )
    method = {
        "i1": cv2_module.CONTOURS_MATCH_I1,
        "i2": cv2_module.CONTOURS_MATCH_I2,
        "i3": cv2_module.CONTOURS_MATCH_I3,
    }[method_name]
    contour_a = contour_points_to_matrix(points=item_a["points"], np_module=np_module)
    contour_b = contour_points_to_matrix(points=item_b["points"], np_module=np_module)
    score = float(cv2_module.matchShapes(contour_a, contour_b, method, 0.0))
    return {
        "score": build_value_payload(score),
        "summary": build_value_payload(
            {
                "method": method_name,
                "contour_index_a": index_a,
                "contour_index_b": index_b,
                "score": score,
                "lower_is_better": True,
            }
        ),
    }


def _find_contour(items: list[dict[str, object]], contour_index: int) -> dict[str, object]:
    """按 contour_index 查找轮廓。"""

    for item in items:
        if int(item["contour_index"]) == contour_index:
            return item
    raise InvalidRequestError("指定 contour_index 不存在", details={"contour_index": contour_index})
