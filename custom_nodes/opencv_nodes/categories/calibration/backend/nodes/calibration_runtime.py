"""相机标定节点共用的输入解析工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    require_value_input,
)


def require_object_input(
    request: WorkflowNodeExecutionRequest,
    input_name: str,
) -> dict[str, object]:
    """读取并校验 value.v1 对象输入。"""

    value = require_value_input(request, input_name=input_name)
    if not isinstance(value, dict):
        raise InvalidRequestError(f"{input_name} 必须解析为对象")
    return value


def parse_camera_model(
    calibration: dict[str, object],
    *,
    np_module: Any,
) -> tuple[Any, Any]:
    """解析相机矩阵和畸变系数。"""

    camera_matrix = np_module.asarray(
        calibration.get("camera_matrix"),
        dtype=np_module.float64,
    )
    if camera_matrix.shape != (3, 3):
        raise InvalidRequestError("calibration.camera_matrix 必须是 3x3 矩阵")
    distortion = np_module.asarray(
        calibration.get("distortion_coefficients", []),
        dtype=np_module.float64,
    ).reshape(-1, 1)
    if distortion.size < 4:
        raise InvalidRequestError(
            "calibration.distortion_coefficients 至少需要 4 个系数"
        )
    return camera_matrix, distortion


def parse_rotation_vector(
    pose: dict[str, object],
    *,
    cv2_module: Any,
    np_module: Any,
) -> Any:
    """从位姿对象读取 Rodrigues 旋转向量。"""

    if pose.get("rotation_vector") is not None:
        return np_module.asarray(
            pose["rotation_vector"],
            dtype=np_module.float64,
        ).reshape(3, 1)
    matrix = np_module.asarray(
        pose.get("rotation_matrix"),
        dtype=np_module.float64,
    )
    if matrix.shape != (3, 3):
        raise InvalidRequestError(
            "pose 必须提供 rotation_vector 或 3x3 rotation_matrix"
        )
    vector, _ = cv2_module.Rodrigues(matrix)
    return vector


def parse_pose_items(value: object, *, field_name: str) -> list[dict[str, object]]:
    """读取位姿对象数组。"""

    raw_items = value.get("items") if isinstance(value, dict) else value
    if not isinstance(raw_items, list) or not all(
        isinstance(item, dict) for item in raw_items
    ):
        raise InvalidRequestError(f"{field_name} 必须包含位姿对象数组")
    return [dict(item) for item in raw_items]


def build_pose_matrices(
    items: list[dict[str, object]],
    *,
    cv2_module: Any,
    np_module: Any,
) -> tuple[list[Any], list[Any]]:
    """把位姿对象数组转换为 OpenCV hand-eye 输入。"""

    rotations: list[Any] = []
    translations: list[Any] = []
    for item in items:
        rotation_vector = parse_rotation_vector(
            item,
            cv2_module=cv2_module,
            np_module=np_module,
        )
        rotation_matrix, _ = cv2_module.Rodrigues(rotation_vector)
        translation = np_module.asarray(
            item.get("translation_vector"),
            dtype=np_module.float64,
        )
        if translation.size != 3:
            raise InvalidRequestError(
                "每个位姿都必须提供长度为 3 的 translation_vector"
            )
        rotations.append(rotation_matrix)
        translations.append(translation.reshape(3, 1))
    return rotations, translations


__all__ = [
    "build_pose_matrices",
    "parse_camera_model",
    "parse_pose_items",
    "parse_rotation_vector",
    "require_object_input",
]
