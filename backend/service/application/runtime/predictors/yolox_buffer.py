"""YOLOX TensorRT runtime buffer 工具。"""

from __future__ import annotations

import ctypes
from typing import Any

from backend.service.application.errors import ServiceConfigurationError


def resolve_yolox_numpy_dtype(*, np_module: Any, dtype_name: str) -> Any:
    """把稳定字符串 dtype 映射为 NumPy dtype。"""

    dtype_map = {
        "float32": np_module.float32,
        "float16": np_module.float16,
        "int32": np_module.int32,
    }
    resolved_dtype = dtype_map.get(dtype_name)
    if resolved_dtype is None:
        raise ServiceConfigurationError(
            "当前 TensorRT session 发现了不支持的张量 dtype",
            details={"dtype_name": dtype_name},
        )
    return resolved_dtype


def resolve_yolox_tensor_byte_size(*, np_module: Any, shape: tuple[int, ...], dtype: Any) -> int:
    """根据张量 shape 和 dtype 计算连续缓冲需要的字节数。

    参数：
    - np_module：NumPy 模块。
    - shape：张量 shape。
    - dtype：NumPy dtype。

    返回：
    - int：当前张量连续存储所需字节数。
    """

    element_count = 1
    for dim in shape:
        element_count *= int(dim)
    return element_count * int(np_module.dtype(dtype).itemsize)


def build_yolox_numpy_array_from_host_pointer(
    *,
    np_module: Any,
    host_ptr: int,
    byte_size: int,
    dtype: Any,
    shape: tuple[int, ...],
) -> Any:
    """把 host pointer 包装成指定 dtype 和 shape 的 NumPy 视图。

    参数：
    - np_module：NumPy 模块。
    - host_ptr：host pointer 整数地址。
    - byte_size：缓冲总字节数。
    - dtype：目标 NumPy dtype。
    - shape：目标数组 shape。

    返回：
    - Any：直接映射到既有 host memory 的 NumPy 数组视图。
    """

    if int(host_ptr) <= 0 or int(byte_size) <= 0:
        raise ServiceConfigurationError(
            "TensorRT pinned host buffer 参数不合法",
            details={"host_ptr": int(host_ptr), "byte_size": int(byte_size)},
        )
    raw_bytes = np_module.ctypeslib.as_array(
        (ctypes.c_ubyte * int(byte_size)).from_address(int(host_ptr))
    )
    return raw_bytes.view(dtype=dtype).reshape(shape)
