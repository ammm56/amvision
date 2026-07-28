"""依据针孔或 fisheye 标定参数矫正二维点。"""

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.calibration_runtime import (
    parse_camera_model,
    require_object_input,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    read_bool,
    read_points,
    require_value_input,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.undistort-points"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """矫正二维点，并按参数选择像素坐标或归一化坐标。"""

    cv2, np = require_opencv_imports()
    points_value = require_value_input(request, input_name="points")
    calibration = require_object_input(request, "calibration")
    raw_points = (
        points_value.get("image_points")
        if isinstance(points_value, dict)
        else points_value
    )
    points = np.asarray(
        read_points(raw_points, field_name="image_points", minimum_count=1),
        dtype=np.float64,
    ).reshape(-1, 1, 2)
    camera_matrix, distortion = parse_camera_model(
        calibration,
        np_module=np,
    )
    normalize = read_bool(
        request.parameters.get("normalize"),
        field_name="normalize",
        default=False,
    )
    projection = None if normalize else camera_matrix
    if str(calibration.get("model", "pinhole")) == "fisheye":
        corrected = cv2.fisheye.undistortPoints(
            points,
            camera_matrix,
            distortion[:4],
            P=projection,
        )
    else:
        corrected = cv2.undistortPoints(
            points,
            camera_matrix,
            distortion,
            P=projection,
        )
    values = corrected.reshape(-1, 2).astype(float).tolist()
    return {
        "points": build_value_payload(
            {
                "image_points": values,
                "point_count": len(values),
                "normalized": normalize,
            }
        )
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]
