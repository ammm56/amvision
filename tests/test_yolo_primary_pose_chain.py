"""pose 内部链烟雾验证。"""

from __future__ import annotations

import numpy as np
import torch

from backend.service.application.models.yolo_primary_model_configs import build_yolo_primary_model
from backend.service.application.runtime.yolo_primary_pose_predictor import _build_pose_instances


def test_pose_model_can_build_and_forward():
    """验证 pose 模型可以构建并完成前向推理。"""
    model = build_yolo_primary_model(model_type="yolov8", task_type="pose", model_scale="n", num_classes=1)
    model.eval()
    with torch.no_grad():
        output = model(torch.randn(1, 3, 256, 256))
    assert output is not None


def test_pose26_model_can_build_and_forward():
    """验证 Pose26 模型可以构建并完成前向推理。"""
    model = build_yolo_primary_model(model_type="yolo26", task_type="pose", model_scale="n", num_classes=1)
    model.eval()
    with torch.no_grad():
        output = model(torch.randn(1, 3, 256, 256))
    assert output is not None


def test_segment26_model_can_build_and_forward():
    """验证 Segment26 模型可以构建并完成前向推理。"""
    model = build_yolo_primary_model(model_type="yolo26", task_type="segmentation", model_scale="n", num_classes=1)
    model.eval()
    with torch.no_grad():
        output = model(torch.randn(1, 3, 256, 256))
    assert output is not None


def test_pose_prediction_array_postprocess():
    """验证 pose 预测数组可以完成后处理。"""
    labels = ("person",)
    prediction = np.random.randn(1, 100, 4 + 1 + 17 * 3).astype(np.float32)
    prediction[:, :, :4] = np.abs(prediction[:, :, :4]) * 300
    prediction[:, :, 4] = 0.9
    instances, kpt_shape = _build_pose_instances(
        np_module=np, prediction_array=prediction, labels=labels,
        score_threshold=0.3, keypoint_confidence_threshold=0.5,
        resize_ratio=1.0, image_width=256, image_height=256,
        input_size=(256, 256), default_kpt_shape=(17, 3),
    )
    assert isinstance(instances, tuple)
    assert kpt_shape == (17, 3)
    for inst in instances:
        assert len(inst.bbox_xyxy) == 4
        assert 0.0 <= inst.score <= 1.0


def test_pose_runtime_contracts_importable():
    from backend.service.application.runtime.pose_runtime_contracts import (
        PosePredictionExecutionResult, PosePredictionInstance,
        PosePredictionKeypoint, PosePredictionRequest,
        PoseRuntimeSessionInfo, PoseRuntimeTensorSpec,
    )


def test_pose_predictor_classes_importable():
    from backend.service.application.runtime.yolo_primary_pose_predictor import (
        OnnxRuntimeYoloPrimaryPoseRuntimeSession,
        OpenVINOYoloPrimaryPoseRuntimeSession,
        PyTorchYoloPrimaryPoseRuntimeSession,
        TensorRTYoloPrimaryPoseRuntimeSession,
    )


def test_pose_model_runtime_importable():
    from backend.service.application.runtime.pose_model_runtime import (
        DefaultPoseModelRuntime, PoseModelRuntimeRegistry,
    )
