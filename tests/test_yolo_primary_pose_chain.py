"""pose 内部链烟雾验证。"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import torch

from backend.service.application.models.pose_loss import compute_pose_loss
from backend.service.application.models.yolo_primary_model_configs import build_yolo_primary_model
from backend.service.application.runtime.yolo_primary_pose_predictor import _build_pose_instances


def test_pose_model_can_build_and_forward():
    """验证 pose 模型可以构建并完成前向推理。"""
    model = build_yolo_primary_model(model_type="yolov8", task_type="pose", model_scale="nano", num_classes=1)
    model.eval()
    with torch.no_grad():
        output = model(torch.randn(1, 3, 256, 256))
    assert output is not None


def test_pose26_model_can_build_and_forward():
    """验证 Pose26 模型可以构建并完成前向推理。"""
    model = build_yolo_primary_model(model_type="yolo26", task_type="pose", model_scale="nano", num_classes=1)
    model.eval()
    with torch.no_grad():
        output = model(torch.randn(1, 3, 256, 256))
    assert output is not None


def test_pose26_loss_can_backward_with_e2e_outputs():
    """验证 Pose26 E2E pose loss 可以完成反向传播。"""

    model = build_yolo_primary_model(model_type="yolo26", task_type="pose", model_scale="nano", num_classes=2)
    model.train()
    outputs = model(torch.randn(1, 3, 64, 64))
    raw_outputs = outputs["one2many"] if isinstance(outputs, dict) and "one2many" in outputs else outputs
    keypoints = tuple((16.0 + index * 0.5, 16.0 + index * 0.25, 2.0) for index in range(17))

    loss_dict = compute_pose_loss(
        torch=torch,
        model=model,
        raw_outputs=raw_outputs,
        batch_targets=(
            SimpleNamespace(
                boxes_xyxy=((10.0, 10.0, 32.0, 34.0),),
                category_indexes=(1,),
                keypoints=(keypoints,),
            ),
        ),
        num_classes=2,
    )

    assert torch.isfinite(loss_dict["loss"]).item() is True
    loss_dict["loss"].backward()
    grad_tensors = [parameter.grad for parameter in model.parameters() if parameter.grad is not None]
    assert grad_tensors
    assert all(torch.isfinite(gradient).all().item() for gradient in grad_tensors)


def test_segment26_model_can_build_and_forward():
    """验证 Segment26 模型可以构建并完成前向推理。"""
    model = build_yolo_primary_model(model_type="yolo26", task_type="segmentation", model_scale="nano", num_classes=1)
    model.eval()
    with torch.no_grad():
        output = model(torch.randn(1, 3, 256, 256))
    assert isinstance(output, tuple)
    assert len(output) == 2
    prediction, proto = output
    assert prediction is not None
    assert proto is not None
    assert prediction.ndim == 3
    assert proto.ndim == 4


def test_segment26_model_training_output_contains_proto():
    """验证 Segment26 训练态原始输出包含 proto。"""
    model = build_yolo_primary_model(model_type="yolo26", task_type="segmentation", model_scale="nano", num_classes=1)
    model.train()
    output = model(torch.randn(1, 3, 256, 256))
    assert isinstance(output, dict)
    if "one2many" in output:
        assert output["one2many"]["proto"] is not None
        assert output["one2one"]["proto"] is not None
        return
    assert output["proto"] is not None


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

    assert PosePredictionExecutionResult
    assert PosePredictionInstance
    assert PosePredictionKeypoint
    assert PosePredictionRequest
    assert PoseRuntimeSessionInfo
    assert PoseRuntimeTensorSpec


def test_pose_predictor_classes_importable():
    from backend.service.application.runtime.yolo_primary_pose_predictor import (
        OnnxRuntimeYoloPrimaryPoseRuntimeSession,
        OpenVINOYoloPrimaryPoseRuntimeSession,
        PyTorchYoloPrimaryPoseRuntimeSession,
        TensorRTYoloPrimaryPoseRuntimeSession,
    )

    assert OnnxRuntimeYoloPrimaryPoseRuntimeSession
    assert OpenVINOYoloPrimaryPoseRuntimeSession
    assert PyTorchYoloPrimaryPoseRuntimeSession
    assert TensorRTYoloPrimaryPoseRuntimeSession


def test_pose_model_runtime_importable():
    from backend.service.application.runtime.pose_model_runtime import (
        DefaultPoseModelRuntime, PoseModelRuntimeRegistry,
    )

    assert DefaultPoseModelRuntime
    assert PoseModelRuntimeRegistry
