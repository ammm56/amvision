"""YOLO OBB 训练验证的原始输出上下文。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


@contextmanager
def obb_validation_outputs(model: Any) -> Iterator[None]:
    """临时启用 OBB 头的原始输出，并在退出验证时恢复原设置。"""

    head = model.model[-1]
    previous = head.return_validation_outputs
    head.return_validation_outputs = True
    try:
        yield
    finally:
        head.return_validation_outputs = previous
