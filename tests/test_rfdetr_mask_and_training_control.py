"""RF-DETR mask 解码和真实训练循环控制回归测试。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from backend.service.application.models.rfdetr_core.datasets.coco import (
    _build_train_resize_config,
    convert_coco_poly_to_mask,
)
from backend.service.application.models.rfdetr_core.models import (
    matcher as rfdetr_matcher_module,
)
from backend.service.application.models.rfdetr_core.models.matcher import (
    HungarianMatcher,
)
from backend.service.application.models.rfdetr_core.segmentation import (
    RfdetrSegmentationPostProcess,
    mask_logits_to_xyxy,
)
from backend.service.application.models.rfdetr_core.training.platform_control import (
    RfdetrPlatformTrainingControlCommand,
    RfdetrPlatformTrainingControlSignal,
    build_rfdetr_platform_training_callback,
)
from backend.service.application.models.rfdetr_core.training.attempt_checkpoint_io import (
    RfdetrAttemptCheckpointIO,
)
from backend.service.application.models.training import (
    rfdetr_detection_task_service as rfdetr_task_service_module,
)
from backend.service.application.models.training.rfdetr_detection import (
    RfdetrTrainingBatchProgress,
    RfdetrTrainingEpochProgress,
    RfdetrTrainingPausedError,
    RfdetrTrainingSavePoint,
)
from backend.service.application.models.training.rfdetr_detection_task_service import (
    RfdetrTrainingTaskRequest,
    SqlAlchemyRfdetrTrainingTaskService,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.domain.datasets.dataset_export import DatasetExport
from backend.service.domain.models.model_task_types import SEGMENTATION_TASK_TYPE
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base
from backend.service.infrastructure.queue.local_file import (
    LocalFileQueueBackend,
    LocalFileQueueSettings,
)


def test_rfdetr_matcher_uses_configured_focal_alpha(monkeypatch) -> None:
    """matcher 必须使用构造参数中的 focal_alpha，不能回退到固定 0.25。"""

    captured_costs: list[np.ndarray] = []

    def capture_assignment(cost_matrix):
        captured_costs.append(np.asarray(cost_matrix).copy())
        return np.asarray([0]), np.asarray([0])

    monkeypatch.setattr(
        rfdetr_matcher_module,
        "linear_sum_assignment",
        capture_assignment,
    )
    focal_alpha = 0.75
    matcher = HungarianMatcher(
        cost_class=1.0,
        cost_bbox=0.0,
        cost_giou=0.0,
        focal_alpha=focal_alpha,
    )
    target_logit = torch.tensor(-0.4)
    matcher(
        {
            "pred_logits": torch.tensor([[[0.2, float(target_logit)]]]),
            "pred_boxes": torch.tensor([[[0.5, 0.5, 0.2, 0.2]]]),
        },
        [
            {
                "labels": torch.tensor([1]),
                "boxes": torch.tensor([[0.5, 0.5, 0.2, 0.2]]),
            }
        ],
    )

    probability = target_logit.sigmoid()
    expected = (
        focal_alpha
        * ((1 - probability) ** 2)
        * (-torch.nn.functional.logsigmoid(target_logit))
        - (1 - focal_alpha)
        * (probability**2)
        * (-torch.nn.functional.logsigmoid(-target_logit))
    )
    assert len(captured_costs) == 1
    assert float(captured_costs[0][0, 0]) == pytest.approx(float(expected))


def test_rfdetr_matcher_rejects_non_divisible_group_queries() -> None:
    """Group DETR 查询数不能被组数整除时必须明确失败，避免静默丢查询。"""

    matcher = HungarianMatcher(cost_class=1.0, cost_bbox=0.0, cost_giou=0.0)
    with pytest.raises(ValueError, match=r"num_queries \(3\) must be divisible"):
        matcher(
            {
                "pred_logits": torch.zeros((1, 3, 1)),
                "pred_boxes": torch.tensor(
                    [[[0.5, 0.5, 0.2, 0.2]]] * 3,
                    dtype=torch.float32,
                ),
            },
            [
                {
                    "labels": torch.tensor([0]),
                    "boxes": torch.tensor([[0.5, 0.5, 0.2, 0.2]]),
                }
            ],
            group_detr=2,
        )


def test_rfdetr_runtime_mask_threshold_controls_decode_result() -> None:
    """运行时 mask_threshold 必须作用于插值后的 logits，不能被固定 0.5 覆盖。"""

    postprocess = RfdetrSegmentationPostProcess(num_select=1)
    outputs = {
        "pred_logits": torch.tensor([[[8.0]]]),
        "pred_boxes": torch.tensor([[[0.5, 0.5, 1.0, 1.0]]]),
        "pred_masks": torch.zeros((1, 1, 2, 2)),
    }
    target_sizes = torch.tensor([[2.0, 2.0]])

    low_threshold = postprocess(
        outputs,
        target_sizes,
        mask_threshold=0.49,
    )
    high_threshold = postprocess(
        outputs,
        target_sizes,
        mask_threshold=0.51,
    )

    assert low_threshold["masks"].shape == (1, 1, 1, 2, 2)
    assert low_threshold["masks"].dtype == torch.bool
    assert bool(low_threshold["masks"].all()) is True
    assert bool(high_threshold["masks"].any()) is False


def test_rfdetr_postprocess_bounds_topk_and_boxes() -> None:
    """小类别/查询模型不能因固定 top-k 崩溃，回归框也不得越过图像边界。"""

    postprocess = RfdetrSegmentationPostProcess(num_select=300)
    result = postprocess.postprocess(
        {
            "pred_logits": torch.tensor([[[4.0], [3.0]]]),
            "pred_boxes": torch.tensor(
                [[[-1.0, -1.0, 4.0, 4.0], [2.0, 2.0, 4.0, 4.0]]]
            ),
            "pred_masks": torch.ones((1, 2, 2, 2)),
        },
        torch.tensor([[10.0, 20.0]]),
    )

    assert result["scores"].shape == (1, 2)
    assert result["masks"].shape == (1, 2, 1, 10, 20)
    assert float(result["boxes_xyxy"].min()) >= 0.0
    assert float(result["boxes_xyxy"][..., 0::2].max()) <= 20.0
    assert float(result["boxes_xyxy"][..., 1::2].max()) <= 10.0


def test_rfdetr_mask_box_decode_accepts_channel_axis_and_uses_exclusive_max() -> None:
    """mask box 应兼容 [B,N,1,H,W] 并输出 exclusive xmax/ymax。"""

    masks = torch.zeros((1, 1, 1, 5, 6), dtype=torch.bool)
    masks[0, 0, 0, 1:4, 2:5] = True

    boxes = mask_logits_to_xyxy(masks)

    assert boxes.shape == (1, 1, 4)
    assert boxes.tolist() == [[[2.0, 1.0, 5.0, 4.0]]]


def test_rfdetr_coco_mask_decode_supports_polygon_and_both_rle_forms() -> None:
    """RF-DETR 数据入口必须正确解码 polygon、压缩 RLE 和未压缩 RLE。"""

    coco_mask = pytest.importorskip("pycocotools.mask")
    expected = np.zeros((4, 5), dtype=np.uint8)
    expected[1:3, 1:4] = 1
    compressed = coco_mask.encode(np.asfortranarray(expected))
    compressed_json = {
        "size": list(compressed["size"]),
        "counts": compressed["counts"].decode("ascii"),
    }
    uncompressed = {
        "size": [4, 5],
        "counts": _encode_uncompressed_coco_rle(expected),
    }
    polygon = [[1.0, 1.0, 4.0, 1.0, 4.0, 3.0, 1.0, 3.0]]

    decoded = convert_coco_poly_to_mask(
        [compressed_json, uncompressed, polygon],
        height=4,
        width=5,
    )

    assert decoded.shape == (3, 4, 5)
    assert torch.equal(decoded[0], torch.from_numpy(expected))
    assert torch.equal(decoded[1], torch.from_numpy(expected))
    assert int(decoded[2].sum()) > 0


def test_rfdetr_scale_jitter_controls_resize_crop_branch() -> None:
    """关闭 scale jitter 后只能保留直接 resize，不能继续随机裁剪。"""

    enabled = _build_train_resize_config(
        [384],
        square=True,
        scale_jitter=True,
    )
    disabled = _build_train_resize_config(
        [384],
        square=True,
        scale_jitter=False,
    )

    assert "OneOf" in enabled[0]
    assert enabled[0]["OneOf"]["transforms"][1]["Sequential"]["transforms"]
    assert disabled == [
        {"OneOf": {"transforms": [{"Resize": {"height": 384, "width": 384}}]}}
    ]


def test_rfdetr_lightning_callback_emits_batch_and_pauses_with_checkpoint(
    tmp_path: Path,
) -> None:
    """batch/epoch callback 必须在真实 hook 内执行，暂停前必须生成恢复 checkpoint。"""

    batch_progress = []
    epoch_progress = []
    savepoints = []

    def on_epoch(progress):
        epoch_progress.append(progress)
        return RfdetrPlatformTrainingControlCommand(pause_training=True)

    callback = build_rfdetr_platform_training_callback(
        task_type=SEGMENTATION_TASK_TYPE,
        max_epochs=3,
        checkpoint_interval=2,
        batch_callback=batch_progress.append,
        control_callback=None,
        epoch_callback=on_epoch,
        savepoint_callback=savepoints.append,
    )

    class _Trainer:
        current_epoch = 0
        global_step = 1
        num_training_batches = 4
        callback_metrics = {
            "train/loss": torch.tensor(1.25),
            "val/segm_mAP_50_95": torch.tensor(0.75),
            "ignored_nan": torch.tensor(float("nan")),
        }
        optimizers = [SimpleNamespace(param_groups=[{"lr": 2e-4}])]
        checkpoint_io = RfdetrAttemptCheckpointIO()
        strategy = SimpleNamespace(checkpoint_io=checkpoint_io)

        def save_checkpoint(self, path: str) -> None:
            self.checkpoint_io.save_checkpoint(
                {"state_dict": {"model.weight": torch.tensor([1.0])}},
                path,
            )

    trainer = _Trainer()
    callback.on_fit_start(trainer, pl_module=object())
    callback.on_train_batch_end(
        trainer,
        pl_module=object(),
        outputs={"loss": torch.tensor(1.5)},
        batch=object(),
        batch_idx=0,
    )
    with pytest.raises(RfdetrPlatformTrainingControlSignal) as raised:
        callback.on_train_epoch_end(trainer, pl_module=object())

    assert batch_progress[0].iteration == 1
    assert batch_progress[0].max_iterations == 4
    assert batch_progress[0].total_iterations == 12
    assert batch_progress[0].train_metrics["loss"] == pytest.approx(1.5)
    assert epoch_progress[0].epoch == 0
    assert epoch_progress[0].learning_rate == pytest.approx(2e-4)
    assert raised.value.status == "paused"
    checkpoint = torch.load(
        BytesIO(raised.value.savepoint.latest_checkpoint_bytes),
        map_location="cpu",
        weights_only=False,
    )
    assert torch.equal(
        checkpoint["state_dict"]["model.weight"],
        torch.tensor([1.0]),
    )
    assert savepoints == [raised.value.savepoint]
    assert savepoints[0].best_metric_value == pytest.approx(0.75)


def test_rfdetr_detection_task_pause_reaches_epoch_loop_and_persists_resume_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """detection API 控制状态必须传到 epoch callback，并在 paused 前持久化 latest。"""

    session_factory = SessionFactory(
        DatabaseSettings(url=f"sqlite:///{(tmp_path / 'rfdetr-control.db').as_posix()}")
    )
    Base.metadata.create_all(session_factory.engine)
    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-storage"))
    )
    queue = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-storage"))
    )
    manifest_key = "exports/rfdetr-control/manifest.json"
    storage.write_json(
        manifest_key,
        {
            "format_id": "coco-detection-v1",
            "classes": [{"id": 1, "name": "part"}],
        },
    )
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        unit_of_work.dataset_exports.save_dataset_export(
            DatasetExport(
                dataset_export_id="rfdetr-control-export",
                dataset_id="dataset-1",
                project_id="project-1",
                dataset_version_id="dataset-version-1",
                format_id="coco-detection-v1",
                task_type="detection",
                status="completed",
                created_at="2026-08-07T00:00:00+00:00",
                manifest_object_key=manifest_key,
                split_names=("train",),
                sample_count=1,
                category_names=("part",),
            )
        )
        unit_of_work.commit()
    finally:
        unit_of_work.close()

    service = SqlAlchemyRfdetrTrainingTaskService(
        session_factory=session_factory,
        dataset_storage=storage,
        queue_backend=queue,
    )
    submission = service.submit_training_task(
        RfdetrTrainingTaskRequest(
            project_id="project-1",
            recipe_id="default",
            model_scale="nano",
            output_model_name="rfdetr-control",
            dataset_export_id="rfdetr-control-export",
            max_epochs=3,
            batch_size=1,
            input_size=(384, 384),
            extra_options={
                "checkpoint_interval": 1,
                "checkpoint_keep_periodic": 2,
            },
        )
    )

    def fake_training(request):
        assert request.batch_callback is not None
        assert request.epoch_callback is not None
        assert request.savepoint_callback is not None
        request.batch_callback(
            RfdetrTrainingBatchProgress(
                epoch=0,
                max_epochs=3,
                iteration=1,
                max_iterations=2,
                global_iteration=1,
                total_iterations=6,
                learning_rate=1e-4,
                train_metrics={"train/loss": 1.0},
            )
        )
        service.request_training_pause(submission.task_id, requested_by="tester")
        command = request.epoch_callback(
            RfdetrTrainingEpochProgress(
                epoch=0,
                max_epochs=3,
                learning_rate=1e-4,
                train_metrics={"train/loss": 0.8},
            )
        )
        assert command is not None and command.pause_training is True
        savepoint = RfdetrTrainingSavePoint(
            latest_checkpoint_bytes=b"resume-state",
            best_checkpoint_bytes=b"best-state",
            train_metrics={"train/loss": 0.8},
            validation_metrics={"val/mAP_50_95": 0.6},
            best_metric_value=0.6,
            best_metric_name="val/mAP_50_95",
            epoch=0,
            learning_rate=1e-4,
        )
        request.savepoint_callback(savepoint)
        raise RfdetrTrainingPausedError(savepoint)

    monkeypatch.setattr(
        rfdetr_task_service_module,
        "run_rfdetr_training",
        fake_training,
    )

    try:
        result = service.process_training_task(submission.task_id)
        task = SqlAlchemyTaskService(session_factory).get_task(submission.task_id).task
    finally:
        session_factory.engine.dispose()

    assert result.status == "paused"
    assert task.state == "paused"
    assert task.progress["stage"] == "paused"
    assert task.result["latest_checkpoint_model_version_id"]
    assert task.result["model_version_id"] == task.result[
        "latest_checkpoint_model_version_id"
    ]
    assert result.latest_checkpoint_object_key is not None
    assert storage.resolve(result.latest_checkpoint_object_key).read_bytes() == b"resume-state"
    assert storage.resolve(result.checkpoint_object_key).read_bytes() == b"best-state"
    assert storage.resolve(
        f"task-runs/{submission.task_id}/output-files/checkpoints/epoch-000001.pt"
    ).read_bytes() == b"resume-state"


def _encode_uncompressed_coco_rle(mask: np.ndarray) -> list[int]:
    """按 COCO Fortran 顺序构造未压缩 RLE counts。"""

    flattened = mask.reshape(-1, order="F")
    counts: list[int] = []
    current = 0
    run_length = 0
    for value in flattened:
        bit = int(value != 0)
        if bit == current:
            run_length += 1
            continue
        counts.append(run_length)
        run_length = 1
        current = bit
    counts.append(run_length)
    return counts
