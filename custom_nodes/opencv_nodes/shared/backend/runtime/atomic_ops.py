"""OpenCV 原子算子节点共享运行时工具。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from backend.nodes.core_nodes.support.logic import require_value_payload
from backend.nodes.parameter_utils import is_empty_parameter
from backend.service.application.errors import InvalidRequestError
from custom_nodes.opencv_nodes.shared.backend.runtime.images import (
    build_output_image_matrix_payload,
)


def read_bool(value: object, *, field_name: str, default: bool) -> bool:
    """读取布尔参数。"""

    if is_empty_parameter(value):
        return default
    if not isinstance(value, bool):
        raise InvalidRequestError(f"{field_name} 必须是布尔值")
    return value


def read_choice(
    value: object,
    *,
    field_name: str,
    choices: Iterable[str],
    default: str,
) -> str:
    """读取并校验枚举字符串参数。"""

    normalized_choices = {str(item).strip().lower() for item in choices}
    normalized = default if is_empty_parameter(value) else str(value).strip().lower()
    if normalized not in normalized_choices:
        raise InvalidRequestError(
            f"{field_name} 不支持当前值",
            details={"value": normalized, "choices": sorted(normalized_choices)},
        )
    return normalized


def read_float(
    value: object,
    *,
    field_name: str,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    """读取有限浮点参数并校验范围。"""

    raw_value = default if is_empty_parameter(value) else value
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数字")
    normalized = float(raw_value)
    if normalized != normalized or normalized in {float("inf"), float("-inf")}:
        raise InvalidRequestError(f"{field_name} 必须是有限数字")
    if minimum is not None and normalized < minimum:
        raise InvalidRequestError(f"{field_name} 不能小于 {minimum}")
    if maximum is not None and normalized > maximum:
        raise InvalidRequestError(f"{field_name} 不能大于 {maximum}")
    return normalized


def read_int(
    value: object,
    *,
    field_name: str,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """读取整数参数并校验范围。"""

    raw_value = default if is_empty_parameter(value) else value
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{field_name} 必须是整数")
    normalized = int(raw_value)
    if minimum is not None and normalized < minimum:
        raise InvalidRequestError(f"{field_name} 不能小于 {minimum}")
    if maximum is not None and normalized > maximum:
        raise InvalidRequestError(f"{field_name} 不能大于 {maximum}")
    return normalized


def read_number_list(
    value: object,
    *,
    field_name: str,
    minimum_length: int = 1,
    exact_length: int | None = None,
) -> list[float]:
    """读取一维数字数组。"""

    if not isinstance(value, (list, tuple)):
        raise InvalidRequestError(f"{field_name} 必须是数字数组")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise InvalidRequestError(f"{field_name} 必须只包含数字")
        result.append(float(item))
    if exact_length is not None and len(result) != exact_length:
        raise InvalidRequestError(f"{field_name} 必须包含 {exact_length} 个数字")
    if len(result) < minimum_length:
        raise InvalidRequestError(f"{field_name} 至少包含 {minimum_length} 个数字")
    return result


def read_points(
    value: object,
    *,
    field_name: str,
    minimum_count: int,
    dimensions: int = 2,
) -> list[list[float]]:
    """读取二维或三维点数组。"""

    if not isinstance(value, (list, tuple)) or len(value) < minimum_count:
        raise InvalidRequestError(f"{field_name} 至少包含 {minimum_count} 个点")
    points: list[list[float]] = []
    for point in value:
        points.append(
            read_number_list(
                point,
                field_name=field_name,
                exact_length=dimensions,
            )
        )
    return points


def require_value_input(request: object, *, input_name: str) -> object:
    """读取 value.v1 输入的 value 字段。"""

    input_values = getattr(request, "input_values", {})
    return require_value_payload(input_values.get(input_name), field_name=input_name)["value"]


def ensure_gray(image_matrix: Any, *, cv2_module: Any) -> Any:
    """把输入图片转换为单通道灰度图。"""

    if len(image_matrix.shape) == 2:
        return image_matrix
    if image_matrix.shape[2] == 4:
        return cv2_module.cvtColor(image_matrix, cv2_module.COLOR_BGRA2GRAY)
    return cv2_module.cvtColor(image_matrix, cv2_module.COLOR_BGR2GRAY)


def ensure_bgr(image_matrix: Any, *, cv2_module: Any) -> Any:
    """把输入图片转换为三通道 BGR 图。"""

    if len(image_matrix.shape) == 2:
        return cv2_module.cvtColor(image_matrix, cv2_module.COLOR_GRAY2BGR)
    if image_matrix.shape[2] == 4:
        return cv2_module.cvtColor(image_matrix, cv2_module.COLOR_BGRA2BGR)
    return image_matrix


def require_same_shape(*matrices: Any, field_name: str = "images") -> None:
    """校验多张图片尺寸和通道完全一致。"""

    shapes = [tuple(matrix.shape) for matrix in matrices]
    if not shapes or any(shape != shapes[0] for shape in shapes[1:]):
        raise InvalidRequestError(
            f"{field_name} 的尺寸和通道必须一致",
            details={"shapes": [list(shape) for shape in shapes]},
        )


def build_image_output(
    request: object,
    *,
    source_payload: dict[str, object],
    image_matrix: Any,
    variant_name: str,
    save_location: object = None,
) -> dict[str, object]:
    """构造原子图像算子的统一 image-ref.v1 输出。"""

    return build_output_image_matrix_payload(
        request,
        source_payload=source_payload,
        image_matrix=image_matrix,
        save_location=save_location,
        variant_name=variant_name,
        error_message=f"OpenCV {variant_name} 后无法编码输出图片",
    )


def json_number(value: Any, *, digits: int = 8) -> float:
    """把 numpy 数字转换为稳定的 JSON 浮点数。"""

    return round(float(value), digits)
