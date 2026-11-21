"""验证 pose 训练的验证损失、最佳权重和恢复轮次。"""

from dataclasses import replace
from importlib import import_module
import io
import math
from pathlib import Path

import cv2
import numpy as np
import pytest
import torch

from backend.service.application.models.yolo_core_common.training.validation_loss import (
    YoloValidationLossAccumulator,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def test_validation_loss_weights_short_final_batch_by_image_count() -> None:
    """总损失使用批次总和，损失分项使用样本加权均值。"""

    losses = YoloValidationLossAccumulator()
    losses.add_batch(payload={"loss": 6.0, "box_loss": 1.0}, sample_count=2)
    losses.add_batch(payload={"loss": 9.0, "box_loss": 4.0}, sample_count=1)

    assert losses.metrics() == {"loss": 5.0, "box_loss": 2.0}


@pytest.mark.parametrize(
    ("family", "class_prefix", "trainer_module", "regression_loss"),
    [
        ("yolov8", "YoloV8", "yolov8_core.training.pose_execution", "dfl_loss"),
        ("yolo11", "Yolo11", "yolo11_core.training.pose_trainer", "dfl_loss"),
        ("yolo26", "Yolo26", "yolo26_core.training.pose_trainer", "l1_loss"),
    ],
)
def test_pose_training_restores_best_checkpoint_epoch_and_overwrites_on_tie(
    tmp_path: Path,
    family: str,
    class_prefix: str,
    trainer_module: str,
    regression_loss: str,
) -> None:
    """用完整 CPU 训练验证恢复、损失分项和并列最高权重的实际轮次。"""

    models_module = "backend.service.application.models"
    execution = import_module(f"{models_module}.training.{family}_pose_training")
    trainer = import_module(f"{models_module}.{trainer_module}")
    request_cls = getattr(execution, f"{class_prefix}PoseTrainingExecutionRequest")
    control_cls = getattr(trainer, f"{class_prefix}PoseTrainingControlCommand")
    paused_error = getattr(trainer, f"{class_prefix}PoseTrainingPausedError")
    run_training = getattr(execution, f"run_{family}_pose_training")

    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=tmp_path))
    splits = []
    for split, sample_count in (("train", 2), ("val", 3), ("test", 1)):
        image_root = f"images/{split}"
        label_root = f"labels/{split}"
        storage.resolve(image_root).mkdir(parents=True)
        for index in range(sample_count):
            image = np.full((64, 64, 3), 100 + index * 10, dtype=np.uint8)
            assert cv2.imwrite(str(storage.resolve(f"{image_root}/{index}.png")), image)
            storage.write_text(
                f"{label_root}/{index}.txt",
                "0 0.5 0.5 0.75 0.75 0.4 0.4 2 0.6 0.6 2\n",
            )
        splits.append(
            {"name": split, "image_root": image_root, "label_root": label_root}
        )

    first_attempt = []
    resumed_attempt = []
    request = request_cls(
        dataset_storage=storage,
        manifest_payload={
            "format_id": "yolo-pose-v1",
            "category_names": ["person"],
            "splits": splits,
        },
        model_type=family,
        model_scale="nano",
        input_size=(64, 64),
        batch_size=2,
        max_epochs=4,
        evaluation_interval=2,
        extra_options={
            "device": "cpu",
            "num_workers": 0,
            "evaluation_confidence_threshold": 1.0,
            "oks_sigmas": [0.1, 0.1],
            "disable_augmentation": True,
        },
        epoch_callback=lambda progress: (
            control_cls(pause_training=True) if progress.epoch == 1 else None
        ),
        savepoint_callback=first_attempt.append,
    )
    original_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        with pytest.raises(paused_error):
            run_training(request)
        assert first_attempt[-1].is_best
        storage.write_bytes("first-best.pt", first_attempt[-1].latest_checkpoint_bytes)
        result = run_training(
            replace(
                request,
                resume_checkpoint_path=storage.resolve("first-best.pt"),
                previous_best_checkpoint_path=storage.resolve("first-best.pt"),
                epoch_callback=lambda progress: (
                    control_cls(save_checkpoint=True) if progress.epoch == 2 else None
                ),
                savepoint_callback=resumed_attempt.append,
            )
        )
    finally:
        torch.set_num_threads(original_threads)

    assert [
        (point.epoch, point.is_best, point.best_checkpoint_saved_epoch)
        for point in resumed_attempt
    ] == [(3, False, 2), (4, True, 4)]
    history = result.validation_metrics_payload["epoch_history"]
    assert [row["epoch"] for row in history] == [2, 4]
    for row in history:
        assert row["oks_ap50_95"] == 0.0
        assert math.isfinite(row["loss"]) and row["loss"] > 0
        assert {
            "box_loss",
            "class_loss",
            "kpt_loss",
            "visibility_loss",
            regression_loss,
        } <= row.keys()
        if family == "yolo26":
            assert row["rle_loss"] > 0
    assert result.best_checkpoint_saved_epoch == 4
    best_payload = torch.load(
        io.BytesIO(result.best_checkpoint_bytes), weights_only=True
    )
    assert best_payload["epoch"] == 4
    assert result.test_metrics_payload["available"]
    assert result.test_metrics_payload["checkpoint_role"] == "best"
    assert result.test_metrics_payload["epoch"] == 4
