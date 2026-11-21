"""YOLO OBB 保存点的权重轮次。"""

from __future__ import annotations

import io
from typing import Any


def read_yolo_obb_checkpoint_epoch(
    *, torch_module: Any, checkpoint_bytes: bytes
) -> int | None:
    """从恢复训练沿用的 checkpoint 中读取其实际保存轮次。"""

    if not checkpoint_bytes:
        return None
    payload = torch_module.load(
        io.BytesIO(checkpoint_bytes),
        map_location="meta",
        weights_only=False,
    )
    epoch = payload.get("epoch") if isinstance(payload, dict) else None
    return epoch if type(epoch) is int and epoch > 0 else None
