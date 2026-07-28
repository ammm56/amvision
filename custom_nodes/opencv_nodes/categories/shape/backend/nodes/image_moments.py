"""Image Moments 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import json_number
from custom_nodes.opencv_nodes.shared.backend.runtime.geometry import contour_points_to_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import require_contours_payload

NODE_TYPE_ID = "custom.opencv.image-moments"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算每个轮廓的空间矩、中心矩和归一化中心矩。"""

    cv2_module, np_module = require_opencv_imports()
    contours = require_contours_payload(request.input_values.get("contours"))
    items: list[dict[str, object]] = []
    for contour_item in contours["items"]:
        contour = contour_points_to_matrix(points=contour_item["points"], np_module=np_module)
        moments = cv2_module.moments(contour)
        centroid = [
            json_number(moments["m10"] / moments["m00"]),
            json_number(moments["m01"] / moments["m00"]),
        ] if moments["m00"] else None
        items.append(
            {
                "contour_index": int(contour_item["contour_index"]),
                "centroid_xy": centroid,
                "moments": {name: json_number(value, digits=12) for name, value in moments.items()},
            }
        )
    return {"moments": build_value_payload({"count": len(items), "items": items})}
