"""Pose 损失升级回归测试。"""

from __future__ import annotations

from types import SimpleNamespace

import torch

from backend.service.application.models.pose_loss import compute_pose_loss
from backend.service.application.models.yolo_primary_model_configs import build_yolo_primary_model


def test_compute_pose_loss_exposes_visibility_loss_for_standard_pose() -> None:
    """验证标准 pose 训练损失会显式产出 visibility_loss。"""

    model = build_yolo_primary_model(
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

    model = build_yolo_primary_model(
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


def _build_pose_target() -> SimpleNamespace:
    """构造一份最小 pose 训练目标。"""

    keypoints: list[float] = []
    for index in range(17):
        keypoints.extend(
            [
                12.0 + index * 0.8,
                14.0 + index * 0.7,
                2.0 if index % 2 == 0 else 1.0,
            ]
        )
    return SimpleNamespace(
        boxes_xyxy=((10.0, 10.0, 42.0, 52.0),),
        category_indexes=(0,),
        keypoints=(keypoints,),
    )
