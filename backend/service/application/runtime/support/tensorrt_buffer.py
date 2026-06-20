"""TensorRT runtime buffer 通用工具。"""

from __future__ import annotations

import ctypes
from typing import Any

from backend.service.application.errors import ServiceConfigurationError


def resolve_numpy_dtype(*, np_module: Any, dtype_name: str) -> Any:
    """把 TensorRT dtype 名称映射为 NumPy dtype。"""

    dtype_map = {
        "float32": np_module.float32,
        "float16": np_module.float16,
        "int32": np_module.int32,
    }
    resolved_dtype = dtype_map.get(dtype_name)
    if resolved_dtype is None:
        raise ServiceConfigurationError(
            "TensorRT session 发现了不支持的张量 dtype",
            details={"dtype_name": dtype_name},
        )
    return resolved_dtype


def resolve_tensor_byte_size(
    *,
    np_module: Any,
    shape: tuple[int, ...],
    dtype: Any,
) -> int:
    """根据张量 shape 和 dtype 计算连续 buffer 字节数。"""

    element_count = 1
    for dim in shape:
        element_count *= int(dim)
    return element_count * int(np_module.dtype(dtype).itemsize)


def build_numpy_array_from_host_pointer(
    *,
    np_module: Any,
    host_ptr: int,
    byte_size: int,
    dtype: Any,
    shape: tuple[int, ...],
) -> Any:
    """把 pinned host pointer 包装成指定 dtype 和 shape 的 NumPy 视图。"""

    if int(host_ptr) <= 0 or int(byte_size) <= 0:
        raise ServiceConfigurationError(
            "TensorRT pinned host buffer 参数不合法",
            details={"host_ptr": int(host_ptr), "byte_size": int(byte_size)},
        )
    raw_bytes = np_module.ctypeslib.as_array(
        (ctypes.c_ubyte * int(byte_size)).from_address(int(host_ptr))
    )
    return raw_bytes.view(dtype=dtype).reshape(shape)


__all__ = [
    "build_numpy_array_from_host_pointer",
    "resolve_numpy_dtype",
    "resolve_tensor_byte_size",
]
