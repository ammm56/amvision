"""OpenCV shared 参数校验和 OpenCV 枚举解析。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError


def require_boolean(value: object, *, field_name: str) -> bool:
    """读取严格 boolean，禁止字符串和数值被隐式转换。"""

    if not isinstance(value, bool):
        raise InvalidRequestError(f"{field_name} 必须是 boolean")
    return value


def require_positive_int(value: object, *, field_name: str) -> int:
    """把输入值解析为正整数。

    参数：
    - value：原始值。
    - field_name：字段名称。

    返回：
    - int：规范化后的正整数。
    """

    normalized_value = int(value)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{field_name} 必须大于 0")
    return normalized_value

def require_number(value: object, *, field_name: str) -> float:
    """把输入值解析为数值。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数值")
    return float(value)

def require_non_negative_float(value: object, *, field_name: str) -> float:
    """把输入值解析为非负浮点数。

    参数：
    - value：原始值。
    - field_name：字段名称。

    返回：
    - float：规范化后的非负浮点数。
    """

    normalized_value = float(value)
    if normalized_value < 0:
        raise InvalidRequestError(f"{field_name} 不能小于 0")
    return normalized_value

def require_uint8_int(value: object, *, field_name: str) -> int:
    """把输入值解析为 0 到 255 之间的整数。

    参数：
    - value：原始值。
    - field_name：字段名称。

    返回：
    - int：规范化后的整数。
    """

    normalized_value = require_non_negative_int(value, field_name=field_name)
    if normalized_value > 255:
        raise InvalidRequestError(f"{field_name} 不能大于 255")
    return normalized_value

def normalize_odd_kernel_size(value: object) -> int:
    """把 kernel size 规范化为奇数正整数。

    参数：
    - value：原始 kernel size。

    返回：
    - int：规范化后的奇数 kernel size。
    """

    kernel_size = require_positive_int(value, field_name="kernel_size")
    if kernel_size % 2 == 0:
        raise InvalidRequestError("kernel_size 必须是奇数")
    return kernel_size

def normalize_adaptive_block_size(value: object) -> int:
    """把 adaptive-threshold 的 block size 规范化为大于等于 3 的奇数。"""

    block_size = normalize_odd_kernel_size(value)
    if block_size < 3:
        raise InvalidRequestError("block_size 必须是大于等于 3 的奇数")
    return block_size

def normalize_morphology_operation(value: object) -> str:
    """规范化 morphology 操作名称。

    参数：
    - value：原始操作名称。

    返回：
    - str：规范化后的操作名称。
    """

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError("operation 必须是非空字符串")
    normalized_value = value.strip().lower()
    if normalized_value not in {"erode", "dilate", "open", "close", "gradient", "top-hat", "black-hat"}:
        raise InvalidRequestError("operation 不在支持的 morphology 列表中")
    return normalized_value

def normalize_contour_retrieval_mode(value: object, *, cv2_module: Any) -> int:
    """把 contour retrieval mode 解析为 OpenCV 常量。

    参数：
    - value：原始 mode 名称。
    - cv2_module：OpenCV 模块。

    返回：
    - int：OpenCV retrieval mode 常量。
    """

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError("retrieval_mode 必须是非空字符串")
    normalized_value = value.strip().lower()
    if normalized_value == "external":
        return cv2_module.RETR_EXTERNAL
    if normalized_value == "list":
        return cv2_module.RETR_LIST
    if normalized_value == "tree":
        return cv2_module.RETR_TREE
    if normalized_value == "ccomp":
        return cv2_module.RETR_CCOMP
    raise InvalidRequestError("retrieval_mode 不在支持的 contour retrieval 列表中")

def normalize_contour_approximation(value: object, *, cv2_module: Any) -> int:
    """把 contour approximation 解析为 OpenCV 常量。

    参数：
    - value：原始 approximation 名称。
    - cv2_module：OpenCV 模块。

    返回：
    - int：OpenCV contour approximation 常量。
    """

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError("approximation 必须是非空字符串")
    normalized_value = value.strip().lower()
    if normalized_value == "simple":
        return cv2_module.CHAIN_APPROX_SIMPLE
    if normalized_value == "none":
        return cv2_module.CHAIN_APPROX_NONE
    if normalized_value == "tc89-l1":
        return cv2_module.CHAIN_APPROX_TC89_L1
    if normalized_value == "tc89-kcos":
        return cv2_module.CHAIN_APPROX_TC89_KCOS
    raise InvalidRequestError("approximation 不在支持的 contour approximation 列表中")

def normalize_kernel_shape(value: object, *, cv2_module: Any) -> int:
    """规范化 morphology kernel 形状。

    参数：
    - value：原始形状名称。
    - cv2_module：OpenCV 模块。

    返回：
    - int：OpenCV kernel shape 常量。
    """

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError("shape 必须是非空字符串")
    normalized_value = value.strip().lower()
    if normalized_value == "rect":
        return cv2_module.MORPH_RECT
    if normalized_value == "ellipse":
        return cv2_module.MORPH_ELLIPSE
    if normalized_value == "cross":
        return cv2_module.MORPH_CROSS
    raise InvalidRequestError("shape 不在支持的 morphology 形状列表中")

def normalize_resize_interpolation(value: object, *, cv2_module: Any) -> int:
    """把 resize interpolation 解析为 OpenCV 常量。"""

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError("interpolation 必须是非空字符串")
    normalized_value = value.strip().lower()
    if normalized_value == "nearest":
        return cv2_module.INTER_NEAREST
    if normalized_value == "linear":
        return cv2_module.INTER_LINEAR
    if normalized_value == "area":
        return cv2_module.INTER_AREA
    if normalized_value == "cubic":
        return cv2_module.INTER_CUBIC
    if normalized_value == "lanczos4":
        return cv2_module.INTER_LANCZOS4
    raise InvalidRequestError("interpolation 不在支持的 resize interpolation 列表中")

def normalize_binary_threshold_mode(value: object, *, cv2_module: Any) -> int:
    """把二值 threshold mode 解析为 OpenCV 常量。"""

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError("threshold_type 必须是非空字符串")
    normalized_value = value.strip().lower()
    if normalized_value == "binary":
        return cv2_module.THRESH_BINARY
    if normalized_value == "binary-inv":
        return cv2_module.THRESH_BINARY_INV
    raise InvalidRequestError("threshold_type 仅支持 binary 或 binary-inv")

def normalize_image_diff_mode(value: object) -> str:
    """规范化 image-diff 的输出模式。"""

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError("diff_mode 必须是非空字符串")
    normalized_value = value.strip().lower()
    if normalized_value not in {"grayscale", "color"}:
        raise InvalidRequestError("diff_mode 仅支持 grayscale 或 color")
    return normalized_value

def normalize_adaptive_threshold_method(value: object, *, cv2_module: Any) -> int:
    """把 adaptive threshold method 解析为 OpenCV 常量。"""

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError("adaptive_method 必须是非空字符串")
    normalized_value = value.strip().lower()
    if normalized_value == "mean":
        return cv2_module.ADAPTIVE_THRESH_MEAN_C
    if normalized_value == "gaussian":
        return cv2_module.ADAPTIVE_THRESH_GAUSSIAN_C
    raise InvalidRequestError("adaptive_method 仅支持 mean 或 gaussian")

def normalize_connected_components_connectivity(value: object) -> int:
    """规范化 connected-components 的 connectivity。"""

    connectivity = require_positive_int(value, field_name="connectivity")
    if connectivity not in {4, 8}:
        raise InvalidRequestError("connectivity 只能是 4 或 8")
    return connectivity

def resolve_morphology_operation(operation_name: str, *, cv2_module: Any) -> int:
    """把 morphology 操作名称解析为 OpenCV 常量。

    参数：
    - operation_name：规范化后的操作名称。
    - cv2_module：OpenCV 模块。

    返回：
    - int：OpenCV morphology 操作常量。
    """

    operation_mapping = {
        "open": cv2_module.MORPH_OPEN,
        "close": cv2_module.MORPH_CLOSE,
        "gradient": cv2_module.MORPH_GRADIENT,
        "top-hat": cv2_module.MORPH_TOPHAT,
        "black-hat": cv2_module.MORPH_BLACKHAT,
    }
    operation_value = operation_mapping.get(operation_name)
    if operation_value is None:
        raise InvalidRequestError("当前 morphology operation 不支持通过 morphologyEx 执行")
    return operation_value

def require_aperture_size(value: object) -> int:
    """把 Canny aperture size 规范化为 3、5 或 7。

    参数：
    - value：原始 aperture size。

    返回：
    - int：规范化后的 aperture size。
    """

    aperture_size = require_positive_int(value, field_name="aperture_size")
    if aperture_size not in {3, 5, 7}:
        raise InvalidRequestError("aperture_size 只能是 3、5 或 7")
    return aperture_size

def require_non_negative_int(value: object, *, field_name: str) -> int:
    """把输入值解析为非负整数。

    参数：
    - value：原始值。
    - field_name：字段名称。

    返回：
    - int：规范化后的非负整数。
    """

    normalized_value = int(value)
    if normalized_value < 0:
        raise InvalidRequestError(f"{field_name} 不能小于 0")
    return normalized_value

def normalize_optional_object_key(value: object) -> str | None:
    """规范化可选 output_object_key 参数。

    参数：
    - value：原始 object key。

    返回：
    - str | None：规范化后的 object key。
    """

    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
