"""普通 YOLO detection loss 报告口径回归测试。"""

from __future__ import annotations

import math

import pytest

from backend.service.application.models.yolo_core_common.training import (
    YoloDetectionLossAccumulator,
    normalize_yolo_detection_loss_metrics,
)
from backend.service.application.models.yolo26_core.training.detection_support import (
    serialize_yolo26_spatial_loss_metrics,
)


def test_normalize_yolo_detection_loss_only_unscales_total_loss() -> None:
    """total loss 按 batch 样本数还原，分量保持其已有样本均值口径。"""

    metrics = normalize_yolo_detection_loss_metrics(
        loss_components={
            "loss": 32.0,
            "class_loss": 1.0,
            "box_loss": 0.25,
            "dfl_loss": 0.75,
        },
        batch_sample_count=16,
    )

    assert metrics == {
        "loss": 2.0,
        "class_loss": 1.0,
        "box_loss": 0.25,
        "dfl_loss": 0.75,
    }


def test_yolo_detection_loss_accumulator_weights_partial_batch_by_samples() -> None:
    """最后一个不足 batch 只能按真实样本数参与 epoch 均值。"""

    accumulator = YoloDetectionLossAccumulator()
    accumulator.add(
        metrics={
            "loss": 2.0,
            "class_loss": 1.0,
            "box_loss": 0.5,
            "dfl_loss": 0.5,
        },
        batch_sample_count=16,
    )
    accumulator.add(
        metrics={
            "loss": 10.0,
            "class_loss": 5.0,
            "box_loss": 2.5,
            "dfl_loss": 2.5,
        },
        batch_sample_count=4,
    )

    assert accumulator.sample_count == 20
    assert accumulator.mean() == {
        "loss": 3.6,
        "class_loss": 1.8,
        "box_loss": 0.9,
        "dfl_loss": 0.9,
    }


def test_yolo26_reports_regression_component_as_l1_loss() -> None:
    """YOLO26 reg_max=1 的第三项不得在公开指标里误标为 DFL。"""

    assert serialize_yolo26_spatial_loss_metrics(
        {
            "loss": 2.0,
            "class_loss": 1.0,
            "box_loss": 0.5,
            "dfl_loss": 0.5,
        }
    ) == {
        "loss": 2.0,
        "class_loss": 1.0,
        "box_loss": 0.5,
        "l1_loss": 0.5,
    }


@pytest.mark.parametrize("invalid_value", [math.nan, math.inf, -math.inf])
def test_yolo_detection_loss_metrics_reject_non_finite_values(
    invalid_value: float,
) -> None:
    """NaN/Inf 不得进入训练历史和页面指标。"""

    with pytest.raises(ValueError, match="不是有限数值"):
        normalize_yolo_detection_loss_metrics(
            loss_components={
                "loss": invalid_value,
                "class_loss": 1.0,
                "box_loss": 0.5,
                "dfl_loss": 0.5,
            },
            batch_sample_count=1,
        )
