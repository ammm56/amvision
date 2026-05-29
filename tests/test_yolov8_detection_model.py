"""YOLOv8 detection 结构实现测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import torch

from backend.service.application.models.yolo_primary_detection_model import (
    build_yolo_primary_detection_model,
    load_yolo_primary_checkpoint,
)
from backend.service.application.models.yolo_primary_model_configs import build_yolo_primary_model


def test_yolov8_detection_model_forward_returns_detection_tensor() -> None:
    """验证项目内 YOLOv8 结构可以完成一次前向。"""

    model = build_yolo_primary_detection_model(
        model_type="yolov8",
        model_scale="nano",
        num_classes=2,
    )
    model.eval()

    with torch.inference_mode():
        prediction = model(torch.randn(1, 3, 64, 64))

    assert prediction.shape == (1, 84, 6)


def test_yolov8_detection_model_can_reload_project_checkpoint(tmp_path: Path) -> None:
    """验证项目内 YOLOv8 结构可以回读自身 checkpoint。"""

    checkpoint_path = tmp_path / "yolov8-project-native.pt"
    source_model = build_yolo_primary_detection_model(
        model_type="yolov8",
        model_scale="nano",
        num_classes=1,
    )
    torch.save({"model_state_dict": source_model.state_dict()}, checkpoint_path)

    target_model = build_yolo_primary_detection_model(
        model_type="yolov8",
        model_scale="nano",
        num_classes=1,
    )
    load_summary = load_yolo_primary_checkpoint(
        imports=SimpleNamespace(torch=torch),
        model=target_model,
        checkpoint_path=checkpoint_path,
    )

    assert load_summary["checkpoint_path"] == str(checkpoint_path)
    assert load_summary["unexpected_keys"] == []


def test_yolov8_checkpoint_loader_tolerates_class_head_shape_mismatch(tmp_path: Path) -> None:
    """验证加载不同类别数 checkpoint 时会跳过不兼容分类头。"""

    checkpoint_path = tmp_path / "yolov8-class-mismatch.pt"
    source_model = build_yolo_primary_detection_model(
        model_type="yolov8",
        model_scale="nano",
        num_classes=2,
    )
    torch.save({"model_state_dict": source_model.state_dict()}, checkpoint_path)

    target_model = build_yolo_primary_detection_model(
        model_type="yolov8",
        model_scale="nano",
        num_classes=1,
    )
    load_summary = load_yolo_primary_checkpoint(
        imports=SimpleNamespace(torch=torch),
        model=target_model,
        checkpoint_path=checkpoint_path,
    )

    assert load_summary["checkpoint_path"] == str(checkpoint_path)
    assert load_summary["shape_mismatch_keys"]
    assert any(".cv3." in key for key in load_summary["shape_mismatch_keys"])


def test_yolo11_detection_model_forward_returns_detection_tensor() -> None:
    """验证共享层已经可以构建并前向 YOLO11 detection 模型。"""

    model = build_yolo_primary_detection_model(
        model_type="yolo11",
        model_scale="nano",
        num_classes=2,
    )
    model.eval()

    with torch.inference_mode():
        prediction = model(torch.randn(1, 3, 64, 64))

    assert prediction.shape == (1, 84, 6)


def test_yolo26_detection_model_forward_returns_detection_tensor() -> None:
    """验证共享层已经可以构建并前向 YOLO26 detection 模型。"""

    model = build_yolo_primary_detection_model(
        model_type="yolo26",
        model_scale="nano",
        num_classes=2,
    )
    model.eval()

    with torch.inference_mode():
        prediction = model(torch.randn(1, 3, 64, 64))

    assert prediction.shape == (1, 84, 6)


def test_yolo11_segmentation_model_forward_returns_prediction_and_proto() -> None:
    """验证共享任务配置已经可以构建并前向 YOLO11 segmentation 模型。"""

    model = build_yolo_primary_model(
        model_type="yolo11",
        task_type="segmentation",
        model_scale="nano",
        num_classes=2,
    )
    model.eval()

    with torch.inference_mode():
        prediction, proto = model(torch.randn(1, 3, 64, 64))

    assert prediction.shape == (1, 84, 38)
    assert proto.shape[0] == 1
    assert proto.shape[1] == 32


def test_yolo26_classification_model_forward_returns_probabilities_and_logits() -> None:
    """验证共享任务配置已经可以构建并前向 YOLO26 classification 模型。"""

    model = build_yolo_primary_model(
        model_type="yolo26",
        task_type="classification",
        model_scale="nano",
        num_classes=3,
    )
    model.eval()

    with torch.inference_mode():
        probabilities, logits = model(torch.randn(1, 3, 64, 64))

    assert probabilities.shape == (1, 3)
    assert logits.shape == (1, 3)
