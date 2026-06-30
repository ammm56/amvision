"""普通 YOLO 训练 batch tensor 搬运工具。"""

from __future__ import annotations

from typing import Any


def move_yolo_tensor_to_training_device(
    tensor: Any,
    *,
    device: str,
    runtime_precision: str | None = None,
) -> Any:
    """把 CPU tensor 按训练设备规则搬到目标设备。

    参考 Ultralytics 的训练预处理边界，CUDA 训练时优先使用 pinned memory
    和 non-blocking transfer，降低数据搬运对 GPU 计算流的阻塞。该函数只处理
    tensor 搬运和 image precision，不改变标签坐标、loss 或模型结构。
    """

    transferred = tensor
    if _should_pin_before_transfer(transferred, device=device):
        try:
            transferred = transferred.pin_memory()
        except RuntimeError:
            transferred = tensor
    to_kwargs: dict[str, object] = {}
    if _is_cuda_device(device):
        to_kwargs["non_blocking"] = True
    transferred = transferred.to(device, **to_kwargs)
    if runtime_precision == "fp16":
        transferred = transferred.half()
    return transferred


def _should_pin_before_transfer(tensor: Any, *, device: str) -> bool:
    """判断当前 tensor 是否适合先 pin memory 再搬到 CUDA。"""

    tensor_device = getattr(tensor, "device", None)
    tensor_device_type = getattr(tensor_device, "type", None)
    return _is_cuda_device(device) and tensor_device_type == "cpu" and hasattr(tensor, "pin_memory")


def _is_cuda_device(device: str) -> bool:
    """判断设备字符串是否指向 CUDA。"""

    return str(device).lower().startswith("cuda")


__all__ = ["move_yolo_tensor_to_training_device"]
