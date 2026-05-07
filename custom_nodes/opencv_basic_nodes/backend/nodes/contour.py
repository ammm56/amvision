"""Contour 节点实现。"""

from __future__ import annotations

from backend.nodes.runtime_support import resolve_image_input
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.support import (
    normalize_contour_approximation,
    normalize_contour_retrieval_mode,
    require_dataset_path,
    require_non_negative_float,
    require_opencv_imports,
    require_positive_int,
    require_uint8_int,
)


NODE_TYPE_ID = "custom.opencv.contour"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行 contour 提取，并输出结构化 contour 集合。"""

    cv2_module, _ = require_opencv_imports()
    _, _, image_object_key = resolve_image_input(request)
    image_matrix = cv2_module.imread(str(require_dataset_path(request, image_object_key)), cv2_module.IMREAD_GRAYSCALE)
    if image_matrix is None:
        raise ServiceConfigurationError(
            "OpenCV 无法读取输入图片",
            details={"node_id": request.node_id, "object_key": image_object_key},
        )

    threshold_value = require_uint8_int(request.parameters.get("threshold", 127), field_name="threshold")
    min_area = require_non_negative_float(request.parameters.get("min_area", 0), field_name="min_area")
    max_contours_raw = request.parameters.get("max_contours")
    max_contours = require_positive_int(max_contours_raw, field_name="max_contours") if max_contours_raw is not None else None
    retrieval_mode = normalize_contour_retrieval_mode(
        request.parameters.get("retrieval_mode", "external"),
        cv2_module=cv2_module,
    )
    approximation = normalize_contour_approximation(
        request.parameters.get("approximation", "simple"),
        cv2_module=cv2_module,
    )

    _, binary_image = cv2_module.threshold(image_matrix, threshold_value, 255, cv2_module.THRESH_BINARY)
    find_contours_result = cv2_module.findContours(binary_image, retrieval_mode, approximation)
    if len(find_contours_result) == 2:
        raw_contours, _ = find_contours_result
    else:
        _, raw_contours, _ = find_contours_result

    contour_items: list[dict[str, object]] = []
    for contour in raw_contours:
        contour_area = float(cv2_module.contourArea(contour))
        if contour_area < min_area:
            continue
        point_pairs = contour.reshape(-1, 2)
        contour_points = [[int(point_x), int(point_y)] for point_x, point_y in point_pairs.tolist()]
        if len(contour_points) < 3:
            continue
        bbox_x, bbox_y, bbox_width, bbox_height = cv2_module.boundingRect(contour)
        contour_items.append(
            {
                "contour_index": len(contour_items) + 1,
                "point_count": len(contour_points),
                "bbox_xyxy": [
                    int(bbox_x),
                    int(bbox_y),
                    int(bbox_x + bbox_width),
                    int(bbox_y + bbox_height),
                ],
                "points": contour_points,
            }
        )
        if max_contours is not None and len(contour_items) >= max_contours:
            break

    return {
        "contours": {
            "items": contour_items,
            "count": len(contour_items),
            "source_object_key": image_object_key,
        }
    }