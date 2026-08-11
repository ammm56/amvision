"""普通 YOLO 训练期验证调度。"""

from __future__ import annotations


def should_run_yolo_validation(
    *,
    epoch_index: int,
    max_epochs: int,
    evaluation_interval: int,
    has_validation_samples: bool,
) -> bool:
    """按用户可见的一基完成轮数决定是否执行 validation。

    训练循环内部 ``epoch_index`` 从 0 开始，但 ``evaluation_interval=20`` 的
    公开语义是完成第 20、40、60 轮后评估。最后一轮始终评估一次；没有验证
    样本时任何轮次都不得伪造 validation。
    """

    if not has_validation_samples:
        return False
    completed_epochs = max(0, int(epoch_index)) + 1
    resolved_max_epochs = max(1, int(max_epochs))
    resolved_interval = max(1, int(evaluation_interval))
    return (
        completed_epochs % resolved_interval == 0
        or completed_epochs >= resolved_max_epochs
    )


__all__ = ["should_run_yolo_validation"]
