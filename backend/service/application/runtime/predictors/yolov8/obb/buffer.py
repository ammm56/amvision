"""YOLOv8 OBB TensorRT runtime buffer 工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.runtime.predictors.yolov8.segmentation.buffer import (
    build_yolov8_segmentation_numpy_array_from_host_pointer,
    resolve_yolov8_segmentation_numpy_dtype,
    resolve_yolov8_segmentation_tensor_byte_size,
)


def resolve_yolov8_obb_numpy_dtype(*, np_module: Any, dtype_name: str) -> Any:
    """把稳定字符串 dtype 映射为 NumPy dtype。"""

    return resolve_yolov8_segmentation_numpy_dtype(np_module=np_module, dtype_name=dtype_name)


def resolve_yolov8_obb_tensor_byte_size(
    *,
    np_module: Any,
    shape: tuple[int, ...],
    dtype: Any,
) -> int:
    """根据张量 shape 和 dtype 计算连续缓冲需要的字节数。"""

    return resolve_yolov8_segmentation_tensor_byte_size(
        np_module=np_module,
        shape=shape,
        dtype=dtype,
    )


def build_yolov8_obb_numpy_array_from_host_pointer(
    *,
    np_module: Any,
    host_ptr: int,
    byte_size: int,
    dtype: Any,
    shape: tuple[int, ...],
) -> Any:
    """把 host pointer 包装成指定 dtype 和 shape 的 NumPy 视图。"""

    return build_yolov8_segmentation_numpy_array_from_host_pointer(
        np_module=np_module,
        host_ptr=host_ptr,
        byte_size=byte_size,
        dtype=dtype,
        shape=shape,
    )


__all__ = [
    "build_yolov8_obb_numpy_array_from_host_pointer",
    "resolve_yolov8_obb_numpy_dtype",
    "resolve_yolov8_obb_tensor_byte_size",
]
