"""RF-DETR COCO 指标契约测试。"""

from __future__ import annotations

import pytest
import torch

from backend.service.application.models.rfdetr_core.training.callbacks.coco_eval import (
    COCOEvalCallback,
)


def _perfect_detection_batch() -> tuple[list[dict[str, torch.Tensor]], list[dict[str, torch.Tensor]]]:
    """构造一个预测框与标注框完全一致的最小 batch。"""

    predictions = [
        {
            "boxes": torch.tensor([[10.0, 10.0, 20.0, 20.0]]),
            "scores": torch.tensor([0.99]),
            "labels": torch.tensor([0]),
        }
    ]
    targets = [
        {
            "boxes": torch.tensor([[10.0, 10.0, 20.0, 20.0]]),
            "labels": torch.tensor([0]),
        }
    ]
    return predictions, targets


def test_rfdetr_coco_metric_keeps_standard_map_with_extended_max_dets() -> None:
    """AR@500 不得使标准 COCO mAP@100 变成无效的 -1。"""

    callback = COCOEvalCallback(max_dets=500)
    callback.setup(trainer=None, pl_module=None, stage="fit")
    predictions, targets = _perfect_detection_batch()
    callback.map_metric.update(predictions, targets)
    callback.map_metric_max_dets.update(predictions, targets)

    metrics = callback.map_metric.compute()
    extended_metrics = callback.map_metric_max_dets.compute()

    assert callback.map_metric.max_detection_thresholds == [1, 10, 100]
    assert callback.map_metric_max_dets.max_detection_thresholds == [1, 100, 500]
    assert float(metrics["map"]) == pytest.approx(1.0)
    assert float(metrics["map_50"]) == pytest.approx(1.0)
    assert float(extended_metrics["mar_500"]) == pytest.approx(1.0)

    callback.teardown(trainer=None, pl_module=None, stage="fit")
    assert callback.map_metric is None
    assert callback.map_metric_max_dets is None
    assert callback.map_metric_ema is None
    assert callback.map_metric_ema_max_dets is None


def test_rfdetr_coco_standard_map_is_not_replaced_by_dense_recall_limit() -> None:
    """第 101 个低分正确框只影响 AR@500，不得进入标准 AP@100。"""

    false_boxes = torch.tensor(
        [[100.0 + index, 100.0, 101.0 + index, 101.0] for index in range(100)]
    )
    correct_box = torch.tensor([[10.0, 10.0, 20.0, 20.0]])
    predictions = [
        {
            "boxes": torch.cat((false_boxes, correct_box), dim=0),
            "scores": torch.linspace(1.0, 0.0, 101),
            "labels": torch.zeros(101, dtype=torch.int64),
        }
    ]
    targets = [
        {
            "boxes": correct_box,
            "labels": torch.tensor([0]),
        }
    ]
    callback = COCOEvalCallback(max_dets=500)
    callback.setup(trainer=None, pl_module=None, stage="fit")
    callback.map_metric.update(predictions, targets)
    callback.map_metric_max_dets.update(predictions, targets)

    standard_metrics = callback.map_metric.compute()
    extended_metrics = callback.map_metric_max_dets.compute()

    assert float(standard_metrics["map"]) == pytest.approx(0.0)
    assert float(extended_metrics["mar_500"]) == pytest.approx(1.0)
    callback.teardown(trainer=None, pl_module=None, stage="fit")


def test_rfdetr_coco_metric_rejects_max_dets_below_standard_ap_limit() -> None:
    """标准 COCO AP 必须保留 maxDets=100。"""

    with pytest.raises(ValueError, match="100"):
        COCOEvalCallback(max_dets=50)
