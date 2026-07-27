"""YOLOv8、YOLO11、YOLO26 共享 full-core 修复回归测试。"""

from __future__ import annotations

import math
from types import SimpleNamespace
import weakref

import cv2
import numpy as np
import pytest
import torch
from torch import nn

from backend.service.application.models.evaluation.coco_style_metrics import (
    compute_object_keypoint_similarity,
)
from backend.service.application.models.evaluation.detection_evaluation import (
    _resolve_detection_category_id,
)
from backend.service.application.models.postprocess.detection_postprocess import (
    postprocess_detection_prediction_array,
)
from backend.service.application.models.yolo_core_common.data import (
    build_yolo_classification_augmentation_options,
    normalize_yolo_classification_image,
    prepare_yolo_classification_image,
)
from backend.service.application.models.yolo_core_common.decode.obb import (
    OBB_ANGLE_DECODE_MODE_RAW,
    build_obb_prediction,
)
from backend.service.application.models.yolo_core_common.training import (
    YoloModelEMA,
    YoloUltralyticsOptimizerStep,
    build_yolo_ultralytics_optimizer,
    compute_yolo_ultralytics_lr_factor,
)
from backend.service.application.models.yolo_core_common.weights import (
    restore_yolo_checkpoint_module_attributes,
)
from backend.service.application.runtime.deployment.deployment_runtime_pool import (
    DeploymentRuntimePool,
    DeploymentRuntimePoolConfig,
)
from backend.service.application.runtime.session_lifecycle import RuntimeSessionLease
from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
)


def test_obb_deployment_decode_applies_half_offset_and_stride() -> None:
    """验证共享 OBB 部署解码同时应用中心二分之一和 feature stride。"""

    prediction = build_obb_prediction(
        raw_outputs={
            "boxes": torch.tensor([[[1.0], [2.0], [3.0], [4.0]]]),
            "scores": torch.zeros((1, 1, 1)),
            "angle": torch.zeros((1, 1, 1)),
            "feats": [torch.zeros((1, 1, 1, 1))],
        },
        strides=(8,),
        dfl_decoder=nn.Identity(),
        angle_decode_mode=OBB_ANGLE_DECODE_MODE_RAW,
    )

    torch.testing.assert_close(
        prediction[0, :4, 0],
        torch.tensor([12.0, 12.0, 32.0, 48.0]),
    )


def test_detection_category_mapping_preserves_sparse_manifest_ids() -> None:
    """验证零基预测类别按 manifest 顺序映射到非连续 COCO category id。"""

    category_ids = (3, 17, 42)
    assert _resolve_detection_category_id(class_index=0, category_ids=category_ids) == 3
    assert (
        _resolve_detection_category_id(class_index=2, category_ids=category_ids) == 42
    )
    assert (
        _resolve_detection_category_id(class_index=-1, category_ids=category_ids)
        is None
    )
    assert (
        _resolve_detection_category_id(class_index=3, category_ids=category_ids) is None
    )


def test_pose_oks_uses_only_gt_visibility_and_coco_denominator() -> None:
    """验证预测 visibility 不参与 mask，且 OKS 分母与 COCO 定义一致。"""

    exact = compute_object_keypoint_similarity(
        [10.0, 20.0, 2.0],
        [10.0, 20.0, 0.0],
        area=100.0,
        sigmas=(0.1,),
    )
    shifted = compute_object_keypoint_similarity(
        [10.0, 20.0, 2.0],
        [11.0, 21.0, 0.0],
        area=100.0,
        sigmas=(0.1,),
    )

    assert exact == pytest.approx(1.0)
    assert shifted == pytest.approx(math.exp(-2.0 / (8.0 * 0.1**2 * 100.0)))


def test_default_scheduler_is_linear_and_cosine_requires_opt_in() -> None:
    """验证默认 scheduler 为 linear，cosine 只在显式启用时生效。"""

    linear_mid = compute_yolo_ultralytics_lr_factor(
        epoch=50,
        max_epochs=100,
        final_lr_ratio=0.01,
    )
    linear_end = compute_yolo_ultralytics_lr_factor(
        epoch=100,
        max_epochs=100,
        final_lr_ratio=0.01,
    )
    cosine_quarter = compute_yolo_ultralytics_lr_factor(
        epoch=25,
        max_epochs=100,
        final_lr_ratio=0.01,
        cosine_schedule=True,
    )

    assert linear_mid == pytest.approx(0.505)
    assert linear_end == pytest.approx(0.01)
    assert cosine_quarter != pytest.approx(
        compute_yolo_ultralytics_lr_factor(
            epoch=25,
            max_epochs=100,
            final_lr_ratio=0.01,
        )
    )


def test_optimizer_groups_accumulation_weight_decay_and_ema() -> None:
    """验证参数分组、nominal batch 累积、weight-decay 缩放和 EMA update。"""

    model = nn.Sequential(
        nn.Conv2d(3, 4, kernel_size=1, bias=True),
        nn.BatchNorm2d(4),
    )
    optimizer, schedule = build_yolo_ultralytics_optimizer(
        torch_module=torch,
        model=model,
        num_classes=2,
        batch_size=16,
        train_sample_count=64,
        max_epochs=10,
        optimizer_name="sgd",
        learning_rate=0.01,
        momentum=0.9,
        weight_decay=5e-4,
        warmup_epochs=0.0,
    )
    groups = {str(group["param_group"]): group for group in optimizer.param_groups}

    assert schedule.accumulate == 4
    assert schedule.scaled_weight_decay == pytest.approx(5e-4)
    assert groups["weight"]["weight_decay"] == pytest.approx(5e-4)
    assert groups["bn"]["weight_decay"] == pytest.approx(0.0)
    assert groups["bias"]["weight_decay"] == pytest.approx(0.0)

    ema = YoloModelEMA(model=model)
    step = YoloUltralyticsOptimizerStep(
        torch_module=torch,
        model=model,
        optimizer=optimizer,
        scaler=None,
        schedule=schedule,
        ema=ema,
        grad_clip_norm=10.0,
    )
    original = model[0].weight.detach().clone()
    for iteration in range(1, 5):
        step.prepare_batch(
            iteration_index=iteration,
            epoch=1,
            batch_size=16,
        )
        output = model(torch.ones((1, 3, 2, 2)))
        did_step = step.backward_and_step(
            loss=output.square().mean(),
            iteration_index=iteration,
            is_last_batch=False,
        )
        assert did_step is (iteration == 4)

    assert not torch.equal(model[0].weight.detach(), original)
    assert ema.updates == 1


class _AttributeBlock(nn.Module):
    """提供可恢复 activation 和 BatchNorm 属性的测试模块。"""

    def __init__(self, *, activation: nn.Module, eps: float, momentum: float) -> None:
        super().__init__()
        self.bn = nn.BatchNorm2d(2, eps=eps, momentum=momentum)
        self.act = activation


def test_checkpoint_loader_restores_activation_and_batchnorm_attributes() -> None:
    """验证完整 checkpoint 中 state_dict 之外的推理语义会被恢复。"""

    source = _AttributeBlock(
        activation=nn.SiLU(inplace=True),
        eps=1e-5,
        momentum=0.1,
    )
    target = _AttributeBlock(
        activation=nn.Identity(),
        eps=1e-3,
        momentum=0.03,
    )

    restored = restore_yolo_checkpoint_module_attributes(
        model=target,
        checkpoint_payload={"model": source},
    )

    assert restored >= 3
    assert isinstance(target.act, nn.SiLU)
    assert target.bn.eps == pytest.approx(1e-5)
    assert target.bn.momentum == pytest.approx(0.1)


def test_classification_validation_preprocess_center_crops_and_normalizes() -> None:
    """验证 classification 验证/部署路径保持比例、中心裁剪并 Normalize。"""

    image = np.zeros((40, 80, 3), dtype=np.uint8)
    image[:, :, 2] = 255
    cropped = prepare_yolo_classification_image(
        image=image,
        input_size=(32, 32),
        training=False,
        cv2_module=cv2,
    )
    tensor = normalize_yolo_classification_image(
        image=cropped,
        options=None,
        np_module=np,
    )

    assert cropped.shape == (32, 32, 3)
    assert tensor.shape == (3, 32, 32)
    assert tensor[0, 0, 0] == pytest.approx((1.0 - 0.485) / 0.229)
    assert tensor[1, 0, 0] == pytest.approx((0.0 - 0.456) / 0.224)
    assert tensor[2, 0, 0] == pytest.approx((0.0 - 0.406) / 0.225)


def test_classification_defaults_enable_reference_auto_augment_and_erasing() -> None:
    """验证 classification 默认启用 RandAugment 和 0.4 RandomErasing。"""

    options = build_yolo_classification_augmentation_options({})
    assert options.auto_augment == "randaugment"
    assert options.random_erasing_prob == pytest.approx(0.4)


def test_detection_postprocess_caps_nms_results_at_max_detections() -> None:
    """验证普通 NMS 路径和 end-to-end 一样遵守 max_det。"""

    predictions = np.asarray(
        [
            [
                [0.0, 0.0, 1.0, 1.0, 0.99],
                [2.0, 0.0, 3.0, 1.0, 0.98],
                [4.0, 0.0, 5.0, 1.0, 0.97],
                [6.0, 0.0, 7.0, 1.0, 0.96],
            ]
        ],
        dtype=np.float32,
    )
    result = postprocess_detection_prediction_array(
        prediction_array=predictions,
        np_module=np,
        num_classes=1,
        score_threshold=0.01,
        nms_threshold=0.7,
        max_detections=2,
    )[0]

    assert result is not None
    assert result.boxes_xyxy.shape[0] == 2


def test_runtime_session_lease_closes_once() -> None:
    """验证 runtime session 释放协议可显式使用且幂等。"""

    class _Session:
        def __init__(self) -> None:
            self.close_count = 0

        def close(self) -> None:
            self.close_count += 1

    session = _Session()
    with RuntimeSessionLease(session) as lease:
        assert lease is not None
    lease.close()
    assert session.close_count == 1


def test_three_generation_five_task_runtime_resource_recreation_matrix() -> None:
    """反复创建/释放三代五任务三种转换运行时后不保留模型强引用。"""

    class _Payload:
        pass

    matrix = [
        (model_type, task_type, runtime_backend)
        for model_type in ("yolov8", "yolo11", "yolo26")
        for task_type in (
            "detection",
            "classification",
            "segmentation",
            "pose",
            "obb",
        )
        for runtime_backend in ("onnxruntime", "openvino", "tensorrt")
    ]
    for model_type, task_type, runtime_backend in matrix:
        payload = _Payload()
        payload_ref = weakref.ref(payload)
        session = SimpleNamespace(
            model=payload,
            model_type=model_type,
            task_type=task_type,
            runtime_backend=runtime_backend,
        )
        with RuntimeSessionLease(session):
            pass
        del session
        del payload
        assert payload_ref() is None, (
            f"{model_type}/{task_type}/{runtime_backend} 释放后仍持有模型引用"
        )


def test_runtime_session_lease_releases_on_exception() -> None:
    """conversion/runtime 异常路径同样只能释放一次。"""

    class _Session:
        def __init__(self) -> None:
            self.close_count = 0

        def close(self) -> None:
            self.close_count += 1

    session = _Session()
    with pytest.raises(RuntimeError, match="conversion failed"):
        with RuntimeSessionLease(session):
            raise RuntimeError("conversion failed")

    assert session.close_count == 1


def test_three_generation_five_task_runtime_pool_recreation_matrix() -> None:
    """真实 runtime pool 反复 warmup/close 后不保留 session 或模型引用。"""

    class _Payload:
        pass

    close_counts: list[int] = []
    payload_refs: list[weakref.ReferenceType[_Payload]] = []

    class _Session:
        def __init__(self) -> None:
            self.payload = _Payload()
            payload_refs.append(weakref.ref(self.payload))
            self.close_count = 0

        def close(self) -> None:
            self.close_count += 1
            self.payload = None
            close_counts.append(self.close_count)

    def load_session(**_: object) -> _Session:
        return _Session()

    pool = DeploymentRuntimePool(
        dataset_storage=SimpleNamespace(),
        model_runtime=SimpleNamespace(load_session=load_session),
    )
    matrix = [
        (model_type, task_type, runtime_backend)
        for model_type in ("yolov8", "yolo11", "yolo26")
        for task_type in (
            "detection",
            "classification",
            "segmentation",
            "pose",
            "obb",
        )
        for runtime_backend in ("onnxruntime", "openvino", "tensorrt")
    ]
    for index, (model_type, task_type, runtime_backend) in enumerate(matrix):
        deployment_id = f"matrix-{index}"
        config = DeploymentRuntimePoolConfig(
            deployment_instance_id=deployment_id,
            runtime_target=SimpleNamespace(
                model_type=model_type,
                task_type=task_type,
                runtime_backend=runtime_backend,
            ),
            runtime_configuration=DeploymentRuntimeConfiguration(),
        )
        pool.warmup_deployment(config)
        pool.close_deployment(deployment_id)

    assert close_counts == [1] * len(matrix)
    assert all(payload_ref() is None for payload_ref in payload_refs)
    assert pool._deployments == {}
