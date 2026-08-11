"""YOLO loss assignment dtype 规则测试。"""

from __future__ import annotations

import pytest

from backend.service.application.models.yolo_core_common.losses.assignment import (
    write_assignment_quality_scores,
)


def test_assignment_quality_score_is_cast_to_fp16_target_dtype() -> None:
    """FP32 几何 quality score 必须能安全写入 FP16 分类 target。"""

    torch = pytest.importorskip("torch")
    target_scores = torch.zeros((3, 2), dtype=torch.float16)
    foreground_mask = torch.tensor([True, False, True])
    gt_classes = torch.tensor([1, 0])
    assigned_indices = torch.tensor([0, 1])
    quality_scores = torch.tensor([0.75, 0.5], dtype=torch.float32)

    write_assignment_quality_scores(
        target_scores=target_scores,
        foreground_mask=foreground_mask,
        gt_classes=gt_classes,
        assigned_gt_indices=assigned_indices,
        quality_scores=quality_scores,
    )

    assert target_scores.dtype == torch.float16
    assert target_scores.tolist() == [[0.0, 0.75], [0.0, 0.0], [0.5, 0.0]]
