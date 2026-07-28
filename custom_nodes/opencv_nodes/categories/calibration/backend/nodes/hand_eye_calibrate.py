"""由机器人末端位姿和标定板位姿估计相机到夹具的外参。"""

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.calibration_runtime import (
    build_pose_matrices,
    parse_pose_items,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    read_choice,
    require_value_input,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)

NODE_TYPE_ID = "custom.opencv.hand-eye-calibrate"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算 camera-to-gripper 手眼变换。"""

    cv2, np = require_opencv_imports()
    robot_value = require_value_input(request, input_name="robot_poses")
    target_value = require_value_input(request, input_name="target_poses")
    robot_items = parse_pose_items(robot_value, field_name="robot_poses")
    target_items = parse_pose_items(target_value, field_name="target_poses")
    if len(robot_items) != len(target_items) or len(robot_items) < 3:
        raise InvalidRequestError(
            "robot_poses 与 target_poses 数量必须一致且至少包含 3 组"
        )
    method_name = read_choice(
        request.parameters.get("method"),
        field_name="method",
        choices={"tsai", "park", "horaud", "andreff", "daniilidis"},
        default="tsai",
    )
    method = {
        "tsai": cv2.CALIB_HAND_EYE_TSAI,
        "park": cv2.CALIB_HAND_EYE_PARK,
        "horaud": cv2.CALIB_HAND_EYE_HORAUD,
        "andreff": cv2.CALIB_HAND_EYE_ANDREFF,
        "daniilidis": cv2.CALIB_HAND_EYE_DANIILIDIS,
    }[method_name]
    robot_rotations, robot_translations = build_pose_matrices(
        robot_items,
        cv2_module=cv2,
        np_module=np,
    )
    target_rotations, target_translations = build_pose_matrices(
        target_items,
        cv2_module=cv2,
        np_module=np,
    )
    rotation, translation = cv2.calibrateHandEye(
        robot_rotations,
        robot_translations,
        target_rotations,
        target_translations,
        method=method,
    )
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = rotation
    transform[:3, 3] = translation.reshape(3)
    rotation_vector, _ = cv2.Rodrigues(rotation)
    return {
        "hand_eye": build_value_payload(
            {
                "method": method_name,
                "rotation_matrix": rotation.astype(float).tolist(),
                "rotation_vector": rotation_vector.reshape(-1).astype(float).tolist(),
                "translation_vector": translation.reshape(-1).astype(float).tolist(),
                "transform_matrix_4x4": transform.astype(float).tolist(),
                "pose_count": len(robot_items),
                "transform_direction": "camera-to-gripper",
            }
        )
    }


__all__ = ["NODE_TYPE_ID", "handle_node"]
