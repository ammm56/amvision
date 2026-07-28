"""对已有二维角点执行亚像素细化。"""

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    ensure_gray,
    read_float,
    read_int,
    read_points,
    require_value_input,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.corner-subpix"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """细化输入角点，并保留输入观测对象中的其他元数据。"""

    cv2, np = require_opencv_imports()
    _, _, image = load_image_matrix(request)
    gray = ensure_gray(image, cv2_module=cv2)
    value = require_value_input(request, input_name="points")
    source = dict(value) if isinstance(value, dict) else {"image_points": value}
    points = read_points(
        source.get("image_points"),
        field_name="image_points",
        minimum_count=1,
    )
    window_size = read_int(
        request.parameters.get("window_size"),
        field_name="window_size",
        default=5,
        minimum=1,
    )
    zero_zone = read_int(
        request.parameters.get("zero_zone"),
        field_name="zero_zone",
        default=-1,
        minimum=-1,
    )
    max_iterations = read_int(
        request.parameters.get("max_iterations"),
        field_name="max_iterations",
        default=30,
        minimum=1,
    )
    epsilon = read_float(
        request.parameters.get("epsilon"),
        field_name="epsilon",
        default=0.01,
        minimum=1e-9,
    )
    matrix = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
    refined = cv2.cornerSubPix(
        gray,
        matrix,
        (window_size, window_size),
        (zero_zone, zero_zone),
        (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, max_iterations, epsilon),
    )
    source["image_points"] = refined.reshape(-1, 2).astype(float).tolist()
    source["point_count"] = len(points)
    source["subpixel_refined"] = True
    source["subpixel_window_size"] = window_size
    return {"points": build_value_payload(source)}


__all__ = ["NODE_TYPE_ID", "handle_node"]
