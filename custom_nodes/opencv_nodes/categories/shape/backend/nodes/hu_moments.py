"""Hu Moments 节点实现。"""

from __future__ import annotations

import math

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import read_bool
from custom_nodes.opencv_nodes.shared.backend.runtime.geometry import contour_points_to_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import require_contours_payload

NODE_TYPE_ID = "custom.opencv.hu-moments"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算七个 Hu 不变矩，可选输出有符号对数形式。"""

    cv2_module, np_module = require_opencv_imports()
    contours = require_contours_payload(request.input_values.get("contours"))
    log_scale = read_bool(request.parameters.get("log_scale"), field_name="log_scale", default=True)
    items: list[dict[str, object]] = []
    for contour_item in contours["items"]:
        contour = contour_points_to_matrix(points=contour_item["points"], np_module=np_module)
        hu_values = cv2_module.HuMoments(cv2_module.moments(contour)).reshape(-1)
        values = []
        for raw_value in hu_values.tolist():
            value = float(raw_value)
            if log_scale:
                value = -math.copysign(1.0, value) * math.log10(abs(value)) if value != 0 else 0.0
            values.append(round(value, 12))
        items.append({"contour_index": int(contour_item["contour_index"]), "values": values})
    return {"hu_moments": build_value_payload({"count": len(items), "log_scale": log_scale, "items": items})}
