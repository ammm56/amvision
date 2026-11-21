"""Pose 训练期验证所需的原始模型输出。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


# 参数依次是验证模型、原始输出和批次标注，返回训练损失张量。
PoseValidationLoss = Callable[[Any, dict[str, Any], list[Any]], dict[str, Any]]


@contextmanager
def returning_pose_validation_outputs(model: Any, *, enabled: bool) -> Iterator[None]:
    """在验证模型一次前向中同时保留解码预测和计算损失所需的张量。"""

    if not enabled:
        yield
        return

    head = model.model[-1]
    previous = head.return_raw_for_validation
    head.return_raw_for_validation = True
    try:
        yield
    finally:
        head.return_raw_for_validation = previous
