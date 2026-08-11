"""YOLO 训练指标历史的公开序列化规则。"""

from __future__ import annotations

from collections.abc import Mapping


def build_yolo_epoch_history_item(
    *,
    epoch_index: int,
    metrics: Mapping[str, object],
) -> dict[str, object]:
    """构建同时包含对外轮次和内部索引的单轮指标。

    训练循环统一使用从 0 开始的 ``epoch_index``，公开指标文件统一使用从 1
    开始的 ``epoch``。两个字段同时保留，防止 UI、导出报告和 checkpoint
    恢复逻辑再次混用两种语义。
    """

    normalized_index = int(epoch_index)
    if normalized_index < 0:
        raise ValueError("epoch_index 必须大于等于 0")
    item = {str(name): value for name, value in metrics.items()}
    item["epoch"] = normalized_index + 1
    item["epoch_index"] = normalized_index
    return item


def build_yolo_completed_epoch_history_item(
    *,
    completed_epoch: int,
    metrics: Mapping[str, object],
) -> dict[str, object]:
    """把一基训练循环轮次安全转换为公开 history item。"""

    normalized_epoch = int(completed_epoch)
    if normalized_epoch < 1:
        raise ValueError("completed_epoch 必须大于等于 1")
    return build_yolo_epoch_history_item(
        epoch_index=normalized_epoch - 1,
        metrics=metrics,
    )


__all__ = [
    "build_yolo_completed_epoch_history_item",
    "build_yolo_epoch_history_item",
]
