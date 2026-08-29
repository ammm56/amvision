"""相机与双目标定 payload 的构造和校验工具。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads.matrices import (
    require_matrix,
    require_vector,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads.points import (
    require_coordinate_space,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.validators import (
    require_non_negative_float,
    require_positive_int,
)


CAMERA_MODELS = {"pinhole", "fisheye"}
CALIBRATION_UNITS = {"millimeter", "meter", "unitless"}


def require_camera_calibration_payload(payload: object) -> dict[str, object]:
    """校验并规范化 camera-calibration.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("camera-calibration payload 必须是对象")
    camera_model = _require_choice(
        payload.get("camera_model"),
        field_name="camera_model",
        supported_values=CAMERA_MODELS,
    )
    image_size = _require_image_size(payload.get("image_size"), field_name="image_size")
    distortion_coefficients = _require_number_array(
        payload.get("distortion_coefficients"),
        field_name="distortion_coefficients",
        min_length=4,
        max_length=14,
    )
    diagnostics = _require_object(payload.get("diagnostics"), field_name="diagnostics")
    return {
        "calibration_id": _require_text(
            payload.get("calibration_id"), field_name="calibration_id"
        ),
        "camera_model": camera_model,
        "image_size": image_size,
        "camera_matrix": require_matrix(
            payload.get("camera_matrix"),
            rows=3,
            columns=3,
            field_name="camera_matrix",
        ),
        "distortion_coefficients": distortion_coefficients,
        "image_coordinate_space": require_coordinate_space(
            payload.get("image_coordinate_space"),
            field_name="image_coordinate_space",
        ),
        "camera_coordinate_space": require_coordinate_space(
            payload.get("camera_coordinate_space"),
            field_name="camera_coordinate_space",
        ),
        "object_point_unit": _require_choice(
            payload.get("object_point_unit"),
            field_name="object_point_unit",
            supported_values=CALIBRATION_UNITS,
        ),
        "observation_count": require_positive_int(
            payload.get("observation_count"),
            field_name="observation_count",
        ),
        "rms_reprojection_error": require_non_negative_float(
            payload.get("rms_reprojection_error"),
            field_name="rms_reprojection_error",
        ),
        "source_fingerprint": _require_text(
            payload.get("source_fingerprint"),
            field_name="source_fingerprint",
        ),
        "diagnostics": diagnostics,
    }


def require_stereo_calibration_payload(payload: object) -> dict[str, object]:
    """校验并规范化 stereo-calibration.v1 payload。"""

    if not isinstance(payload, dict):
        raise InvalidRequestError("stereo-calibration payload 必须是对象")
    left_camera = require_camera_calibration_payload(payload.get("left_camera"))
    right_camera = require_camera_calibration_payload(payload.get("right_camera"))
    image_size = _require_image_size(payload.get("image_size"), field_name="image_size")
    if image_size != left_camera["image_size"] or image_size != right_camera["image_size"]:
        raise InvalidRequestError("stereo image_size 必须与左右相机标定一致")

    normalized_payload: dict[str, object] = {
        "stereo_calibration_id": _require_text(
            payload.get("stereo_calibration_id"),
            field_name="stereo_calibration_id",
        ),
        "left_camera": left_camera,
        "right_camera": right_camera,
        "image_size": image_size,
        "left_coordinate_space": require_coordinate_space(
            payload.get("left_coordinate_space"),
            field_name="left_coordinate_space",
        ),
        "right_coordinate_space": require_coordinate_space(
            payload.get("right_coordinate_space"),
            field_name="right_coordinate_space",
        ),
        "rotation_3x3": require_matrix(
            payload.get("rotation_3x3"),
            rows=3,
            columns=3,
            field_name="rotation_3x3",
        ),
        "translation_3": require_vector(
            payload.get("translation_3"),
            length=3,
            field_name="translation_3",
        ),
        "essential_matrix_3x3": require_matrix(
            payload.get("essential_matrix_3x3"),
            rows=3,
            columns=3,
            field_name="essential_matrix_3x3",
        ),
        "fundamental_matrix_3x3": require_matrix(
            payload.get("fundamental_matrix_3x3"),
            rows=3,
            columns=3,
            field_name="fundamental_matrix_3x3",
        ),
        "rms_epipolar_error": require_non_negative_float(
            payload.get("rms_epipolar_error"),
            field_name="rms_epipolar_error",
        ),
        "source_fingerprint": _require_text(
            payload.get("source_fingerprint"),
            field_name="source_fingerprint",
        ),
        "diagnostics": _require_object(
            payload.get("diagnostics"),
            field_name="diagnostics",
        ),
    }
    raw_rectification = payload.get("rectification")
    if raw_rectification is not None:
        normalized_payload["rectification"] = _require_rectification(raw_rectification)
    return normalized_payload


def _require_rectification(raw_value: object) -> dict[str, object]:
    """校验双目校正参数与 ObjectStore map 引用。"""

    if not isinstance(raw_value, dict):
        raise InvalidRequestError("rectification 必须是对象")
    normalized_value: dict[str, object] = {
        "left_rotation_3x3": require_matrix(
            raw_value.get("left_rotation_3x3"),
            rows=3,
            columns=3,
            field_name="rectification.left_rotation_3x3",
        ),
        "right_rotation_3x3": require_matrix(
            raw_value.get("right_rotation_3x3"),
            rows=3,
            columns=3,
            field_name="rectification.right_rotation_3x3",
        ),
        "left_projection_3x4": require_matrix(
            raw_value.get("left_projection_3x4"),
            rows=3,
            columns=4,
            field_name="rectification.left_projection_3x4",
        ),
        "right_projection_3x4": require_matrix(
            raw_value.get("right_projection_3x4"),
            rows=3,
            columns=4,
            field_name="rectification.right_projection_3x4",
        ),
        "disparity_to_depth_4x4": require_matrix(
            raw_value.get("disparity_to_depth_4x4"),
            rows=4,
            columns=4,
            field_name="rectification.disparity_to_depth_4x4",
        ),
        "left_valid_roi_xywh": _require_integer_roi(
            raw_value.get("left_valid_roi_xywh"),
            field_name="rectification.left_valid_roi_xywh",
        ),
        "right_valid_roi_xywh": _require_integer_roi(
            raw_value.get("right_valid_roi_xywh"),
            field_name="rectification.right_valid_roi_xywh",
        ),
    }
    raw_map_keys = raw_value.get("map_object_keys")
    if raw_map_keys is not None:
        if not isinstance(raw_map_keys, dict):
            raise InvalidRequestError("rectification.map_object_keys 必须是对象")
        required_keys = ("left_map_x", "left_map_y", "right_map_x", "right_map_y")
        normalized_value["map_object_keys"] = {
            key: _require_text(
                raw_map_keys.get(key),
                field_name=f"rectification.map_object_keys.{key}",
                max_length=1024,
            )
            for key in required_keys
        }
    return normalized_value


def _require_image_size(raw_value: object, *, field_name: str) -> list[int]:
    """读取正整数宽高。"""

    if not isinstance(raw_value, list) or len(raw_value) != 2:
        raise InvalidRequestError(f"{field_name} 必须是 [width, height]")
    return [
        require_positive_int(raw_value[0], field_name=f"{field_name}[0]"),
        require_positive_int(raw_value[1], field_name=f"{field_name}[1]"),
    ]


def _require_number_array(
    raw_value: object,
    *,
    field_name: str,
    min_length: int,
    max_length: int,
) -> list[float]:
    """读取长度有界的有限数值数组。"""

    from custom_nodes.opencv_nodes.shared.backend.runtime.validators import require_number

    if not isinstance(raw_value, list) or not min_length <= len(raw_value) <= max_length:
        raise InvalidRequestError(
            f"{field_name} 长度必须在 {min_length} 到 {max_length} 之间"
        )
    return [
        require_number(raw_cell, field_name=f"{field_name}[{cell_index}]")
        for cell_index, raw_cell in enumerate(raw_value)
    ]


def _require_integer_roi(raw_value: object, *, field_name: str) -> list[int]:
    """读取非负整数 xywh。"""

    if not isinstance(raw_value, list) or len(raw_value) != 4:
        raise InvalidRequestError(f"{field_name} 必须是长度为 4 的整数数组")
    normalized_value: list[int] = []
    for item_index, raw_item in enumerate(raw_value):
        if isinstance(raw_item, bool) or not isinstance(raw_item, int) or raw_item < 0:
            raise InvalidRequestError(f"{field_name}[{item_index}] 必须是非负整数")
        normalized_value.append(raw_item)
    return normalized_value


def _require_choice(
    raw_value: object,
    *,
    field_name: str,
    supported_values: set[str],
) -> str:
    """读取受控小写枚举。"""

    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in supported_values:
        supported_text = "、".join(sorted(supported_values))
        raise InvalidRequestError(f"{field_name} 仅支持 {supported_text}")
    return normalized_value


def _require_text(
    raw_value: object,
    *,
    field_name: str,
    max_length: int = 128,
) -> str:
    """读取长度有界的非空文本。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{field_name} 必须是非空字符串")
    normalized_value = raw_value.strip()
    if len(normalized_value) > max_length:
        raise InvalidRequestError(f"{field_name} 长度不能超过 {max_length}")
    return normalized_value


def _require_object(raw_value: object, *, field_name: str) -> dict[str, object]:
    """读取 JSON 对象。"""

    if not isinstance(raw_value, dict):
        raise InvalidRequestError(f"{field_name} 必须是对象")
    return dict(raw_value)


__all__ = [
    "CALIBRATION_UNITS",
    "CAMERA_MODELS",
    "require_camera_calibration_payload",
    "require_stereo_calibration_payload",
]
