"""YOLOX PyTorch 运行时辅助函数。"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any


def build_yolox_autocast_context(
    *,
    torch_module: Any,
    device: str,
    precision: str,
):
    """按当前 precision 构建 YOLOX 自动混合精度上下文。"""

    if precision != "fp16" or not device.startswith("cuda"):
        return nullcontext()

    return torch_module.autocast(device_type="cuda", dtype=torch_module.float16)
