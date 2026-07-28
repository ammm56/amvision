"""Point Polygon Test 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import read_bool, read_int, read_points
from custom_nodes.opencv_nodes.shared.backend.runtime.geometry import contour_points_to_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import require_contours_payload

NODE_TYPE_ID = "custom.opencv.point-polygon-test"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """判断一个或多个点位于轮廓内部、边界还是外部。"""

    cv2_module, np_module = require_opencv_imports()
    contours = require_contours_payload(request.input_values.get("contours"))
    contour_index = read_int(request.parameters.get("contour_index"), field_name="contour_index", default=1, minimum=1)
    contour_item = next(
        (item for item in contours["items"] if int(item["contour_index"]) == contour_index),
        None,
    )
    if contour_item is None:
        raise InvalidRequestError("指定 contour_index 不存在")
    raw_points = request.parameters.get("points_xy")
    if raw_points is None or raw_points == "":
        single_point = request.parameters.get("point_xy")
        raw_points = [single_point]
    points = read_points(raw_points, field_name="points_xy", minimum_count=1)
    measure_distance = read_bool(
        request.parameters.get("measure_distance"),
        field_name="measure_distance",
        default=True,
    )
    contour = contour_points_to_matrix(points=contour_item["points"], np_module=np_module)
    items = []
    for point in points:
        result = float(cv2_module.pointPolygonTest(contour, (point[0], point[1]), measure_distance))
        items.append(
            {
                "point_xy": point,
                "signed_distance": result if measure_distance else None,
                "relation": "inside" if result > 0 else "boundary" if result == 0 else "outside",
            }
        )
    return {
        "result": build_value_payload(
            {
                "contour_index": contour_index,
                "measure_distance": measure_distance,
                "count": len(items),
                "items": items,
            }
        )
    }
