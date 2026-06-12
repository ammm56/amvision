"""obb 内部链烟雾验证。"""

from __future__ import annotations

import numpy as np
import torch

from backend.service.application.models.yolo_primary_model_configs import build_yolo_primary_model
from backend.service.application.runtime.yolo_primary_obb_predictor import _build_obb_instances


def test_obb_model_can_build_and_forward():
    """验证 obb 模型可以构建并完成前向推理。"""
    overrides = {"ne": 1}
    model = build_yolo_primary_model(model_type="yolov8", task_type="obb", model_scale="nano", num_classes=1, model_config_overrides=overrides)
    model.eval()
    with torch.no_grad():
        output = model(torch.randn(1, 3, 256, 256))
    assert output is not None
    assert output.ndim == 3
    assert int(output.shape[2]) == 6


def test_obb26_model_can_build_and_forward():
    """验证 OBB26 模型推理输出包含 bbox、score 和 angle。"""
    overrides = {"ne": 1}
    model = build_yolo_primary_model(model_type="yolo26", task_type="obb", model_scale="nano", num_classes=1, model_config_overrides=overrides)
    model.eval()
    with torch.no_grad():
        output = model(torch.randn(1, 3, 256, 256))
    assert output is not None
    assert output.ndim == 3
    assert int(output.shape[2]) == 6


def test_obb_prediction_array_postprocess():
    """验证 obb 预测数组可以后处理。"""
    labels = ("person",)
    prediction = np.random.randn(1, 100, 4 + 1 + 1).astype(np.float32)
    prediction[:, :, :4] = np.abs(prediction[:, :, :4]) * 300
    prediction[:, :, 4] = 0.9
    prediction[:, :, 5] = 0.0
    instances = _build_obb_instances(np_module=np, prediction_array=prediction, labels=labels, score_threshold=0.3, resize_ratio=1.0, image_width=256, image_height=256)
    assert isinstance(instances, tuple)
    for inst in instances:
        assert len(inst.bbox_xyxy) == 4
        assert 0.0 <= inst.score <= 1.0
        assert inst.angle is not None


def test_obb_runtime_contracts_importable():
    from backend.service.application.runtime.obb_runtime_contracts import (
        ObbPredictionExecutionResult, ObbPredictionInstance,
        ObbPredictionRequest, ObbRuntimeSessionInfo, ObbRuntimeTensorSpec,
    )
