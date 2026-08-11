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
from backend.service.application.models.yolo_core_common.geometry import (
    build_yolo_letterbox_transform,
)
from backend.service.application.models.yolo_core_common.training import (
    YoloModelEMA,
    YoloUltralyticsOptimizerStep,
    YoloTrainingNumericalError,
    build_yolo_ultralytics_optimizer,
    compute_yolo_ultralytics_lr_factor,
    resolve_yolo_optimizer_base_learning_rate,
)
from backend.service.application.models.yolo_core_common.postprocess import (
    crop_binary_mask_to_box,
)
from backend.service.application.models.yolo_core_common.weights import (
    restore_yolo_checkpoint_module_attributes,
)
from backend.service.application.models.yolo11_core.postprocess.segmentation import (
    build_yolo11_segmentation_postprocess_instances,
    postprocess_yolo11_segmentation_prediction_array,
)
from backend.service.application.models.yolo26_core.postprocess.segmentation import (
    build_yolo26_segmentation_postprocess_instances,
)
from backend.service.application.models.yolov8_core.postprocess.segmentation import (
    build_yolov8_segmentation_postprocess_instances,
    postprocess_yolov8_segmentation_prediction_array,
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
    scheduler_calls: list[bool] = []
    scheduler = type(
        "_Scheduler",
        (),
        {"step": lambda _self: scheduler_calls.append(True)},
    )()
    assert step.step_scheduler_if_optimizer_updated(scheduler) is True
    assert step.step_scheduler_if_optimizer_updated(scheduler) is False
    assert scheduler_calls == [True]


@pytest.mark.parametrize("invalid_loss", [float("nan"), float("inf"), float("-inf")])
def test_optimizer_rejects_non_finite_loss_before_backward(invalid_loss: float) -> None:
    """NaN/Inf loss 不得进入 backward、optimizer 或 checkpoint。"""

    model = nn.Linear(2, 1)
    optimizer, schedule = build_yolo_ultralytics_optimizer(
        torch_module=torch,
        model=model,
        num_classes=1,
        batch_size=1,
        train_sample_count=1,
        max_epochs=1,
        warmup_epochs=0.0,
    )
    step = YoloUltralyticsOptimizerStep(
        torch_module=torch,
        model=model,
        optimizer=optimizer,
        scaler=None,
        schedule=schedule,
        ema=None,
        grad_clip_norm=10.0,
    )

    with pytest.raises(YoloTrainingNumericalError, match="非有限 total loss"):
        step.backward_and_step(
            loss=torch.tensor(invalid_loss, requires_grad=True),
            iteration_index=1,
            is_last_batch=True,
        )

    assert all(parameter.grad is None for parameter in model.parameters())


def test_amp_overflow_does_not_advance_ema_or_report_optimizer_step() -> None:
    """GradScaler 跳过 overflow step 时不得伪装成一次有效模型更新。"""

    class _OverflowGradScaler:
        def __init__(self) -> None:
            self.scale_value = 65536.0

        def scale(self, loss):
            return loss

        def unscale_(self, _optimizer) -> None:
            return None

        def step(self, _optimizer) -> None:
            return None

        def update(self) -> None:
            self.scale_value /= 2.0

        def get_scale(self) -> float:
            return self.scale_value

    model = nn.Linear(2, 1)
    optimizer, schedule = build_yolo_ultralytics_optimizer(
        torch_module=torch,
        model=model,
        num_classes=1,
        batch_size=1,
        train_sample_count=1,
        max_epochs=1,
        warmup_epochs=0.0,
    )
    ema = YoloModelEMA(model=model)
    optimizer_step = YoloUltralyticsOptimizerStep(
        torch_module=torch,
        model=model,
        optimizer=optimizer,
        scaler=_OverflowGradScaler(),
        schedule=schedule,
        ema=ema,
        grad_clip_norm=10.0,
    )
    original = model.weight.detach().clone()

    did_step = optimizer_step.backward_and_step(
        loss=model(torch.ones((1, 2))).square().mean(),
        iteration_index=1,
        is_last_batch=True,
    )

    assert did_step is False
    assert optimizer_step.successful_optimizer_steps == 0
    assert optimizer_step.skipped_optimizer_steps == 1
    assert optimizer_step.consecutive_skipped_optimizer_steps == 1
    assert ema.updates == 0
    assert torch.equal(model.weight.detach(), original)
    scheduler_calls: list[bool] = []
    scheduler = type(
        "_Scheduler",
        (),
        {"step": lambda _self: scheduler_calls.append(True)},
    )()
    assert optimizer_step.step_scheduler_if_optimizer_updated(scheduler) is False
    assert scheduler_calls == []


def test_auto_optimizer_resolves_adamw_or_musgd_and_restores_state() -> None:
    """验证 Auto 边界、MuSGD 参数分组和 checkpoint 恢复。"""

    small_model = nn.Linear(4, 2)
    _, small_schedule = build_yolo_ultralytics_optimizer(
        torch_module=torch,
        model=small_model,
        num_classes=2,
        batch_size=16,
        train_sample_count=64,
        max_epochs=10,
    )
    assert small_schedule.optimizer_name == "AdamW"
    assert small_schedule.initial_lr == pytest.approx(0.001667)

    model = nn.Linear(4, 2)
    optimizer, schedule = build_yolo_ultralytics_optimizer(
        torch_module=torch,
        model=model,
        num_classes=2,
        batch_size=16,
        train_sample_count=20_000,
        max_epochs=40,
    )
    assert schedule.optimizer_name == "MuSGD"
    assert {group["param_group"] for group in optimizer.param_groups} >= {
        "muon",
        "bias",
    }
    loss = model(torch.ones((2, 4))).square().mean()
    loss.backward()
    optimizer.step()
    state_dict = optimizer.state_dict()

    restored, _ = build_yolo_ultralytics_optimizer(
        torch_module=torch,
        model=nn.Linear(4, 2),
        num_classes=2,
        batch_size=16,
        train_sample_count=20_000,
        max_epochs=40,
    )
    restored.load_state_dict(state_dict)
    assert restored.state_dict()["state"]


def test_musgd_uses_reference_finetune_learning_rate_groups() -> None:
    """验证检测头和语义原型参数按参考规则使用三倍学习率。"""

    blocks = [nn.Identity() for _ in range(23)]
    detection_head = nn.Module()
    detection_head.cv3 = nn.Linear(4, 2)
    blocks.append(detection_head)
    model = nn.Sequential(*blocks)
    optimizer, _ = build_yolo_ultralytics_optimizer(
        torch_module=torch,
        model=model,
        num_classes=2,
        batch_size=16,
        train_sample_count=20_000,
        max_epochs=40,
    )
    boosted_muon_groups = [
        group
        for group in optimizer.param_groups
        if group["param_group"] == "muon" and group["lr"] == pytest.approx(0.03)
    ]
    assert len(boosted_muon_groups) == 1
    assert len(boosted_muon_groups[0]["params"]) == 1
    assert boosted_muon_groups[0]["params"][0] is detection_head.cv3.weight
    assert resolve_yolo_optimizer_base_learning_rate(
        optimizer=optimizer,
        initial_learning_rate=0.01,
    ) == pytest.approx(0.01)


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


@pytest.mark.parametrize(
    "postprocess_func",
    [
        postprocess_yolov8_segmentation_prediction_array,
        postprocess_yolo11_segmentation_prediction_array,
    ],
)
def test_segmentation_postprocess_caps_instances_before_mask_decode(
    postprocess_func: object,
) -> None:
    """验证 v8/11 在 mask decode 前仅保留分数最高的 max_det 候选。"""

    prediction = np.asarray(
        [
            [
                [8.0, 8.0, 4.0, 4.0, 0.20, 1.0],
                [16.0, 8.0, 4.0, 4.0, 0.95, 2.0],
                [24.0, 8.0, 4.0, 4.0, 0.70, 3.0],
                [32.0, 8.0, 4.0, 4.0, 0.80, 4.0],
            ]
        ],
        dtype=np.float32,
    )

    result = postprocess_func(
        prediction_array=prediction,
        np_module=np,
        num_classes=1,
        score_threshold=0.01,
        nms_threshold=0.7,
        nms_indices_func=lambda **_kwargs: np.asarray([0, 1, 2, 3]),
        max_detections=2,
    )[0]

    assert result is not None
    assert result.scores.tolist() == pytest.approx([0.95, 0.80])
    assert result.mask_coefficients[:, 0].tolist() == pytest.approx([2.0, 4.0])


def test_segmentation_binary_mask_is_cropped_with_ultralytics_pixel_rules() -> None:
    """验证 segmentation mask 使用左闭右开像素坐标裁到预测框。"""

    cropped = crop_binary_mask_to_box(
        binary_mask=np.ones((5, 6), dtype=np.uint8),
        box_xyxy=(1.2, 0.8, 4.1, 3.0),
        np_module=np,
    )

    assert int(cropped.sum()) == 6
    assert np.all(cropped[1:3, 2:5] == 1)
    assert np.count_nonzero(cropped[:, :2]) == 0
    assert np.count_nonzero(cropped[3:, :]) == 0


def test_segmentation_evaluation_can_encode_cropped_masks_without_polygons() -> None:
    """验证三个 family 的评估路径可直接编码裁剪后的 binary mask。"""

    transform = build_yolo_letterbox_transform(
        source_width=32,
        source_height=32,
        input_size=(32, 32),
    )
    encoded_masks: list[np.ndarray] = []

    def encode_mask(mask: np.ndarray) -> dict[str, object]:
        encoded_masks.append(mask.copy())
        return {"size": [32, 32], "counts": "encoded"}

    common_prediction = np.asarray(
        [[[16.0, 16.0, 16.0, 16.0, 0.9, 8.0]]],
        dtype=np.float32,
    )
    common_kwargs = {
        "cv2_module": cv2,
        "np_module": np,
        "prediction_array": common_prediction,
        "proto_array": np.ones((1, 1, 4, 4), dtype=np.float32),
        "labels": ("part",),
        "score_threshold": 0.01,
        "mask_threshold": 0.5,
        "letterbox_transform": transform,
        "mask_encoder": encode_mask,
        "include_segments": False,
    }
    v8_instances = build_yolov8_segmentation_postprocess_instances(
        **common_kwargs,
        nms_threshold=0.7,
        nms_indices_func=lambda **_kwargs: np.asarray([0]),
    )
    y11_instances = build_yolo11_segmentation_postprocess_instances(
        **common_kwargs,
        nms_threshold=0.7,
        nms_indices_func=lambda **_kwargs: np.asarray([0]),
    )
    y26_instances = build_yolo26_segmentation_postprocess_instances(
        **{
            **common_kwargs,
            "prediction_array": np.asarray(
                [[[8.0, 8.0, 24.0, 24.0, 0.9, 0.0, 8.0]]],
                dtype=np.float32,
            ),
        }
    )

    for instances in (v8_instances, y11_instances, y26_instances):
        assert len(instances) == 1
        assert instances[0].segments == ()
        assert instances[0].mask_rle == {"size": [32, 32], "counts": "encoded"}
    assert len(encoded_masks) == 3
    assert all(int(mask.sum()) == 256 for mask in encoded_masks)


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
