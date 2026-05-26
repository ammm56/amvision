"""YOLOv8 detection 结构实现测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import torch

from backend.service.application.models.yolov8_detection_model import (
    build_yolov8_detection_model,
    load_yolov8_checkpoint,
)


def test_yolov8_detection_model_forward_returns_detection_tensor() -> None:
    """验证项目内 YOLOv8 结构可以完成一次前向。"""

    model = build_yolov8_detection_model(model_scale="n", num_classes=2)
    model.eval()

    with torch.inference_mode():
        prediction = model(torch.randn(1, 3, 64, 64))

    assert prediction.shape == (1, 84, 6)


def test_yolov8_detection_model_can_reload_project_checkpoint(tmp_path: Path) -> None:
    """验证项目内 YOLOv8 结构可以回读自身 checkpoint。"""

    checkpoint_path = tmp_path / "yolov8-project-native.pt"
    source_model = build_yolov8_detection_model(model_scale="n", num_classes=1)
    torch.save({"model_state_dict": source_model.state_dict()}, checkpoint_path)

    target_model = build_yolov8_detection_model(model_scale="n", num_classes=1)
    load_summary = load_yolov8_checkpoint(
        imports=SimpleNamespace(torch=torch),
        model=target_model,
        checkpoint_path=checkpoint_path,
    )

    assert load_summary["checkpoint_path"] == str(checkpoint_path)
    assert load_summary["unexpected_keys"] == []
