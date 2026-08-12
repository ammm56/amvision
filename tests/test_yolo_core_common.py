"""YOLO core 共用基础能力测试。"""

from __future__ import annotations

import ctypes
import gc
import os
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import cv2
import pytest
import torch

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common import (
    Conv,
    DistributionFocalLossDecoder,
    OBB_ANGLE_DECODE_MODE_RAW,
    OBB_ANGLE_DECODE_MODE_SIGMOID_MINUS_QUARTER_PI,
    build_detection_prediction,
    build_obb_prediction,
    decode_detection_boxes,
    decode_detection_training_predictions,
    decode_obb_angle_logits,
    decode_pose_keypoints,
    decode_segmentation_masks,
    dist2bbox_xyxy,
    dist2rbox,
    make_anchors,
)
from backend.service.application.models.yolo_core_common.assigners import (
    assign_detection_targets,
    assign_segmentation_targets,
    box_iou_aligned,
)
from backend.service.application.models.yolo_core_common.export import (
    normalize_segmentation_export_outputs,
    resolve_segmentation_export_output_names,
)
from backend.service.application.models.yolo_core_common.losses import (
    build_pose_box_area,
    build_pose_oks_sigmas,
    build_pose_visibility_mask,
    compute_obb_angle_loss,
    compute_oks_keypoint_loss,
    compute_segmentation_detection_loss,
    compute_segmentation_mask_loss,
    compute_visibility_loss,
    decode_pose_keypoints_xy,
    decode_segmentation_training_boxes,
    distribution_focal_loss,
    probiou_aligned,
    segmentation_bbox_iou_aligned,
)
from backend.service.application.models.yolo26_core.losses import (
    build_yolo26_pose_rle_weights,
    compute_yolo26_rle_loss,
)
from backend.service.application.models.yolo_core_common.postprocess import (
    build_segmentation_postprocess_instances,
    normalize_segmentation_outputs,
    postprocess_segmentation_prediction_array,
    prepare_detection_nms_inputs_array,
    prepare_detection_nms_inputs_tensor,
    prepare_segmentation_nms_inputs_array,
)
from backend.service.application.models.yolo_core_common.targets import (
    anchor_in_rotated_box,
    bbox_xyxy_to_distances,
    decode_distances_to_rboxes,
    normalize_gt_keypoints_tensor,
    rasterize_segmentation_polygons,
    rbox_to_distances,
    select_object_segmentation_polygons,
    xywhr_to_corners,
    xywhr_to_xyxy,
)
from backend.service.application.models.yolo_core_common.training.task_dataloader import (
    YoloTaskDataLoaderPlan,
    YoloTaskTrainingDataLoaderLifecycle,
    build_yolo_task_evaluation_dataloader,
    iter_yolo_task_evaluation_items,
    managed_yolo_task_evaluation_dataloader,
    move_yolo_task_batch_to_device,
)
from backend.service.application.models.yolo_core_common.training.classification_dataloader import (
    YoloClassificationBatchCollator,
)
from backend.service.application.models.yolo_core_common.training.worker_ipc import (
    serialize_yolo_worker_value,
)
from backend.service.application.models.yolo_core_common.training.validation_schedule import (
    should_run_yolo_validation,
)
from backend.service.application.models.yolo_core_common.training.metrics_history import (
    build_yolo_completed_epoch_history_item,
    build_yolo_epoch_history_item,
)
from backend.service.application.models.yolo_core_common.training.infinite_dataloader import (
    YoloInfiniteDataLoader,
    _close_yolo_dataloader_worker_processes,
)
from backend.service.application.models.yolo26_core.tasks import (
    OBB26,
    Pose26,
    Segment26,
)
from backend.service.application.models.yolov8_core.training.epoch import (
    should_run_yolov8_detection_validation,
)
from backend.service.application.models.yolo11_core.training.epoch import (
    should_run_yolo11_detection_validation,
)
from backend.service.application.models.yolo26_core.training.epoch import (
    should_run_yolo26_detection_validation,
)


def test_yolo26_heads_live_in_yolo26_core() -> None:
    """验证 YOLO26 专用 head 留在 yolo26_core 边界内。"""

    assert Segment26.__module__.endswith("yolo26_core.nn.tasks.segmentation")
    assert Pose26.__module__.endswith("yolo26_core.nn.tasks.pose")
    assert OBB26.__module__.endswith("yolo26_core.nn.tasks.obb")
    assert not hasattr(Pose26, "_decode_keypoints_pose26")
    assert not hasattr(OBB26, "_decode_angle_logits")


def test_yolo_epoch_history_separates_public_epoch_from_internal_index() -> None:
    """验证公开轮次从 1 开始且保留明确的内部索引。"""

    assert build_yolo_epoch_history_item(
        epoch_index=0,
        metrics={"loss": 1.25},
    ) == {"loss": 1.25, "epoch": 1, "epoch_index": 0}


def test_yolo_epoch_history_rejects_negative_index() -> None:
    """验证非法的负 epoch index 不会进入训练报告。"""

    with pytest.raises(ValueError, match="epoch_index"):
        build_yolo_epoch_history_item(epoch_index=-1, metrics={"loss": 1.25})


def test_yolo_completed_epoch_history_normalizes_one_based_loop_epoch() -> None:
    """一基 detection 循环不得把首轮序列化成公开第 2 轮。"""

    assert build_yolo_completed_epoch_history_item(
        completed_epoch=1,
        metrics={"loss": 1.25},
    ) == {"loss": 1.25, "epoch": 1, "epoch_index": 0}
    with pytest.raises(ValueError, match="completed_epoch"):
        build_yolo_completed_epoch_history_item(
            completed_epoch=0,
            metrics={"loss": 1.25},
        )


def test_classification_worker_collator_uses_numpy_ipc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 classification worker 不再直接跨进程发送 Tensor。"""

    @dataclass(frozen=True)
    class _Batch:
        images: object
        targets: object

    monkeypatch.setattr(torch.utils.data, "get_worker_info", lambda: object())
    collator = YoloClassificationBatchCollator(
        input_size=(32, 32),
        training=True,
        augmentation_options=None,
        build_batch=lambda **_kwargs: _Batch(
            images=torch.ones((1, 3, 32, 32)),
            targets=torch.tensor([0]),
        ),
        load_imports=lambda: SimpleNamespace(torch=torch),
    )

    batch = collator([object()])

    assert isinstance(batch.images, np.ndarray)
    assert isinstance(batch.targets, np.ndarray)


@pytest.mark.parametrize(
    "schedule",
    (
        should_run_yolov8_detection_validation,
        should_run_yolo11_detection_validation,
        should_run_yolo26_detection_validation,
    ),
)
def test_detection_validation_wrappers_use_completed_epoch_schedule(
    schedule: Callable[..., bool],
) -> None:
    """验证 detection 三族不再按零基轮次错后一轮执行验证。"""

    assert not schedule(
        epoch=18,
        max_epochs=200,
        evaluation_interval=20,
        validation_sample_count=1,
    )
    assert schedule(
        epoch=19,
        max_epochs=200,
        evaluation_interval=20,
        validation_sample_count=1,
    )
    assert not schedule(
        epoch=20,
        max_epochs=200,
        evaluation_interval=20,
        validation_sample_count=1,
    )
    assert schedule(
        epoch=199,
        max_epochs=200,
        evaluation_interval=30,
        validation_sample_count=1,
    )


def test_task_dataloader_lifecycle_reuses_workers_until_augmentation_phase_changes() -> (
    None
):
    """验证跨 epoch 复用 loader，并在 close-mosaic 阶段只重建一次。"""

    class _FakeLoader:
        def __init__(self) -> None:
            self.close_count = 0

        def close(self) -> None:
            self.close_count += 1

    created: list[_FakeLoader] = []

    def build_loader() -> _FakeLoader:
        loader = _FakeLoader()
        created.append(loader)
        return loader

    lifecycle = YoloTaskTrainingDataLoaderLifecycle()
    first = lifecycle.resolve(
        augmentation_options=("mosaic", 1.0),
        build_loader=build_loader,
    )
    reused = lifecycle.resolve(
        augmentation_options=("mosaic", 1.0),
        build_loader=build_loader,
    )
    closed_phase = lifecycle.resolve(
        augmentation_options=("mosaic", 0.0),
        build_loader=build_loader,
    )
    lifecycle.close()
    lifecycle.close()

    assert first is reused
    assert closed_phase is not first
    assert len(created) == 2
    assert created[0].close_count == 1
    assert created[1].close_count == 1


def test_task_dataloader_worker_tensor_transport_round_trips_through_numpy() -> None:
    """Windows worker batch 不保留 torch shared-memory 映射，主进程可无损恢复。"""

    source = {
        "images": torch.arange(12, dtype=torch.float32).reshape(1, 3, 2, 2),
        "labels": torch.tensor([2], dtype=torch.int64),
    }

    transported = serialize_yolo_worker_value(
        value=source,
        torch_module=torch,
    )
    restored = move_yolo_task_batch_to_device(
        batch=transported,
        device="cpu",
        precision="fp32",
        torch_module=torch,
    )

    assert isinstance(transported["images"], np.ndarray)
    assert isinstance(transported["labels"], np.ndarray)
    assert transported["images"].base is None
    assert transported["labels"].base is None
    assert torch.equal(restored["images"], source["images"])
    assert torch.equal(restored["labels"], source["labels"])


def test_task_dataloader_lifecycle_recycles_windows_style_workers() -> None:
    """worker 到达复用上限后必须受控回收，限制 Windows IPC 内存高水位。"""

    class _FakeWorkerLoader:
        num_workers = 2

        def __init__(self) -> None:
            self.close_count = 0

        def close(self) -> None:
            self.close_count += 1

    created: list[_FakeWorkerLoader] = []

    def build_loader() -> _FakeWorkerLoader:
        loader = _FakeWorkerLoader()
        created.append(loader)
        return loader

    lifecycle = YoloTaskTrainingDataLoaderLifecycle(max_reuse_epochs=2)
    first = lifecycle.resolve(augmentation_options=None, build_loader=build_loader)
    second = lifecycle.resolve(augmentation_options=None, build_loader=build_loader)
    third = lifecycle.resolve(augmentation_options=None, build_loader=build_loader)
    lifecycle.close()

    assert first is second
    assert third is not first
    assert [loader.close_count for loader in created] == [1, 1]


def test_task_dataloader_lifecycle_default_does_not_recycle_workers_by_epoch() -> None:
    """默认跨 epoch 常驻 worker，避免 Windows spawn 周期停顿。"""

    class _FakeWorkerLoader:
        num_workers = 2

        def __init__(self) -> None:
            self.close_count = 0

        def close(self) -> None:
            self.close_count += 1

    created: list[_FakeWorkerLoader] = []

    def build_loader() -> _FakeWorkerLoader:
        loader = _FakeWorkerLoader()
        created.append(loader)
        return loader

    lifecycle = YoloTaskTrainingDataLoaderLifecycle()
    resolved = [
        lifecycle.resolve(augmentation_options=None, build_loader=build_loader)
        for _ in range(5)
    ]
    lifecycle.close()

    assert all(loader is resolved[0] for loader in resolved)
    assert len(created) == 1
    assert created[0].close_count == 1


def test_infinite_dataloader_close_releases_worker_process_handles() -> None:
    """回收 worker 后必须 join 并关闭父进程 Process 句柄。"""

    class _FakeWorker:
        def __init__(self, *, terminate_sticks: bool) -> None:
            self.alive = True
            self.terminate_sticks = terminate_sticks
            self.terminate_count = 0
            self.kill_count = 0
            self.join_count = 0
            self.close_count = 0

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            self.terminate_count += 1
            if not self.terminate_sticks:
                self.alive = False

        def kill(self) -> None:
            self.kill_count += 1
            self.alive = False

        def join(self, *, timeout: float) -> None:
            assert timeout > 0
            self.join_count += 1

        def close(self) -> None:
            assert self.alive is False
            self.close_count += 1

    normal_worker = _FakeWorker(terminate_sticks=False)
    stuck_worker = _FakeWorker(terminate_sticks=True)

    _close_yolo_dataloader_worker_processes((normal_worker, stuck_worker))

    assert (normal_worker.terminate_count, normal_worker.kill_count) == (1, 0)
    assert (normal_worker.join_count, normal_worker.close_count) == (1, 1)
    assert (stuck_worker.terminate_count, stuck_worker.kill_count) == (1, 1)
    assert (stuck_worker.join_count, stuck_worker.close_count) == (2, 1)


@pytest.mark.skipif(os.name != "nt", reason="只验证 Windows spawn Process 句柄释放")
def test_infinite_dataloader_closes_real_windows_worker_handles() -> None:
    """真实 DataLoader worker 退出后，父进程 Process 对象必须进入 closed 状态。"""

    dataset = torch.utils.data.TensorDataset(torch.arange(8, dtype=torch.float32))
    loader = YoloInfiniteDataLoader(
        dataset,
        torch_module=torch,
        batch_size=2,
        num_workers=2,
        persistent_workers=True,
    )
    next(iter(loader))
    workers = tuple(loader.iterator._workers)

    loader.close()

    assert len(workers) == 2
    assert all(getattr(worker, "_popen", object()) is None for worker in workers)
    assert all(worker.is_alive() is False for worker in workers)


@pytest.mark.skipif(os.name != "nt", reason="只验证 Windows spawn 句柄高水位")
def test_infinite_dataloader_repeated_close_does_not_leak_windows_handles() -> None:
    """重复创建并关闭 DataLoader 后，父进程句柄数不得阶梯增长。"""

    def read_handle_count() -> int:
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetProcessHandleCount.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        )
        kernel32.GetProcessHandleCount.restype = ctypes.c_int
        count = ctypes.c_ulong()
        success = kernel32.GetProcessHandleCount(
            kernel32.GetCurrentProcess(),
            ctypes.byref(count),
        )
        assert success
        return int(count.value)

    dataset = torch.utils.data.TensorDataset(torch.arange(8, dtype=torch.float32))

    # 先完成一次 multiprocessing 的惰性初始化，再记录稳定基线。
    warmup = YoloInfiniteDataLoader(
        dataset,
        torch_module=torch,
        batch_size=2,
        num_workers=2,
        persistent_workers=True,
    )
    next(iter(warmup))
    warmup.close()
    del warmup
    gc.collect()
    baseline = read_handle_count()

    for _ in range(3):
        loader = YoloInfiniteDataLoader(
            dataset,
            torch_module=torch,
            batch_size=2,
            num_workers=2,
            persistent_workers=True,
        )
        next(iter(loader))
        loader.close()
        del loader
        gc.collect()

    assert read_handle_count() <= baseline + 2


def test_common_validation_schedule_uses_completed_one_based_epochs() -> None:
    """evaluation_interval=20 必须在页面第 20/40 轮触发，而不是第 21/41 轮。"""

    assert (
        should_run_yolo_validation(
            epoch_index=18,
            max_epochs=200,
            evaluation_interval=20,
            has_validation_samples=True,
        )
        is False
    )
    assert (
        should_run_yolo_validation(
            epoch_index=19,
            max_epochs=200,
            evaluation_interval=20,
            has_validation_samples=True,
        )
        is True
    )
    assert (
        should_run_yolo_validation(
            epoch_index=39,
            max_epochs=200,
            evaluation_interval=20,
            has_validation_samples=True,
        )
        is True
    )
    assert (
        should_run_yolo_validation(
            epoch_index=199,
            max_epochs=200,
            evaluation_interval=999,
            has_validation_samples=True,
        )
        is True
    )
    assert (
        should_run_yolo_validation(
            epoch_index=199,
            max_epochs=200,
            evaluation_interval=20,
            has_validation_samples=False,
        )
        is False
    )


def test_common_conv_preserves_spatial_shape_with_same_padding() -> None:
    """验证 common Conv 的 same padding 行为。"""

    layer = Conv(3, 8, k=3, s=1)
    layer.eval()

    with torch.inference_mode():
        output = layer(torch.randn(2, 3, 16, 16))

    assert output.shape == (2, 8, 16, 16)


def test_common_dfl_decoder_returns_distance_channels() -> None:
    """验证 DFL 解码器输出 4 个距离通道。"""

    decoder = DistributionFocalLossDecoder(reg_max=4)
    logits = torch.zeros(1, 16, 3)

    distances = decoder(logits)

    assert distances.shape == (1, 4, 3)
    assert torch.allclose(distances, torch.full_like(distances, 1.5))


def test_common_anchor_and_bbox_decode_match_expected_grid() -> None:
    """验证 anchor 生成和 xyxy 解码的基础几何行为。"""

    feature = torch.zeros(1, 4, 2, 2)
    anchor_points, stride_tensor = make_anchors(
        feature_maps=(feature,),
        strides=(8,),
    )
    distances = torch.ones(1, 4, 4)

    decoded = dist2bbox_xyxy(
        distances=distances,
        anchor_points=anchor_points.unsqueeze(0),
        stride_tensor=stride_tensor.unsqueeze(0),
    )

    assert anchor_points.tolist() == [
        [0.5, 0.5],
        [1.5, 0.5],
        [0.5, 1.5],
        [1.5, 1.5],
    ]
    assert decoded.shape == (1, 4, 4)
    assert decoded[0, :, 0].tolist() == [-4.0, -4.0, 12.0, 12.0]


def test_common_detection_decode_builds_prediction_tensor() -> None:
    """验证 detection decode 入口会组装 box 与类别分数。"""

    feature = torch.zeros(1, 8, 1, 2)
    raw_outputs = {
        "boxes": torch.zeros(1, 16, 2),
        "scores": torch.zeros(1, 2, 2),
        "feats": (feature,),
    }
    decoder = DistributionFocalLossDecoder(reg_max=4)

    decoded_boxes = decode_detection_boxes(
        raw_outputs=raw_outputs,
        strides=(8,),
        dfl_decoder=decoder,
    )
    prediction = build_detection_prediction(
        raw_outputs=raw_outputs,
        strides=(8,),
        dfl_decoder=decoder,
    )

    assert decoded_boxes.shape == (1, 4, 2)
    assert prediction.shape == (1, 6, 2)
    assert torch.allclose(prediction[:, 4:, :], torch.full((1, 2, 2), 0.5))


def test_common_detection_training_decode_builds_loss_bundle() -> None:
    """验证 detection 训练态 decode 会返回 loss 所需的公共预测结构。"""

    feature = torch.zeros(1, 8, 1, 1)
    raw_outputs = {
        "boxes": torch.zeros(1, 16, 1),
        "scores": torch.zeros(1, 2, 1),
        "feats": (feature,),
    }
    head = torch.nn.Module()
    head.reg_max = 4
    head.strides = (8,)
    head.dfl = DistributionFocalLossDecoder(reg_max=4)

    prediction_bundle = decode_detection_training_predictions(
        torch_module=torch,
        detect_head=head,
        raw_outputs=raw_outputs,
    )

    assert prediction_bundle["distance_logits"].shape == (1, 1, 16)
    assert prediction_bundle["boxes_xyxy"].shape == (1, 1, 4)
    assert prediction_bundle["class_logits"].shape == (1, 1, 2)
    assert prediction_bundle["anchor_points"].tolist() == [[0.5, 0.5]]
    assert prediction_bundle["stride_tensor"].tolist() == [[8.0]]
    assert prediction_bundle["reg_max"] == 4


def test_common_detection_assigner_target_and_dfl_loss() -> None:
    """验证 detection assigner、target 编码和 DFL loss 可以独立工作。"""

    pred_boxes = torch.tensor(
        [
            [0.0, 0.0, 16.0, 16.0],
            [100.0, 100.0, 120.0, 120.0],
        ]
    )
    class_probabilities = torch.tensor([[0.9, 0.1], [0.1, 0.8]])
    anchor_centers_xy = torch.tensor([[8.0, 8.0], [110.0, 110.0]])
    gt_boxes = torch.tensor([[0.0, 0.0, 16.0, 16.0]])
    gt_classes = torch.tensor([0], dtype=torch.long)

    assignment = assign_detection_targets(
        torch_module=torch,
        pred_boxes=pred_boxes,
        class_probabilities=class_probabilities,
        anchor_centers_xy=anchor_centers_xy,
        gt_boxes=gt_boxes,
        gt_classes=gt_classes,
        topk=1,
        alpha=0.5,
        beta=6.0,
    )
    target_distances = bbox_xyxy_to_distances(
        torch_module=torch,
        boxes_xyxy=gt_boxes,
        anchor_points=torch.tensor([[1.0, 1.0]]),
        stride_tensor=torch.tensor([[8.0]]),
        reg_max=4,
    )
    dfl_loss = distribution_focal_loss(
        torch_module=torch,
        logits=torch.zeros(1, 4, 4),
        target=target_distances,
    )

    assert assignment["foreground_mask"].tolist() == [True, False]
    assert assignment["assigned_gt_indices"].tolist() == [0, -1]
    assert (
        torch.isclose(assignment["quality_scores"][0], torch.tensor(1.0)).item() is True
    )
    assert torch.allclose(
        box_iou_aligned(torch_module=torch, boxes1=gt_boxes, boxes2=gt_boxes),
        torch.ones(1),
    )
    assert target_distances.tolist() == [[1.0, 1.0, 1.0, 1.0]]
    assert dfl_loss.shape == (1,)
    assert torch.isfinite(dfl_loss).all().item() is True


def test_common_segmentation_assigner_and_detection_loss() -> None:
    """验证 segmentation assigner 和检测损失编排可独立工作。"""

    prediction = torch.zeros(2, 6)
    prediction[:, :4] = torch.tensor(
        [
            [4.0, 4.0, 4.0, 4.0],
            [4.0, 4.0, 4.0, 4.0],
        ]
    )
    prediction[0, 4] = 5.0
    prediction[1, 5] = 5.0
    anchor_points = torch.tensor([[8.0, 8.0], [32.0, 32.0]])
    stride_tensor = torch.tensor([[8.0], [8.0]])
    targets = {
        "boxes": [[4.0, 4.0, 12.0, 12.0]],
        "class_ids": [0],
    }

    assignment = assign_segmentation_targets(
        torch_module=torch,
        targets=targets,
        prediction=prediction,
        anchor_points=anchor_points,
        stride_tensor=stride_tensor,
        topk=1,
        alpha=0.5,
        beta=6.0,
        num_classes=2,
    )

    assert assignment is not None
    assert assignment.fg_mask.tolist() == [True, False]
    decoded_boxes = decode_segmentation_training_boxes(
        torch_module=torch,
        prediction=prediction,
        anchor_points=anchor_points,
    )
    iou = segmentation_bbox_iou_aligned(
        torch_module=torch,
        boxes1=decoded_boxes[:1],
        boxes2=torch.tensor([[4.0, 4.0, 12.0, 12.0]]),
    )
    class_loss, box_loss, dfl_loss = compute_segmentation_detection_loss(
        torch_module=torch,
        prediction=prediction,
        assignment=assignment,
        anchor_points=anchor_points,
        stride_tensor=stride_tensor,
        dfl_weight=1.5,
        num_classes=2,
    )

    assert torch.allclose(decoded_boxes[0], torch.tensor([4.0, 4.0, 12.0, 12.0]))
    assert torch.allclose(iou, torch.ones(1))
    assert torch.isfinite(class_loss).item() is True
    assert torch.isclose(box_loss, torch.tensor(0.0)).item() is True
    assert torch.isclose(dfl_loss, torch.tensor(0.0)).item() is True


def test_common_pose_decode_supports_standard_and_yolo26_offsets() -> None:
    """验证 pose decode 可显式区分标准 YOLO 和 YOLO26 偏移规则。"""

    feature = torch.zeros(1, 4, 1, 1)
    raw_outputs = {
        "kpts": torch.tensor([[[1.0], [2.0], [0.0]]]),
        "feats": (feature,),
    }

    standard = decode_pose_keypoints(
        raw_outputs=raw_outputs,
        strides=(8,),
        keypoint_shape=(1, 3),
        offset_multiplier=2.0,
        anchor_offset=-0.5,
    )
    yolo26 = decode_pose_keypoints(
        raw_outputs=raw_outputs,
        strides=(8,),
        keypoint_shape=(1, 3),
        offset_multiplier=1.0,
        anchor_offset=0.0,
    )

    assert standard.shape == (1, 3, 1)
    assert torch.allclose(standard, torch.tensor([[[16.0], [32.0], [0.5]]]))
    assert torch.allclose(yolo26, torch.tensor([[[12.0], [20.0], [0.5]]]))


def test_common_pose_losses_compute_keypoint_and_visibility() -> None:
    """验证 common pose loss 辅助函数可以脱离训练 service 独立工作。"""

    pred_xy = torch.tensor([[[0.0, 0.0], [2.0, 2.0]]])
    gt_keypoints = torch.tensor([[[0.0, 0.0, 2.0], [4.0, 2.0, 1.0]]])
    keypoint_mask = build_pose_visibility_mask(
        torch_module=torch,
        gt_keypoints=gt_keypoints,
        keypoint_dim=3,
    )
    area = build_pose_box_area(gt_boxes=torch.tensor([[0.0, 0.0, 4.0, 4.0]]))
    sigmas = build_pose_oks_sigmas(
        torch_module=torch,
        num_keypoints=2,
        device=pred_xy.device,
        dtype=pred_xy.dtype,
    )

    keypoint_loss = compute_oks_keypoint_loss(
        torch_module=torch,
        pred_keypoints_xy=pred_xy,
        gt_keypoints_xy=gt_keypoints[..., :2],
        keypoint_mask=keypoint_mask,
        area=area,
        sigmas=sigmas,
    )
    visibility_loss = compute_visibility_loss(
        torch_module=torch,
        pred_visibility_logits=torch.zeros(1, 2),
        keypoint_mask=keypoint_mask,
    )
    standard_xy = decode_pose_keypoints_xy(
        pred_xy=torch.ones(1, 2, 2),
        anchors_xy=torch.tensor([[4.0, 8.0]]),
        strides=torch.tensor([[2.0]]),
        is_pose26=False,
    )
    pose26_xy = decode_pose_keypoints_xy(
        pred_xy=torch.ones(1, 2, 2),
        anchors_xy=torch.tensor([[4.0, 8.0]]),
        strides=torch.tensor([[2.0]]),
        is_pose26=True,
    )

    assert keypoint_mask.tolist() == [[True, True]]
    assert torch.isfinite(keypoint_loss).item() is True
    assert torch.isfinite(visibility_loss).item() is True
    assert torch.allclose(standard_xy, torch.tensor([[[8.0, 12.0], [8.0, 12.0]]]))
    assert torch.allclose(pose26_xy, torch.tensor([[[6.0, 10.0], [6.0, 10.0]]]))


def test_common_pose_oks_loss_keeps_large_fp16_coordinates_finite() -> None:
    """验证大图坐标和面积不会在 FP16 OKS 路径中形成 Inf/Inf。"""

    pred_xy = torch.full((1, 21, 2), 384.0, dtype=torch.float16)
    gt_xy = torch.zeros_like(pred_xy)
    keypoint_mask = torch.ones((1, 21), dtype=torch.bool)
    area = build_pose_box_area(
        gt_boxes=torch.tensor([[0.0, 0.0, 384.0, 384.0]], dtype=torch.float16)
    )
    sigmas = build_pose_oks_sigmas(
        torch_module=torch,
        num_keypoints=21,
        device=pred_xy.device,
        dtype=pred_xy.dtype,
    )

    loss = compute_oks_keypoint_loss(
        torch_module=torch,
        pred_keypoints_xy=pred_xy,
        gt_keypoints_xy=gt_xy,
        keypoint_mask=keypoint_mask,
        area=area,
        sigmas=sigmas,
    )

    assert area.dtype == torch.float32
    assert area.item() == 384.0 * 384.0
    assert loss.dtype == torch.float32
    assert torch.isfinite(loss).item() is True


def test_common_bbox_ciou_keeps_large_fp16_coordinates_finite() -> None:
    """验证原图像素坐标平方不会在 FP16 CIoU 路径中溢出。"""

    from backend.service.application.models.yolo_core_common.losses.box import (
        bbox_ciou_matrix,
    )

    boxes1 = torch.tensor(
        [[0.0, 0.0, 384.0, 384.0]],
        dtype=torch.float16,
    )
    boxes2 = torch.tensor(
        [[8.0, 12.0, 376.0, 372.0]],
        dtype=torch.float16,
    )

    ciou = bbox_ciou_matrix(
        torch_module=torch,
        boxes1=boxes1,
        boxes2=boxes2,
    )

    assert ciou.dtype == torch.float32
    assert torch.isfinite(ciou).all()
    assert float(ciou.item()) > 0.0


def test_yolo26_pose_rle_loss_lives_in_yolo26_core() -> None:
    """验证 YOLO26 pose RLE loss 留在 yolo26_core 边界内。"""

    pred_xy = torch.tensor([[[0.0, 0.0], [2.0, 2.0]]])
    gt_keypoints = torch.tensor([[[0.0, 0.0, 2.0], [4.0, 2.0, 1.0]]])
    keypoint_mask = build_pose_visibility_mask(
        torch_module=torch,
        gt_keypoints=gt_keypoints,
        keypoint_dim=3,
    )
    rle_loss = compute_yolo26_rle_loss(
        torch_module=torch,
        flow_model=_DummyPoseFlowModel(),
        pred_keypoints_xy=pred_xy,
        pred_sigma_logits=torch.zeros(1, 2, 2),
        gt_keypoints_xy=gt_keypoints[..., :2],
        keypoint_mask=keypoint_mask,
        target_weights=build_yolo26_pose_rle_weights(
            torch_module=torch,
            num_keypoints=2,
            device=pred_xy.device,
            dtype=pred_xy.dtype,
        ),
    )

    assert torch.isfinite(rle_loss).item() is True


def test_yolo26_pose_rle_loss_promotes_extreme_fp16_sigma_to_fp32() -> None:
    """验证 FP16 sigmoid 下溢前先提升精度，不丢弃有效 RLE 样本。"""

    pred_xy = torch.full((1, 1, 2), 100.0, dtype=torch.float16)
    gt_xy = torch.zeros_like(pred_xy)
    rle_loss = compute_yolo26_rle_loss(
        torch_module=torch,
        flow_model=_DummyPoseFlowModel(),
        pred_keypoints_xy=pred_xy,
        pred_sigma_logits=torch.full((1, 1, 2), -20.0, dtype=torch.float16),
        gt_keypoints_xy=gt_xy,
        keypoint_mask=torch.ones((1, 1), dtype=torch.bool),
        target_weights=torch.ones(1, dtype=torch.float16),
    )

    assert rle_loss.dtype == torch.float32
    assert torch.isfinite(rle_loss).item() is True
    assert rle_loss.item() > 0.0


def test_common_pose_target_normalizes_list_and_tensor_keypoints() -> None:
    """验证 pose target 编码会规整 list 和 tensor 两类关键点输入。"""

    assigned_indices = torch.tensor([1, 0], dtype=torch.long)
    list_keypoints = [
        [1.0, 2.0, 2.0, 3.0, 4.0, 1.0],
        [5.0, 6.0, 2.0, 7.0, 8.0, 1.0],
    ]
    tensor_keypoints = torch.tensor(
        [
            [[1.0, 2.0, 2.0], [3.0, 4.0, 1.0]],
            [[5.0, 6.0, 2.0], [7.0, 8.0, 1.0]],
        ]
    )

    normalized_from_list = normalize_gt_keypoints_tensor(
        torch_module=torch,
        raw_keypoints=list_keypoints,
        assigned_indices=assigned_indices,
        num_keypoints=2,
        keypoint_dim=3,
        device=torch.device("cpu"),
        dtype=torch.float32,
    )
    normalized_from_tensor = normalize_gt_keypoints_tensor(
        torch_module=torch,
        raw_keypoints=tensor_keypoints,
        assigned_indices=assigned_indices,
        num_keypoints=2,
        keypoint_dim=3,
        device=torch.device("cpu"),
        dtype=torch.float32,
    )

    expected = torch.tensor(
        [
            [[5.0, 6.0, 2.0], [7.0, 8.0, 1.0]],
            [[1.0, 2.0, 2.0], [3.0, 4.0, 1.0]],
        ]
    )
    assert torch.allclose(normalized_from_list, expected)
    assert torch.allclose(normalized_from_tensor, expected)


def test_common_obb_angle_decode_supports_standard_and_raw_modes() -> None:
    """验证 OBB angle decode 可显式区分标准模式和 YOLO26 raw 模式。"""

    angle_logits = torch.zeros(1, 1, 1)

    standard = decode_obb_angle_logits(
        angle_logits=angle_logits,
        mode=OBB_ANGLE_DECODE_MODE_SIGMOID_MINUS_QUARTER_PI,
    )
    raw = decode_obb_angle_logits(
        angle_logits=angle_logits,
        mode=OBB_ANGLE_DECODE_MODE_RAW,
    )

    assert torch.allclose(standard, torch.full_like(standard, torch.pi / 4))
    assert torch.allclose(raw, torch.zeros_like(raw))


def test_common_obb_decode_builds_prediction_tensor() -> None:
    """验证 OBB decode 入口会组装旋转框、类别分数和角度。"""

    feature = torch.zeros(1, 8, 1, 1)
    raw_outputs = {
        "boxes": torch.zeros(1, 16, 1),
        "scores": torch.zeros(1, 2, 1),
        "angle": torch.zeros(1, 1, 1),
        "feats": (feature,),
    }
    decoder = DistributionFocalLossDecoder(reg_max=4)

    prediction = build_obb_prediction(
        raw_outputs=raw_outputs,
        strides=(8,),
        dfl_decoder=decoder,
        angle_decode_mode=OBB_ANGLE_DECODE_MODE_RAW,
    )

    assert prediction.shape == (1, 7, 1)
    assert torch.allclose(prediction[:, 4:6, :], torch.full((1, 2, 1), 0.5))
    assert torch.allclose(prediction[:, 6:, :], torch.zeros(1, 1, 1))


def test_common_obb_loss_and_target_helpers_work_independently() -> None:
    """验证 OBB loss、target 编码和旋转框几何辅助函数可以独立工作。"""

    rboxes = torch.tensor([[10.0, 10.0, 4.0, 2.0, 0.0]])
    probiou = probiou_aligned(torch_module=torch, obb1=rboxes, obb2=rboxes)
    corners = xywhr_to_corners(torch_module=torch, rboxes=rboxes)
    inside_mask = anchor_in_rotated_box(
        torch_module=torch,
        anchor_points=torch.tensor([[10.0, 10.0], [20.0, 20.0]]),
        corners=corners,
    )
    encoded_distances = rbox_to_distances(
        torch_module=torch,
        rboxes=rboxes,
        anchor_points=torch.tensor([[1.25, 1.25]]),
        stride_tensor=torch.tensor([[8.0]]),
        reg_max=4,
    )
    decoded_rboxes = decode_distances_to_rboxes(
        torch_module=torch,
        pred_dist=torch.tensor([[[1.0, 1.0, 1.0, 1.0]]]),
        pred_angle=torch.zeros(1, 1, 1),
        anchor_points=torch.tensor([[[2.0, 3.0]]]),
    )
    angle_loss = compute_obb_angle_loss(
        torch_module=torch,
        pred_angle=torch.zeros(1, 1),
        gt_angle=torch.zeros(1, 1),
        gt_wh=torch.tensor([[4.0, 2.0]]),
        target_scores=torch.ones(1),
    )
    xyxy = xywhr_to_xyxy(torch_module=torch, rboxes=rboxes)

    assert probiou.shape == (1,)
    assert probiou.item() > 0.999
    assert corners.shape == (1, 4, 2)
    assert inside_mask.tolist() == [[True, False]]
    assert encoded_distances.tolist() == [[0.25, 0.125, 0.25, 0.125]]
    assert torch.allclose(decoded_rboxes, torch.tensor([[[2.0, 3.0, 2.0, 2.0, 0.0]]]))
    assert torch.allclose(angle_loss, torch.zeros(()))
    assert xyxy.tolist() == [[8.0, 9.0, 12.0, 11.0]]


def test_common_obb_losses_keep_large_fp16_geometry_finite() -> None:
    """验证大旋转框及极端长宽比不会在 FP16 损失中溢出。"""

    rboxes = torch.tensor(
        [[192.0, 192.0, 384.0, 320.0, 0.25]],
        dtype=torch.float16,
    )
    probiou = probiou_aligned(
        torch_module=torch,
        obb1=rboxes,
        obb2=rboxes.clone(),
    )
    angle_loss = compute_obb_angle_loss(
        torch_module=torch,
        pred_angle=torch.tensor([[0.25]], dtype=torch.float16),
        gt_angle=torch.tensor([[0.2]], dtype=torch.float16),
        gt_wh=torch.tensor([[384.0, 0.001]], dtype=torch.float16),
        target_scores=torch.ones(1, dtype=torch.float16),
    )

    assert probiou.dtype == torch.float32
    assert torch.isfinite(probiou).all()
    assert float(probiou.item()) > 0.999
    assert angle_loss.dtype == torch.float32
    assert torch.isfinite(angle_loss).item() is True


def test_common_detection_tensor_nms_inputs_filter_candidates() -> None:
    """验证 tensor 版 NMS 前置后处理会筛出高分候选。"""

    prediction = torch.tensor(
        [
            [
                [0.0, 0.0, 10.0, 10.0, 0.1, 0.8],
                [1.0, 1.0, 2.0, 2.0, 0.7, 0.2],
                [3.0, 3.0, 4.0, 4.0, 0.2, 0.3],
            ]
        ]
    )

    nms_inputs = prepare_detection_nms_inputs_tensor(
        prediction_tensor=prediction,
        num_classes=2,
        score_threshold=0.5,
    )

    assert nms_inputs is not None
    assert nms_inputs.boxes_xyxy.shape == (2, 4)
    assert nms_inputs.scores.tolist() == [0.800000011920929, 0.699999988079071]
    assert nms_inputs.class_ids.tolist() == [1, 0]
    assert nms_inputs.batch_indices.tolist() == [0, 0]


def test_common_detection_array_nms_inputs_filter_candidates() -> None:
    """验证数组版 NMS 前置后处理会筛出高分候选。"""

    image_prediction = np.asarray(
        [
            [0.0, 0.0, 10.0, 10.0, 0.1, 0.8],
            [1.0, 1.0, 2.0, 2.0, 0.7, 0.2],
            [3.0, 3.0, 4.0, 4.0, 0.2, 0.3],
        ],
        dtype=np.float32,
    )

    nms_inputs = prepare_detection_nms_inputs_array(
        image_prediction=image_prediction,
        np_module=np,
        num_classes=2,
        score_threshold=0.5,
    )

    assert nms_inputs is not None
    assert nms_inputs.boxes_xyxy.shape == (2, 4)
    assert nms_inputs.scores.tolist() == [0.800000011920929, 0.699999988079071]
    assert nms_inputs.class_ids.tolist() == [1, 0]


def test_common_segmentation_nms_inputs_preserve_mask_coefficients() -> None:
    """验证 segmentation NMS 前置后处理会保留 mask coeff。"""

    image_prediction = np.asarray(
        [
            [0.0, 0.0, 10.0, 10.0, 0.1, 0.8, 0.25, 0.5],
            [1.0, 1.0, 2.0, 2.0, 0.7, 0.2, 0.75, 1.0],
            [3.0, 3.0, 4.0, 4.0, 0.2, 0.3, 0.10, 0.2],
        ],
        dtype=np.float32,
    )

    nms_inputs = prepare_segmentation_nms_inputs_array(
        image_prediction=image_prediction,
        np_module=np,
        num_classes=2,
        score_threshold=0.5,
    )

    assert nms_inputs is not None
    assert nms_inputs.boxes_xyxy.shape == (2, 4)
    assert nms_inputs.scores.tolist() == [0.800000011920929, 0.699999988079071]
    assert nms_inputs.class_ids.tolist() == [1, 0]
    assert nms_inputs.mask_coefficients.tolist() == [[0.25, 0.5], [0.75, 1.0]]


def test_common_segmentation_mask_decode_thresholds_proto_masks() -> None:
    """验证 segmentation mask decode 会把 proto 与 coeff 还原为二值 mask。"""

    proto = np.asarray([[[10.0, -10.0], [-10.0, 10.0]]], dtype=np.float32)
    mask_coefficients = np.asarray([[1.0]], dtype=np.float32)

    masks = decode_segmentation_masks(
        cv2_module=cv2,
        np_module=np,
        proto=proto,
        mask_coefficients=mask_coefficients,
        input_size=(2, 2),
        resized_width=2,
        resized_height=2,
        image_width=2,
        image_height=2,
        mask_threshold=0.5,
    )

    assert len(masks) == 1
    assert masks[0].dtype == np.uint8
    assert masks[0].tolist() == [[1, 0], [0, 1]]


def test_common_segmentation_full_postprocess_builds_instances() -> None:
    """验证 segmentation 完整后处理会生成 bbox、mask 面积和类别实例。"""

    prediction_array, proto_array = normalize_segmentation_outputs(
        outputs=(
            np.asarray([[0.0, 0.0, 2.0, 2.0, 0.9, 1.0]], dtype=np.float32),
            np.asarray([[[10.0, 10.0], [10.0, 10.0]]], dtype=np.float32),
        ),
        np_module=np,
    )

    nms_results = postprocess_segmentation_prediction_array(
        prediction_array=prediction_array,
        np_module=np,
        num_classes=1,
        score_threshold=0.5,
        nms_threshold=0.65,
        nms_indices_func=_keep_all_nms_indices,
    )
    instances = build_segmentation_postprocess_instances(
        cv2_module=cv2,
        np_module=np,
        prediction_array=prediction_array,
        proto_array=proto_array,
        labels=("defect",),
        score_threshold=0.5,
        nms_threshold=0.65,
        mask_threshold=0.5,
        resize_ratio=1.0,
        image_width=2,
        image_height=2,
        input_size=(2, 2),
        nms_indices_func=_keep_all_nms_indices,
    )

    assert nms_results[0] is not None
    assert nms_results[0].scores.tolist() == [0.8999999761581421]
    assert len(instances) == 1
    assert instances[0].bbox_xyxy == (0.0, 0.0, 2.0, 2.0)
    assert instances[0].class_name == "defect"
    assert instances[0].mask_area == 4.0


def test_common_segmentation_export_boundary_requires_prediction_and_proto() -> None:
    """验证 segmentation export 边界固定为 prediction/proto 双输出。"""

    prediction = np.zeros((1, 1, 6), dtype=np.float32)
    proto = np.zeros((1, 1, 2, 2), dtype=np.float32)

    normalized_prediction, normalized_proto = normalize_segmentation_export_outputs(
        outputs=[prediction, proto],
    )

    assert resolve_segmentation_export_output_names() == ("predictions", "proto")
    assert normalized_prediction is prediction
    assert normalized_proto is proto


def test_common_segmentation_mask_target_and_loss_helpers_work_independently() -> None:
    """验证 segmentation polygon target 和 mask loss 可以独立工作。"""

    segmentations = [[2.0, 2.0, 6.0, 2.0, 6.0, 6.0, 2.0, 6.0]]
    polygons = select_object_segmentation_polygons(
        segmentations,
        object_index=0,
        object_count=1,
    )
    mask, valid = rasterize_segmentation_polygons(
        cv2_module=cv2,
        np_module=np,
        polygons=polygons,
        output_size=(8, 8),
        resize_scale=1.0,
        pad_xy=(0, 0),
    )
    prediction = torch.tensor(
        [
            [0.0, 0.0, 1.0, 1.0, 4.0, 1.0],
            [0.0, 0.0, 1.0, 1.0, -4.0, -1.0],
        ],
        dtype=torch.float32,
    )
    proto = torch.zeros(1, 2, 2)
    proto[0, 0, 0] = 1.0
    proto[0, 0, 1] = -1.0
    proto[0, 1, 0] = -1.0
    proto[0, 1, 1] = -1.0
    target_masks = torch.tensor(
        [
            [
                [1.0, 0.0],
                [0.0, 0.0],
            ]
        ]
    )
    mask_loss = compute_segmentation_mask_loss(
        torch_module=torch,
        prediction=prediction,
        proto=proto,
        foreground_mask=torch.tensor([True, False]),
        target_masks=target_masks,
        target_mask_valid=torch.tensor([True]),
        matched_gt_indices=torch.tensor([0, 0]),
        num_classes=1,
    )

    assert valid is True
    assert int(mask.sum()) > 0
    assert torch.isfinite(mask_loss).item() is True
    assert float(mask_loss.item()) < 0.5


def test_common_segmentation_target_decodes_compressed_coco_rle() -> None:
    """验证 YOLO segmentation 不会静默丢弃 compressed COCO RLE。"""

    pycocotools_mask = pytest.importorskip("pycocotools.mask")
    from backend.service.application.models.yolo_core_common.targets.segmentation import (
        decode_coco_rle_mask,
        downsample_yolo_segmentation_masks,
    )

    source_mask = np.zeros((7, 9), dtype=np.uint8)
    source_mask[1:5, 2:7] = 1
    encoded = pycocotools_mask.encode(np.asfortranarray(source_mask))
    decoded = decode_coco_rle_mask(
        segmentation={
            "size": [7, 9],
            "counts": encoded["counts"].decode("ascii"),
        },
        np_module=np,
    )

    assert np.array_equal(decoded, source_mask)
    full_masks = np.zeros((100, 640, 640), dtype=np.uint8)
    reduced_masks = downsample_yolo_segmentation_masks(
        full_masks,
        cv2_module=cv2,
        np_module=np,
    )
    assert reduced_masks.shape == (100, 160, 160)
    assert reduced_masks.nbytes == full_masks.nbytes // 16


def test_common_segmentation_mask_downsample_matches_ultralytics_resize() -> None:
    """细目标 mask 必须逐实例匹配 Ultralytics OpenCV resize，而不是步长抽样。"""

    from backend.service.application.models.yolo_core_common.targets.segmentation import (
        downsample_yolo_segmentation_masks,
    )

    full_mask = np.zeros((1, 16, 16), dtype=np.uint8)
    cv2.line(full_mask[0], (1, 15), (14, 0), color=1, thickness=2)
    expected = cv2.resize(full_mask[0], (4, 4), interpolation=cv2.INTER_LINEAR)
    stride_sample = full_mask[:, ::4, ::4]

    reduced = downsample_yolo_segmentation_masks(
        full_mask,
        cv2_module=cv2,
        np_module=np,
    )

    assert np.array_equal(reduced[0], expected)
    assert not np.array_equal(reduced, stride_sample)


def test_common_segmentation_evaluation_masks_preserve_full_resolution() -> None:
    """验证 COCO AP 可无损恢复完整 mask，且不把 dense mask 跨进程传输。"""

    from backend.service.application.models.yolo_core_common.targets.segmentation import (
        pack_yolo_segmentation_evaluation_masks,
        unpack_yolo_segmentation_evaluation_masks,
    )

    masks = np.zeros((2, 17, 19), dtype=np.uint8)
    masks[0, 2:15, 7] = 1
    masks[1, 5:9, 3:14] = 1

    packed = pack_yolo_segmentation_evaluation_masks(masks, np_module=np)
    restored = unpack_yolo_segmentation_evaluation_masks(packed, np_module=np)

    assert restored is not None
    assert np.array_equal(restored, masks)
    assert all(isinstance(item["bits"], bytes) for item in packed)
    assert sum(len(item["bits"]) for item in packed) < masks.nbytes


def test_common_segmentation_polygon_rasterization_matches_reference_truncation() -> None:
    """验证 polygon 坐标按参考实现直接转 int32，而不是四舍五入。"""

    mask, valid = rasterize_segmentation_polygons(
        cv2_module=cv2,
        np_module=np,
        polygons=[[1.9, 1.9, 5.9, 1.9, 5.9, 5.9, 1.9, 5.9]],
        output_size=(8, 8),
        resize_scale=1.0,
        pad_xy=(0, 0),
    )

    expected = np.zeros((8, 8), dtype=np.uint8)
    cv2.fillPoly(
        expected,
        [np.asarray([[1, 1], [5, 1], [5, 5], [1, 5]], dtype=np.int32)],
        1,
    )
    assert valid is True
    assert np.array_equal(mask, expected)


def test_task_evaluation_dataloader_uses_full_validation_split_by_default() -> None:
    """验证训练期验证默认不再只抽取前 8 个样本。"""

    plan = YoloTaskDataLoaderPlan(
        num_workers=0,
        pin_memory=False,
        prefetch_factor=2,
        persistent_workers=False,
        seed=0,
    )
    samples = tuple(range(12))
    full_loader = build_yolo_task_evaluation_dataloader(
        torch_module=torch,
        samples=samples,
        input_size=(64, 64),
        plan=plan,
        build_batch=lambda **kwargs: kwargs["samples"],
        load_imports=lambda: None,
    )
    quick_loader = build_yolo_task_evaluation_dataloader(
        torch_module=torch,
        samples=samples,
        input_size=(64, 64),
        plan=plan,
        build_batch=lambda **kwargs: kwargs["samples"],
        load_imports=lambda: None,
        max_samples=8,
    )

    assert len(full_loader.dataset) == 12
    assert len(quick_loader.dataset) == 8
    full_loader.close()
    quick_loader.close()


def test_task_evaluation_dataloader_batches_full_split_and_tail() -> None:
    """验证 validator 使用显式 batch，并完整保留最后一个不足批次。"""

    plan = YoloTaskDataLoaderPlan(
        num_workers=0,
        pin_memory=False,
        prefetch_factor=2,
        persistent_workers=False,
        seed=0,
    )
    loader = build_yolo_task_evaluation_dataloader(
        torch_module=torch,
        samples=tuple(range(12)),
        batch_size=5,
        input_size=(64, 64),
        plan=plan,
        build_batch=lambda **kwargs: tuple(kwargs["samples"]),
        load_imports=lambda: SimpleNamespace(torch=torch),
    )

    with managed_yolo_task_evaluation_dataloader(loader):
        assert [len(batch) for batch in loader] == [5, 5, 2]


def test_task_evaluation_items_keep_targets_outputs_and_image_ids_aligned() -> None:
    """验证批量前向输出按图切分，且跨 batch 的 image_id 连续。"""

    prediction = np.arange(3 * 4, dtype=np.float32).reshape(3, 4)
    proto = np.arange(3 * 2 * 2, dtype=np.float32).reshape(3, 2, 2)
    items = list(
        iter_yolo_task_evaluation_items(
            targets=("first", "second", "tail"),
            batched_outputs=(prediction, proto),
            image_index_start=7,
        )
    )

    assert [item[0] for item in items] == [7, 8, 9]
    assert [item[1] for item in items] == ["first", "second", "tail"]
    assert all(item[2][0].shape == (1, 4) for item in items)
    assert all(item[2][1].shape == (1, 2, 2) for item in items)
    assert np.array_equal(items[1][2][0], prediction[1:2])
    assert np.array_equal(items[2][2][1], proto[2:3])


def test_task_evaluation_items_reject_mismatched_batch_dimensions() -> None:
    """验证输出 batch 维不一致时明确失败，禁止静默污染指标。"""

    with pytest.raises(InvalidRequestError, match="输出与 target batch 数量不一致"):
        list(
            iter_yolo_task_evaluation_items(
                targets=("first", "second"),
                batched_outputs=(np.zeros((1, 4), dtype=np.float32),),
                image_index_start=0,
            )
        )


def test_common_rotated_bbox_decode_preserves_axis_aligned_width_height() -> None:
    """验证零角度 rotated bbox 解码会保留距离宽高。"""

    distances = torch.tensor([[[1.0], [2.0], [3.0], [4.0]]])
    angle = torch.zeros(1, 1, 1)
    anchor_points = torch.tensor([[10.0, 20.0]])

    decoded = dist2rbox(
        pred_dist=distances,
        pred_angle=angle,
        anchor_points=anchor_points,
    )

    assert decoded.shape == (1, 4, 1)
    assert torch.allclose(
        decoded,
        torch.tensor([[[11.0], [21.0], [4.0], [6.0]]]),
    )


def _keep_all_nms_indices(*, scores, np_module, **_kwargs):
    """测试用 NMS：保留所有候选。"""

    return np_module.arange(int(scores.shape[0]))


class _DummyPoseFlowModel:
    """测试用的最小 flow 模型。"""

    def log_prob(self, x: torch.Tensor) -> torch.Tensor:
        """返回稳定的伪 log probability。"""

        return -(x.pow(2).sum(dim=1))
