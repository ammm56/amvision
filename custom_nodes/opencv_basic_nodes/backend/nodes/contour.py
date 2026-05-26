"""Contour 节点实现。"""

from __future__ import annotations

from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_basic_nodes.backend.support import (
    load_image_matrix,
    normalize_contour_approximation,
    normalize_contour_retrieval_mode,
    require_non_negative_float,
    require_opencv_imports,
    require_positive_int,
    require_uint8_int,
)


NODE_TYPE_ID = "custom.opencv.contour"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对输入图片执行 contour 提取，并输出结构化 contour 集合。"""

    cv2_module, _ = require_opencv_imports()
    image_payload, image_object_key, image_matrix = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )

    raw_threshold = request.parameters.get("threshold")
    threshold_value = 127 if raw_threshold in {None, ""} else require_uint8_int(raw_threshold, field_name="threshold")
    raw_min_area = request.parameters.get("min_area")
    min_area = 0 if raw_min_area in {None, ""} else require_non_negative_float(raw_min_area, field_name="min_area")
    max_contours_raw = request.parameters.get("max_contours")
    if max_contours_raw == "":
        max_contours_raw = None
    max_contours = require_positive_int(max_contours_raw, field_name="max_contours") if max_contours_raw is not None else None
    raw_retrieval_mode = request.parameters.get("retrieval_mode")
    retrieval_mode = normalize_contour_retrieval_mode(
        "external" if raw_retrieval_mode in {None, ""} else raw_retrieval_mode,
        cv2_module=cv2_module,
    )
    raw_approximation = request.parameters.get("approximation")
    approximation = normalize_contour_approximation(
        "simple" if raw_approximation in {None, ""} else raw_approximation,
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
            "source_image": dict(image_payload),
            **({"source_object_key": image_object_key} if image_object_key is not None else {}),
        }
    }