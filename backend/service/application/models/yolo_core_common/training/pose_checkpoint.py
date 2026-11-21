"""读取 pose 训练权重记录的实际轮次。"""

from __future__ import annotations

import io
from typing import Any


def read_pose_checkpoint_epoch(
    *, torch_module: Any, checkpoint_bytes: bytes
) -> int | None:
    """从已保存的权重读取一基轮次，兼容无轮次的旧文件。"""

    if not checkpoint_bytes:
        return None
    payload = torch_module.load(
        io.BytesIO(checkpoint_bytes), map_location="cpu", weights_only=False
    )
    epoch = payload.get("epoch") if isinstance(payload, dict) else None
    return epoch if type(epoch) is int and epoch > 0 else None
