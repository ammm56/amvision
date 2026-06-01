"""YOLO 主线 detection 训练增强与 E2E 路径测试。"""

from __future__ import annotations

import random
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
import torch

from backend.service.application.models.yolo_primary_detection_model import (
    build_yolo_primary_detection_model,
)
from backend.service.application.models.yolo_primary_detection_training import (
    _PreparedTrainingTarget,
    _ResolvedTrainingAnnotation,
    _ResolvedTrainingSample,
    _build_training_batch,
    _compute_e2e_detection_loss,
    _resolve_detection_augmentation_options,
    _unwrap_e2e_detection_outputs,
)


def test_build_training_batch_flip_prob_one_flips_bbox_horizontally(
    tmp_path: Path,
) -> None:
    """验证 detection 训练 batch 在 flip_prob=1 时会正确翻转 bbox。"""

    sample = _write_detection_sample(
        tmp_path=tmp_path,
        file_name="flip-sample.jpg",
        color=(60, 120, 180),
        bbox_xyxy=(10.0, 20.0, 30.0, 50.0),
    )
    images, batch_targets = _build_training_batch(
        imports=SimpleNamespace(cv2=cv2, np=np, torch=torch),
        samples=[sample],
        input_size=(64, 64),
        device="cpu",
        runtime_precision="fp32",
        augment_training=True,
        available_samples=(sample,),
        augmentation_options=_resolve_detection_augmentation_options(
            {
                "flip_prob": 1.0,
                "hsv_prob": 0.0,
                "mosaic_prob": 0.0,
                "mixup_prob": 0.0,
                "degrees": 0.0,
                "translate": 0.0,
                "shear": 0.0,
            }
        ),
    )

    assert tuple(images.shape) == (1, 3, 64, 64)
    assert len(batch_targets) == 1
    assert len(batch_targets[0].boxes_xyxy) == 1
    x1, y1, x2, y2 = batch_targets[0].boxes_xyxy[0]
    assert x1 == pytest.approx(44.8, abs=1e-3)
    assert y1 == pytest.approx(12.8, abs=1e-3)
    assert x2 == pytest.approx(57.6, abs=1e-3)
    assert y2 == pytest.approx(32.0, abs=1e-3)


def test_build_training_batch_mosaic_mixup_keeps_boxes_in_bounds(
    tmp_path: Path,
) -> None:
    """验证 Mosaic + MixUp 进入正式训练 batch 后 bbox 仍保持在输入范围内。"""

    samples = tuple(
        _write_detection_sample(
            tmp_path=tmp_path,
            file_name=f"mosaic-sample-{index}.jpg",
            color=(40 + index * 20, 90 + index * 10, 140 + index * 5),
            bbox_xyxy=(10.0 + index, 12.0 + index, 34.0 + index, 40.0 + index),
        )
        for index in range(4)
    )
    random.seed(0)
    images, batch_targets = _build_training_batch(
        imports=SimpleNamespace(cv2=cv2, np=np, torch=torch),
        samples=[samples[0], samples[1]],
        input_size=(64, 64),
        device="cpu",
        runtime_precision="fp32",
        augment_training=True,
        available_samples=samples,
        augmentation_options=_resolve_detection_augmentation_options(
            {
                "flip_prob": 0.0,
                "hsv_prob": 0.0,
                "mosaic_prob": 1.0,
                "enable_mixup": True,
                "mixup_prob": 1.0,
                "degrees": 0.0,
                "translate": 0.0,
                "shear": 0.0,
                "mosaic_scale": [1.0, 1.0],
                "mixup_scale": [1.0, 1.0],
            }
        ),
    )

    assert tuple(images.shape) == (2, 3, 64, 64)
    for target in batch_targets:
        assert len(target.boxes_xyxy) >= 1
        for x1, y1, x2, y2 in target.boxes_xyxy:
            assert 0.0 <= x1 < x2 <= 64.0
            assert 0.0 <= y1 < y2 <= 64.0


def test_yolo26_e2e_loss_path_runs_with_dual_branch_outputs() -> None:
    """验证 YOLO26 E2E 双分支损失路径可以稳定执行。"""

    model = build_yolo_primary_detection_model(
        model_type="yolo26",
        model_scale="nano",
        num_classes=2,
    )
    model.train()
    outputs = model(torch.randn(1, 3, 64, 64))
    one2many_outputs, one2one_outputs = _unwrap_e2e_detection_outputs(outputs)

    assert "boxes" in one2many_outputs
    assert "scores" in one2many_outputs
    assert "boxes" in one2one_outputs
    assert "scores" in one2one_outputs

    loss_components = _compute_e2e_detection_loss(
        imports=SimpleNamespace(torch=torch),
        model=model,
        raw_outputs=(one2many_outputs, one2one_outputs),
        batch_targets=(
            _PreparedTrainingTarget(
                image_id=1,
                image_width=64,
                image_height=64,
                boxes_xyxy=((10.0, 10.0, 30.0, 30.0),),
                category_indexes=(1,),
            ),
        ),
        num_classes=2,
        class_loss_weight=0.5,
        box_loss_weight=7.5,
        dfl_loss_weight=1.5,
        assign_topk=10,
        assign_alpha=0.5,
        assign_beta=6.0,
        e2e_o2m_weight=0.8,
        e2e_o2o_weight=0.2,
    )

    assert torch.isfinite(loss_components["loss"]).item() is True
    assert torch.isfinite(loss_components["class_loss"]).item() is True
    assert torch.isfinite(loss_components["box_loss"]).item() is True
    assert torch.isfinite(loss_components["dfl_loss"]).item() is True
    assert torch.isfinite(loss_components["one2many_loss"]).item() is True
    assert torch.isfinite(loss_components["one2one_loss"]).item() is True


def _write_detection_sample(
    *,
    tmp_path: Path,
    file_name: str,
    color: tuple[int, int, int],
    bbox_xyxy: tuple[float, float, float, float],
) -> _ResolvedTrainingSample:
    """写入一张最小训练图片并返回解析后的训练样本。"""

    image_path = tmp_path / file_name
    image = np.full((100, 100, 3), color, dtype=np.uint8)
    assert cv2.imwrite(str(image_path), image) is True
    return _ResolvedTrainingSample(
        image_id=1,
        image_path=image_path,
        image_width=100,
        image_height=100,
        annotations=(
            _ResolvedTrainingAnnotation(
                category_index=0,
                category_id=1,
                bbox_xyxy=bbox_xyxy,
            ),
        ),
    )
