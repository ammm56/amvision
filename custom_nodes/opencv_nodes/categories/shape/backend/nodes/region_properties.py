"""Region Properties 节点实现。"""

from __future__ import annotations

import math

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import json_number
from custom_nodes.opencv_nodes.shared.backend.runtime.geometry import contour_points_to_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import require_contours_payload

NODE_TYPE_ID = "custom.opencv.region-properties"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算轮廓的通用工业区域特征。"""

    cv2_module, np_module = require_opencv_imports()
    contours = require_contours_payload(request.input_values.get("contours"))
    items: list[dict[str, object]] = []
    for contour_item in contours["items"]:
        contour = contour_points_to_matrix(points=contour_item["points"], np_module=np_module)
        area = float(cv2_module.contourArea(contour))
        perimeter = float(cv2_module.arcLength(contour, True))
        moments = cv2_module.moments(contour)
        center_x = float(moments["m10"] / moments["m00"]) if moments["m00"] else 0.0
        center_y = float(moments["m01"] / moments["m00"]) if moments["m00"] else 0.0
        x, y, width, height = cv2_module.boundingRect(contour)
        hull = cv2_module.convexHull(contour)
        hull_area = float(cv2_module.contourArea(hull))
        rotated_rect = cv2_module.minAreaRect(contour)
        rect_width, rect_height = [float(value) for value in rotated_rect[1]]
        major_axis = max(rect_width, rect_height)
        minor_axis = min(rect_width, rect_height)
        orientation_deg = float(rotated_rect[2])
        if rect_width < rect_height:
            orientation_deg += 90.0
        circularity = 4.0 * math.pi * area / (perimeter * perimeter) if perimeter > 0 else 0.0
        items.append(
            {
                "contour_index": int(contour_item["contour_index"]),
                "area": json_number(area),
                "perimeter": json_number(perimeter),
                "centroid_xy": [json_number(center_x), json_number(center_y)],
                "bbox_xywh": [int(x), int(y), int(width), int(height)],
                "orientation_deg": json_number(orientation_deg),
                "major_axis": json_number(major_axis),
                "minor_axis": json_number(minor_axis),
                "aspect_ratio": json_number(major_axis / minor_axis if minor_axis > 0 else 0.0),
                "eccentricity": json_number(
                    math.sqrt(max(0.0, 1.0 - (minor_axis * minor_axis) / (major_axis * major_axis)))
                    if major_axis > 0
                    else 0.0
                ),
                "circularity": json_number(circularity),
                "solidity": json_number(area / hull_area if hull_area > 0 else 0.0),
                "extent": json_number(area / float(width * height) if width > 0 and height > 0 else 0.0),
                "convex": bool(cv2_module.isContourConvex(contour)),
            }
        )
    return {"properties": build_value_payload({"count": len(items), "items": items})}
