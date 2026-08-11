"""YOLO 非 detection 任务共享的 batch 进度契约。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class YoloTaskTrainingBatchProgress:
    """描述一个已完成 batch 的瞬时训练数据。

    ``epoch`` 使用零基索引，与现有 core epoch callback 保持一致；公开遥测层会转换为
    一基 ``epoch`` 和零基 ``epoch_index``。``train_metrics`` 只表示当前 batch，禁止
    写入 epoch 指标文件或 TaskEvent 表。
    """

    epoch: int
    max_epochs: int
    iteration: int
    max_iterations: int
    global_iteration: int
    total_iterations: int
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]


__all__ = ["YoloTaskTrainingBatchProgress"]
