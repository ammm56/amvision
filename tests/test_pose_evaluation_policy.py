"""Pose 评估参数和指标坐标回归；普通预测仍使用展示裁剪。"""

from __future__ import annotations

from importlib import import_module

import cv2
import numpy as np
import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.evaluation.pose_policy import (
    PoseEvaluationPolicy,
    build_pose_evaluation_policy,
)
from backend.service.application.models.yolo_core_common.geometry import (
    build_yolo_letterbox_transform,
)
from backend.service.application.runtime.contracts.pose.evaluation import (
    PoseEvaluationPredictionRequest,
    pose_evaluation_postprocess_options,
    pose_evaluation_preprocess_options,
)
from backend.service.application.runtime.contracts.pose.prediction import (
    PosePredictionRequest,
)
from backend.service.application.runtime.predictors.common.pose_runtime_io import (
    preprocess_pose_image,
)


@pytest.mark.parametrize("family", ["yolov8", "yolo11", "yolo26"])
def test_pose_metric_coordinates_preserve_padding_and_outside_canvas(
    family: str,
) -> None:
    """裁剪不能把 padding 或画布外的错误关键点推到原图边缘。"""
    module = import_module(
        f"backend.service.application.runtime.predictors.{family}.pose.postprocess"
    )
    build = getattr(module, f"build_{family}_pose_runtime_instances")
    transform = build_yolo_letterbox_transform(
        source_width=96,
        source_height=64,
        input_size=(256, 384),
        scaleup=False,
    )
    box = [144, 96, 240, 160] if family == "yolo26" else [192, 128, 96, 64]
    prediction = np.array(
        [[box + [0.9, -20, 400, 0.8, 170, 120, 0.8]]], dtype=np.float32
    )
    options = dict(
        np_module=np,
        prediction_array=prediction,
        labels=("part",),
        score_threshold=0.1,
        keypoint_confidence_threshold=0,
        letterbox_transform=transform,
        default_kpt_shape=(2, 3),
    )
    displayed, _ = build(**options)
    measured, _ = build(**options, clip_coordinates=False)
    assert displayed[0].keypoints[0].x == 0
    assert displayed[0].keypoints[0].y == 64
    assert measured[0].keypoints[0].x == -164
    assert measured[0].keypoints[0].y == 304
    assert measured[0].keypoints[1] == displayed[0].keypoints[1]


def test_evaluation_request_does_not_change_public_prediction_defaults() -> None:
    """只有内部强类型请求启用评估参数，extra_options 不能伪装评估用途。"""
    common = dict(
        score_threshold=0.001, keypoint_confidence_threshold=0, save_result_image=False
    )
    normal = PosePredictionRequest(**common, extra_options={"evaluation_policy": True})
    policy = PoseEvaluationPolicy(input_size=(256, 384), score_threshold=0.001)
    metric = PoseEvaluationPredictionRequest(**common, evaluation_policy=policy)
    assert pose_evaluation_preprocess_options(normal) == {}
    assert pose_evaluation_postprocess_options(normal) == {}
    assert pose_evaluation_preprocess_options(metric) == {"scaleup": False}
    assert pose_evaluation_postprocess_options(metric) == {
        "clip_coordinates": False,
        "nms_threshold": 0.7,
    }
    assert pose_evaluation_postprocess_options(metric, end2end=True) == {
        "clip_coordinates": False
    }


def test_pose_small_image_evaluation_does_not_upscale() -> None:
    """验证与部署共享实现，但仅评估禁止小图放大。"""
    image = np.zeros((64, 96, 3), dtype=np.uint8)
    common = dict(cv2_module=cv2, np_module=np, image=image, input_size=(256, 384))
    normal, normal_transform = preprocess_pose_image(**common)
    metric, metric_transform = preprocess_pose_image(**common, scaleup=False)
    assert normal.shape == metric.shape == (3, 256, 384)
    assert normal_transform.gain == 4
    assert metric_transform.gain == 1
    assert metric_transform.pad_left == 144
    assert metric_transform.pad_top == 96
    assert np.any(normal != metric)


@pytest.mark.parametrize(
    "sigmas", [[float("nan")], [float("inf")], [0], [-1], "invalid"]
)
def test_pose_policy_rejects_invalid_sigma(sigmas: object) -> None:
    """非法 sigma 不得进入 COCO 指标或生成看似有效的分数。"""
    with pytest.raises(InvalidRequestError):
        build_pose_evaluation_policy(
            input_size=(256, 384),
            score_threshold=0.001,
            extra_options={"oks_sigmas": sigmas},
        )


def test_pose_policy_checks_custom_topology() -> None:
    """自定义 sigma 必须与实际拓扑完全匹配。"""
    policy = build_pose_evaluation_policy(
        input_size=(256, 384),
        score_threshold=0.001,
        extra_options={"oks_sigmas": [0.1, 0.2]},
    )
    assert policy.resolve_sigmas(2) == (0.1, 0.2)
    with pytest.raises(InvalidRequestError):
        policy.resolve_sigmas(17)


@pytest.mark.parametrize("family", ["yolov8", "yolo11", "yolo26"])
@pytest.mark.parametrize("outside", [False, True])
@pytest.mark.parametrize("small_box", [False, True])
def test_training_and_independent_pose_metrics_share_actual_pipeline(
    tmp_path, family: str, outside: bool, small_box: bool
) -> None:
    """相同模型经过真实数据加载、predictor 和 COCO 评估，两端必须一致。"""
    from types import SimpleNamespace
    import torch
    from backend.service.infrastructure.object_store.local_dataset_storage import (
        LocalDatasetStorage,
        DatasetStorageSettings,
    )
    from backend.service.application.models.evaluation.pose_evaluation import (
        PoseEvaluationRequest,
        _run_pose_evaluation_with_session,
    )

    height, width = (512, 768) if small_box else (64, 96)
    box_width, box_height = (1.0, 1.0) if small_box else (96.0, 64.0)
    gt_points = [0.0, box_height, 2, box_width / 5, box_height / 3, 2]
    transform = build_yolo_letterbox_transform(
        source_width=width, source_height=height, input_size=(256, 384), scaleup=False
    )

    class FixedPose(torch.nn.Module):
        """固定模型输出隔离评估策略，避免随机训练精度影响断言。"""

        def __init__(self):
            super().__init__()
            x, y, gain = transform.pad_left, transform.pad_top, transform.gain
            w, h = box_width * gain, box_height * gain
            box = (
                [x, y, x + w, y + h]
                if family == "yolo26"
                else [x + w / 2, y + h / 2, w, h]
            )
            first = [-2000, 4000, 0.9] if outside else [x, y + h, 0.9]
            second = [-1000, 4000, 0.9] if outside else [x + w / 5, y + h / 3, 0.9]
            row = torch.zeros((1, 16, 11), dtype=torch.float32)
            row[0, 0] = torch.tensor(box + [0.9, *first, *second])
            self.register_buffer(
                "prediction", row if family == "yolo26" else row.transpose(1, 2)
            )

        def forward(self, images):
            """保持实际 batch 维度，返回公开模型布局。"""
            return self.prediction.expand(images.shape[0], -1, -1)

    image_path = tmp_path / "image.png"
    assert cv2.imwrite(str(image_path), np.zeros((height, width, 3), dtype=np.uint8))
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=tmp_path))
    target = SimpleNamespace(
        input_size=(256, 384),
        labels=("part",),
        model_config={"kpt_shape": [2, 3]},
        runtime_backend="pytorch",
        runtime_precision="fp32",
        model_version_id="test",
        model_build_id=None,
        runtime_artifact_storage_uri="test.pt",
    )
    imports = SimpleNamespace(torch=torch, np=np, cv2=cv2)
    model = FixedPose().eval()
    cls_name = (
        "PyTorch"
        + {"yolov8": "YoloV8", "yolo11": "Yolo11", "yolo26": "Yolo26"}[family]
        + "PoseRuntimeSession"
    )
    cls = getattr(
        import_module(
            f"backend.service.application.runtime.predictors.{family}.pose.pytorch"
        ),
        cls_name,
    )
    session = cls(
        dataset_storage=storage,
        runtime_target=target,
        imports=imports,
        model=model,
        device_name="cpu",
        runtime_precision="fp32",
    )
    keypoints = gt_points
    sample = SimpleNamespace(
        image_path=image_path,
        boxes_xywh=[[0, 0, box_width, box_height]],
        class_ids=[0],
        keypoints=[keypoints],
    )
    evaluate = getattr(
        import_module(
            f"backend.service.application.models.{family}_core.evaluation.pose"
        ),
        f"evaluate_{family}_pose_samples",
    )
    train = evaluate(
        model=model,
        samples=[sample],
        labels=target.labels,
        input_size=target.input_size,
        device="cpu",
        precision="fp32",
        score_threshold=0.001,
        kpt_shape=(2, 3),
        imports=imports,
        **({"nms_threshold": 0.7} if family != "yolo26" else {}),
    )
    result = _run_pose_evaluation_with_session(
        request=PoseEvaluationRequest(
            dataset_storage=storage,
            runtime_target=target,
            manifest_payload={},
            score_threshold=0.001,
        ),
        dataset_storage=storage,
        score_threshold=0.001,
        output_prefix="evaluation",
        samples=[
            {
                "image_path": "image.png",
                "annotations": [
                    {
                        "category_id": 0,
                        "bbox": [0, 0, box_width, box_height],
                        "keypoints": keypoints,
                    }
                ],
            }
        ],
        categories=[{"id": 0, "name": "part"}],
        session=session,
    )
    for metric in ("bbox_map50", "bbox_map50_95", "oks_ap50", "oks_ap50_95"):
        assert abs(train[metric] - getattr(result, metric)) < 1e-6
    assert result.oks_ap50 == pytest.approx(0 if outside else 1)
