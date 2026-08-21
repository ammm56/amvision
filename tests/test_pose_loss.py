"""Pose 损失升级回归测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import torch

from backend.service.application.models.yolo26_core.losses import (
    compute_yolo26_pose_loss,
)
from backend.service.application.models.yolo_core_common.losses.pose_loss import compute_pose_loss
from backend.service.application.models.yolo_core_common.model_builders import build_yolo_model


def test_compute_pose_loss_exposes_visibility_loss_for_standard_pose() -> None:
    """验证标准 pose 训练损失会显式产出 visibility_loss。"""

    model = build_yolo_model(
        model_type="yolov8",
        task_type="pose",
        model_scale="nano",
        num_classes=1,
    )
    model.train()
    raw_outputs = model(torch.randn(1, 3, 64, 64))

    loss_dict = compute_pose_loss(
        torch=torch,
        model=model,
        raw_outputs=raw_outputs,
        batch_targets=(_build_pose_target(),),
        num_classes=1,
        kpt_shape=(17, 3),
    )

    assert "visibility_loss" in loss_dict
    assert torch.isfinite(loss_dict["loss"]).item() is True
    assert torch.isfinite(loss_dict["kpt_loss"]).item() is True
    assert torch.isfinite(loss_dict["visibility_loss"]).item() is True


def test_compute_pose_loss_exposes_rle_loss_for_pose26() -> None:
    """验证 Pose26 训练损失会显式产出 rle_loss。"""

    model = build_yolo_model(
        model_type="yolo26",
        task_type="pose",
        model_scale="nano",
        num_classes=1,
    )
    model.train()
    raw_outputs = model(torch.randn(1, 3, 64, 64))
    if isinstance(raw_outputs, dict) and "one2many" in raw_outputs:
        raw_outputs = raw_outputs["one2many"]

    loss_dict = compute_pose_loss(
        torch=torch,
        model=model,
        raw_outputs=raw_outputs,
        batch_targets=(_build_pose_target(),),
        num_classes=1,
        kpt_shape=(17, 3),
    )

    assert "visibility_loss" in loss_dict
    assert "rle_loss" in loss_dict
    assert torch.isfinite(loss_dict["loss"]).item() is True
    assert torch.isfinite(loss_dict["kpt_loss"]).item() is True
    assert torch.isfinite(loss_dict["visibility_loss"]).item() is True
    assert torch.isfinite(loss_dict["rle_loss"]).item() is True


def test_yolo26_pose_loss_calls_realnvp_once_for_the_whole_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证一个分支的整批 pose loss 只调用一次 RealNVP。"""

    def assign_two_foreground_anchors(*, torch_module, pred_boxes, **_kwargs):
        foreground_mask = torch_module.zeros(
            pred_boxes.shape[0],
            dtype=torch_module.bool,
            device=pred_boxes.device,
        )
        foreground_mask[:2] = True
        assigned_gt_indices = torch_module.zeros(
            pred_boxes.shape[0],
            dtype=torch_module.long,
            device=pred_boxes.device,
        )
        quality_scores = pred_boxes.new_zeros(pred_boxes.shape[0])
        quality_scores[:2] = 1.0
        return {
            "foreground_mask": foreground_mask,
            "assigned_gt_indices": assigned_gt_indices,
            "quality_scores": quality_scores,
        }

    monkeypatch.setattr(
        "backend.service.application.models.yolo26_core.losses.pose."
        "assign_yolo26_pose_targets",
        assign_two_foreground_anchors,
    )

    model = build_yolo_model(
        model_type="yolo26",
        task_type="pose",
        model_scale="nano",
        num_classes=1,
    )
    model.train()
    raw_outputs = model(torch.randn(2, 3, 128, 128))
    if isinstance(raw_outputs, dict) and "one2many" in raw_outputs:
        raw_outputs = raw_outputs["one2many"]

    flow_model = model.model[-1].flow_model
    original_log_prob = flow_model.log_prob
    log_prob_call_count = 0

    def counted_log_prob(value):
        nonlocal log_prob_call_count
        log_prob_call_count += 1
        return original_log_prob(value)

    flow_model.log_prob = counted_log_prob
    runtime_metrics: dict[str, float] = {}
    loss_dict = compute_yolo26_pose_loss(
        torch=torch,
        model=model,
        raw_outputs=raw_outputs,
        batch_targets=(
            _build_pose_target(coordinate_scale=2.0),
            _build_pose_target(coordinate_scale=2.0),
        ),
        num_classes=1,
        kpt_shape=(17, 3),
        runtime_metrics=runtime_metrics,
    )

    assert log_prob_call_count == 1
    assert runtime_metrics == {
        "foreground_count": 4.0,
        "rle_error_count": 68.0,
        "rle_image_count": 2.0,
    }
    assert torch.isfinite(loss_dict["loss"]).item() is True


def _build_pose_target(*, coordinate_scale: float = 1.0) -> SimpleNamespace:
    """构造一份最小 pose 训练目标。"""

    keypoints: list[float] = []
    for index in range(17):
        keypoints.extend(
            [
                (12.0 + index * 0.8) * coordinate_scale,
                (14.0 + index * 0.7) * coordinate_scale,
                2.0 if index % 2 == 0 else 1.0,
            ]
        )
    return SimpleNamespace(
        boxes_xyxy=(
            tuple(
                value * coordinate_scale
                for value in (10.0, 10.0, 42.0, 52.0)
            ),
        ),
        category_indexes=(0,),
        keypoints=[keypoints],
    )
