"""按相机模型和位姿把三维点投影到图像平面。"""

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.calibration_runtime import (
    parse_camera_model,
    parse_rotation_vector,
    require_object_input,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    read_points,
    require_value_input,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.project-points"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """投影三维点，兼容 pinhole 和 fisheye 标定模型。"""

    cv2, np = require_opencv_imports()
    points_value = require_value_input(request, input_name="object_points")
    pose = require_object_input(request, "pose")
    calibration = require_object_input(request, "calibration")
    raw_points = (
        points_value.get("object_points")
        if isinstance(points_value, dict)
        else points_value
    )
    object_points = np.asarray(
        read_points(
            raw_points,
            field_name="object_points",
            minimum_count=1,
            dimensions=3,
        ),
        dtype=np.float64,
    )
    camera_matrix, distortion = parse_camera_model(
        calibration,
        np_module=np,
    )
    rotation = parse_rotation_vector(
        pose,
        cv2_module=cv2,
        np_module=np,
    )
    translation = np.asarray(
        pose.get("translation_vector"),
        dtype=np.float64,
    ).reshape(3, 1)
    if str(calibration.get("model", "pinhole")) == "fisheye":
        projected, _ = cv2.fisheye.projectPoints(
            object_points.reshape(1, -1, 3),
            rotation,
            translation,
            camera_matrix,
            distortion[:4],
        )
    else:
        projected, _ = cv2.projectPoints(
            object_points,
            rotation,
            translation,
            camera_matrix,
            distortion,
        )
    points = projected.reshape(-1, 2).astype(float).tolist()
    return {
        "image_points": build_value_payload(
            {"image_points": points, "point_count": len(points)}
        )
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]
