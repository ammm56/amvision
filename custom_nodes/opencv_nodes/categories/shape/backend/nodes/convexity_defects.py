"""Convexity Defects 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import json_number
from custom_nodes.opencv_nodes.shared.backend.runtime.geometry import contour_points_to_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import require_contours_payload

NODE_TYPE_ID = "custom.opencv.convexity-defects"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算轮廓相对凸包的凹陷缺陷。"""

    cv2_module, np_module = require_opencv_imports()
    contours = require_contours_payload(request.input_values.get("contours"))
    result_items: list[dict[str, object]] = []
    for contour_item in contours["items"]:
        contour = contour_points_to_matrix(points=contour_item["points"], np_module=np_module)
        hull_indices = cv2_module.convexHull(contour, returnPoints=False)
        raw_defects = cv2_module.convexityDefects(contour, hull_indices) if hull_indices is not None and len(hull_indices) >= 3 else None
        defects: list[dict[str, object]] = []
        if raw_defects is not None:
            for defect_index, raw_defect in enumerate(raw_defects.reshape(-1, 4).tolist(), start=1):
                start_index, end_index, far_index, fixed_depth = [int(value) for value in raw_defect]
                defects.append(
                    {
                        "defect_index": defect_index,
                        "start_xy": [int(value) for value in contour[start_index, 0].tolist()],
                        "end_xy": [int(value) for value in contour[end_index, 0].tolist()],
                        "far_xy": [int(value) for value in contour[far_index, 0].tolist()],
                        "depth_pixels": json_number(fixed_depth / 256.0),
                    }
                )
        result_items.append(
            {
                "contour_index": int(contour_item["contour_index"]),
                "defect_count": len(defects),
                "items": defects,
            }
        )
    return {"defects": build_value_payload({"count": len(result_items), "items": result_items})}
