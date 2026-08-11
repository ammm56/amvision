"""模型评估阶段的运行模式生命周期。"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


@contextmanager
def evaluating_model(model: Any) -> Iterator[None]:
    """临时切换到 eval mode，并在成功或异常退出时恢复原模式。"""

    previous_training_mode = bool(model.training)
    model.eval()
    try:
        yield
    finally:
        model.train(previous_training_mode)


__all__ = ["evaluating_model"]
