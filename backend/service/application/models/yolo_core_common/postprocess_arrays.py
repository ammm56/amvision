"""YOLO 后处理数组归一化工具。"""

from __future__ import annotations

from typing import Any


def to_yolo_numpy_array(
    *,
    value: Any,
    np_module: Any,
    dtype: Any | None = None,
) -> Any:
    """把 PyTorch tensor 或运行时数组统一转换为 NumPy array。

    PyTorch 训练期输出可能位于 CUDA 设备，不能直接交给 ``numpy.asarray``。
    ONNX Runtime、OpenVINO 和 TensorRT 适配器已经返回 CPU array，因此统一在
    后处理边界执行一次无副作用归一化。
    """

    detach = getattr(value, "detach", None)
    if callable(detach):
        value = detach()
        cpu = getattr(value, "cpu", None)
        if callable(cpu):
            value = cpu()
        numpy = getattr(value, "numpy", None)
        if callable(numpy):
            value = numpy()
    return np_module.asarray(value, dtype=dtype)


__all__ = ["to_yolo_numpy_array"]
