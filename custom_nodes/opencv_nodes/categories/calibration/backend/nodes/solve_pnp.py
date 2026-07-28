"""Solve PnP 节点实现。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    read_choice,
    read_points,
    require_value_input,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports

NODE_TYPE_ID = "custom.opencv.solve-pnp"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """根据 3D-2D 对应点和相机标定结果估计物体位姿。"""

    cv2_module, np_module = require_opencv_imports()
    observation = require_value_input(request, input_name="observation")
    calibration = require_value_input(request, input_name="calibration")
    if not isinstance(observation, dict) or not isinstance(calibration, dict):
        raise InvalidRequestError("observation 和 calibration 必须解析为对象")
    object_points = read_points(
        observation.get("object_points"),
        field_name="object_points",
        minimum_count=4,
        dimensions=3,
    )
    image_points = read_points(
        observation.get("image_points"),
        field_name="image_points",
        minimum_count=4,
        dimensions=2,
    )
    if len(object_points) != len(image_points):
        raise InvalidRequestError("object_points 与 image_points 数量必须一致")
    camera_matrix = np_module.asarray(calibration.get("camera_matrix"), dtype=np_module.float64)
    if camera_matrix.shape != (3, 3):
        raise InvalidRequestError("calibration.camera_matrix 必须是 3x3 矩阵")
    distortion = np_module.asarray(
        calibration.get("distortion_coefficients", []),
        dtype=np_module.float64,
    ).reshape(-1, 1)
    method_name = read_choice(
        request.parameters.get("method"),
        field_name="method",
        choices={"iterative", "epnp", "p3p", "ippe", "ippe-square"},
        default="iterative",
    )
    method = {
        "iterative": cv2_module.SOLVEPNP_ITERATIVE,
        "epnp": cv2_module.SOLVEPNP_EPNP,
        "p3p": cv2_module.SOLVEPNP_P3P,
        "ippe": cv2_module.SOLVEPNP_IPPE,
        "ippe-square": cv2_module.SOLVEPNP_IPPE_SQUARE,
    }[method_name]
    if method_name in {"p3p", "ippe-square"} and len(object_points) != 4:
        raise InvalidRequestError(f"{method_name} 方法要求恰好四组对应点")
    object_matrix = np_module.asarray(object_points, dtype=np_module.float64)
    image_matrix = np_module.asarray(image_points, dtype=np_module.float64)
    success, rotation_vector, translation_vector = cv2_module.solvePnP(
        object_matrix,
        image_matrix,
        camera_matrix,
        distortion,
        flags=method,
    )
    if not success:
        raise InvalidRequestError("solvePnP 未能估计位姿")
    rotation_matrix, _ = cv2_module.Rodrigues(rotation_vector)
    projected, _ = cv2_module.projectPoints(
        object_matrix,
        rotation_vector,
        translation_vector,
        camera_matrix,
        distortion,
    )
    reprojection_errors = np_module.linalg.norm(projected.reshape(-1, 2) - image_matrix, axis=1)
    return {
        "pose": build_value_payload(
            {
                "method": method_name,
                "rotation_vector": rotation_vector.reshape(-1).astype(float).tolist(),
                "translation_vector": translation_vector.reshape(-1).astype(float).tolist(),
                "rotation_matrix": rotation_matrix.astype(float).tolist(),
                "transform_matrix_4x4": np_module.vstack(
                    [
                        np_module.column_stack([rotation_matrix, translation_vector.reshape(3, 1)]),
                        [0.0, 0.0, 0.0, 1.0],
                    ]
                ).astype(float).tolist(),
                "projected_points": projected.reshape(-1, 2).astype(float).tolist(),
                "mean_reprojection_error": float(reprojection_errors.mean()),
                "max_reprojection_error": float(reprojection_errors.max()),
                "point_count": len(object_points),
            }
        )
    }
