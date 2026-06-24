"""obb 内部链烟雾验证。"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import torch

from backend.service.application.models.yolo_core_common.losses.obb_loss import compute_obb_loss
from backend.service.application.models.yolo_core_common.model_builders import build_yolo_model
from backend.service.application.runtime.predictors.yolov8.obb.postprocess import (
    build_yolov8_obb_runtime_instances,
)


def test_obb_model_can_build_and_forward():
    """验证 obb 模型可以构建并完成前向推理。"""
    overrides = {"ne": 1}
    model = build_yolo_model(model_type="yolov8", task_type="obb", model_scale="nano", num_classes=1, model_config_overrides=overrides)
    model.eval()
    with torch.no_grad():
        output = model(torch.randn(1, 3, 256, 256))
    assert output is not None
    assert output.ndim == 3
    assert int(output.shape[2]) == 6


def test_obb26_model_can_build_and_forward():
    """验证 OBB26 普通推理返回官方 processed 输出和 raw head 输出。"""
    overrides = {"ne": 1}
    model = build_yolo_model(model_type="yolo26", task_type="obb", model_scale="nano", num_classes=1, model_config_overrides=overrides)
    model.eval()
    with torch.no_grad():
        prediction, raw_outputs = model(torch.randn(1, 3, 256, 256))
    assert prediction is not None
    assert prediction.ndim == 3
    assert int(prediction.shape[2]) == 7
    assert isinstance(raw_outputs, dict)
    assert set(raw_outputs) == {"one2many", "one2one"}


def test_obb26_loss_can_backward_with_e2e_outputs():
    """验证 OBB26 E2E obb loss 可以完成反向传播。"""

    model = build_yolo_model(model_type="yolo26", task_type="obb", model_scale="nano", num_classes=2)
    model.train()
    outputs = model(torch.randn(1, 3, 64, 64))
    raw_outputs = outputs["one2many"] if isinstance(outputs, dict) and "one2many" in outputs else outputs

    loss_dict = compute_obb_loss(
        torch=torch,
        model=model,
        raw_outputs=raw_outputs,
        batch_targets=(
            SimpleNamespace(
                boxes_xywhr=((24.0, 24.0, 20.0, 12.0, 0.15),),
                category_indexes=(1,),
            ),
        ),
        num_classes=2,
    )

    assert torch.isfinite(loss_dict["loss"]).item() is True
    loss_dict["loss"].backward()
    grad_tensors = [parameter.grad for parameter in model.parameters() if parameter.grad is not None]
    assert grad_tensors
    assert all(torch.isfinite(gradient).all().item() for gradient in grad_tensors)


def test_obb_prediction_array_postprocess():
    """验证 obb 预测数组可以后处理。"""
    labels = ("person",)
    prediction = np.random.randn(1, 100, 4 + 1 + 1).astype(np.float32)
    prediction[:, :, :4] = np.abs(prediction[:, :, :4]) * 300
    prediction[:, :, 4] = 0.9
    prediction[:, :, 5] = 0.0
    instances = build_yolov8_obb_runtime_instances(
        np_module=np,
        prediction_array=prediction,
        labels=labels,
        score_threshold=0.3,
        resize_ratio=1.0,
        image_width=256,
        image_height=256,
    )
    assert isinstance(instances, tuple)
    for inst in instances:
        assert len(inst.bbox_xyxy) == 4
        assert 0.0 <= inst.score <= 1.0
        assert inst.angle is not None


def test_obb_runtime_contracts_importable():
    from backend.service.application.runtime.contracts.obb.prediction import (
        ObbPredictionExecutionResult, ObbPredictionInstance,
        ObbPredictionRequest, ObbRuntimeSessionInfo, ObbRuntimeTensorSpec,
    )

    assert ObbPredictionExecutionResult
    assert ObbPredictionInstance
    assert ObbPredictionRequest
    assert ObbRuntimeSessionInfo
    assert ObbRuntimeTensorSpec
