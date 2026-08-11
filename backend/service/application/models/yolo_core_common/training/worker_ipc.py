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
        return value.detach().cpu().numpy()
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
