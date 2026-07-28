"""检测对称或非对称圆点阵并构造标定观测。"""

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    ensure_gray,
    read_bool,
    read_float,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.circle-grid-detect"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """检测圆点阵并输出完整的标定观测对象。"""

    cv2, np = require_opencv_imports()
    image_payload, _, image = load_image_matrix(request)
    gray = ensure_gray(image, cv2_module=cv2)
    columns = read_int(
        request.parameters.get("columns"),
        field_name="columns",
        default=4,
        minimum=2,
    )
    rows = read_int(
        request.parameters.get("rows"),
        field_name="rows",
        default=11,
        minimum=2,
    )
    spacing = read_float(
        request.parameters.get("spacing"),
        field_name="spacing",
        default=1.0,
        minimum=1e-9,
    )
    asymmetric = read_bool(
        request.parameters.get("asymmetric"),
        field_name="asymmetric",
        default=True,
    )
    use_clustering = read_bool(
        request.parameters.get("use_clustering"),
        field_name="use_clustering",
        default=True,
    )
    flags = cv2.CALIB_CB_ASYMMETRIC_GRID if asymmetric else cv2.CALIB_CB_SYMMETRIC_GRID
    if use_clustering:
        flags |= cv2.CALIB_CB_CLUSTERING
    found, centers = cv2.findCirclesGrid(gray, (columns, rows), flags=flags)
    if not found or centers is None:
        raise InvalidRequestError(
            "未检测到完整圆点阵",
            details={"columns": columns, "rows": rows, "asymmetric": asymmetric},
        )

    object_points = np.zeros((columns * rows, 3), dtype=np.float32)
    for row in range(rows):
        for column in range(columns):
            index = row * columns + column
            object_points[index, 0] = (
                2 * column + (row % 2 if asymmetric else 0)
            ) * spacing
            object_points[index, 1] = row * spacing
    return {
        "observation": build_value_payload(
            {
                "pattern_kind": "asymmetric-circle-grid"
                if asymmetric
                else "symmetric-circle-grid",
                "pattern_size": [columns, rows],
                "spacing": spacing,
                "image_size": [int(gray.shape[1]), int(gray.shape[0])],
                "image_points": centers.reshape(-1, 2).astype(float).tolist(),
                "object_points": object_points.astype(float).tolist(),
                "source_image": image_payload,
                "point_count": int(centers.shape[0]),
            }
        )
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]
