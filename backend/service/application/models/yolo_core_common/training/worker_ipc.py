"""YOLO DataLoader worker 的跨进程批数据序列化。"""

from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from typing import Any


def serialize_yolo_worker_value(*, value: Any, torch_module: Any) -> Any:
    """把 worker 生成的 CPU Tensor 转为普通 NumPy IPC 载荷。

    Windows ``spawn`` DataLoader 直接传 Tensor 时会为每批创建共享内存映射，
    长训练的 worker working set 会持续保持历史高水位。图像增强仍在 worker
    并行执行，只把出站 Tensor 转成 NumPy；主进程搬到训练设备时再恢复 Tensor。
    """

    if torch_module.is_tensor(value):
        # ``Tensor.numpy()`` 返回的 ndarray 仍以 Tensor 作为 ``base``。Windows
        # DataLoader 的 multiprocessing.Queue 在后台序列化该数组时，历史 batch
        # 的 Tensor storage 会在 worker 内按 batch 阶梯式滞留；大 batch 训练
        # 两轮即可占用数十 GiB。这里必须返回独立拥有内存的 C-contiguous 数组，
        # 让当前 Tensor 在 collate 返回后立即释放，后续 IPC 只持有 NumPy 内存。
        return value.detach().cpu().numpy().copy(order="C")
    if is_dataclass(value) and not isinstance(value, type):
        return replace(
            value,
            **{
                field.name: serialize_yolo_worker_value(
                    value=getattr(value, field.name),
                    torch_module=torch_module,
                )
                for field in fields(value)
            },
        )
    if isinstance(value, dict):
        return {
            key: serialize_yolo_worker_value(
                value=item,
                torch_module=torch_module,
            )
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(
            serialize_yolo_worker_value(value=item, torch_module=torch_module)
            for item in value
        )
    if isinstance(value, list):
        return [
            serialize_yolo_worker_value(value=item, torch_module=torch_module)
            for item in value
        ]
    return value


__all__ = ["serialize_yolo_worker_value"]
