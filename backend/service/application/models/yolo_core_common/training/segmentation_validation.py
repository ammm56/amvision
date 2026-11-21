"""YOLO segmentation 训练期验证损失。"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.training.validation_loss import (
    YoloValidationLossAccumulator,
)


SegmentationBatchLoss = Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]]


@contextmanager
def segmentation_validation_outputs(model: Any, *, enabled: bool) -> Iterator[None]:
    """仅在训练期验证额外保留 head 输出，保持模型及子层处于 eval 模式。"""
    if not enabled:
        yield
        return
    head = model.model[-1]
    previous = head.return_validation_outputs
    head.return_validation_outputs = True
    try:
        yield
    finally:
        head.return_validation_outputs = previous


class SegmentationValidationLoss:
    """累计按训练定义乘过 batch 大小的损失，并按实际样本数取平均。"""

    def __init__(self, compute: SegmentationBatchLoss | None) -> None:
        """接收训练损失回调，仅在回调存在时读取额外的 head 输出。"""
        self.compute = compute
        self.accumulator = YoloValidationLossAccumulator(all_components_are_sums=True)

    def consume(self, outputs: Any, targets: list[dict[str, Any]]) -> Any:
        """用同次前向的原始输出计算损失，并返回解码用的输出。"""
        if self.compute is None:
            return outputs
        predictions, raw_outputs = outputs
        if not isinstance(raw_outputs, dict):
            raise InvalidRequestError("segmentation 验证输出缺少原始 head 输出")
        self.accumulator.add_batch(
            payload=self.compute(raw_outputs, targets), sample_count=len(targets)
        )
        return predictions

    def metrics(self) -> dict[str, float]:
        """返回按有效验证样本数归一化的损失。"""
        return self.accumulator.metrics()


def weighted_segmentation_loss(
    loss_terms: Mapping[str, Any],
    weights: Mapping[str, float],
) -> dict[str, Any]:
    """计算训练使用的总损失和各分项，保留 YOLO26 one-to-one 展示口径。"""
    weighted_terms = {
        name: weight * loss_terms[name] for name, weight in weights.items()
    }
    reported = {
        name: weights[name] * loss_terms[f"reported_{name}"]
        if f"reported_{name}" in loss_terms
        else value
        for name, value in weighted_terms.items()
    }
    return {"loss": sum(weighted_terms.values()), **reported}
