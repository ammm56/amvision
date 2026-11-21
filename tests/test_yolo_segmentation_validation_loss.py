"""覆盖分割任务真实验证损失和并列最高分时的权重轮次。"""

from __future__ import annotations

import io
import math
from dataclasses import replace
from importlib import import_module
from pathlib import Path

import pytest

from backend.service.application.models.yolo_core_common.training.segmentation_validation import (
    SegmentationValidationLoss,
)
from tests.test_yolo_seg_pose_manifest_support import _seed_yolo_segmentation_storage


@pytest.mark.parametrize(
    ("family", "model_label", "module_name", "regression_key"),
    [
        ("yolov8", "YoloV8", "yolov8_core.training.segmentation_execution", "dfl_loss"),
        ("yolo11", "Yolo11", "training.yolo11_segmentation_training", "dfl_loss"),
        ("yolo26", "Yolo26", "training.yolo26_segmentation_training", "l1_loss"),
    ],
)
def test_segmentation_validation_uses_one_forward_and_saves_latest_tied_epoch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    model_label: str,
    module_name: str,
    regression_key: str,
) -> None:
    """真实运行两个验证轮，并在独立测试集加载第二轮最佳权重。"""
    torch = pytest.importorskip("torch")
    pytest.importorskip("pycocotools")
    storage = _seed_yolo_segmentation_storage(tmp_path)
    input_root = storage.resolve("exports/sample")
    for split, sample_count in (("train", 2), ("val", 3), ("test", 1)):
        for dirname, extension in (("images", "jpg"), ("labels", "txt")):
            source = input_root / dirname / "train" / f"sample-1.{extension}"
            destination = input_root / dirname / split
            destination.mkdir(parents=True, exist_ok=True)
            for index in range(1, sample_count + 1):
                (destination / f"sample-{index}.{extension}").write_bytes(
                    source.read_bytes()
                )
    manifest = {
        "format_id": "yolo-instance-seg-v1",
        "category_names": ["part"],
        "splits": [
            {
                "name": split,
                "image_root": f"exports/sample/images/{split}",
                "label_root": f"exports/sample/labels/{split}",
            }
            for split in ("train", "val", "test")
        ],
    }
    module = import_module(f"backend.service.application.models.{module_name}")
    evaluate_name = f"evaluate_{family}_segmentation_samples"
    evaluate = getattr(module, evaluate_name)
    evaluation_calls: list[tuple[int, list[int]]] = []

    def count_evaluation_batches(**kwargs):
        """记录每次评估的前向次数及传入训练损失的 batch 大小。"""
        batch_sizes = []
        forward_calls = []
        handle = kwargs["model"].register_forward_hook(
            lambda model, args, result: forward_calls.append(args[0].shape[0])
        )
        batch_loss = kwargs.get("batch_loss")
        if batch_loss is not None:

            def observe_loss(outputs, targets):
                batch_sizes.append(len(targets))
                return batch_loss(outputs, targets)

            kwargs["batch_loss"] = observe_loss
        try:
            return evaluate(**kwargs)
        finally:
            handle.remove()
            evaluation_calls.append((len(forward_calls), batch_sizes))

    monkeypatch.setattr(module, evaluate_name, count_evaluation_batches)
    request_type = getattr(module, f"{model_label}SegmentationTrainingExecutionRequest")
    run_training = getattr(module, f"run_{family}_segmentation_training")
    savepoints = []
    request = request_type(
        dataset_storage=storage,
        manifest_payload=manifest,
        model_type=family,
        model_scale="nano",
        max_epochs=2,
        evaluation_interval=1,
        batch_size=2,
        input_size=(96, 96),
        extra_options={
            "device": "cpu",
            "batch_mode": "fixed",
            "num_workers": 0,
            "mosaic": 0.0,
            "evaluation_confidence_threshold": 1.0,
        },
        savepoint_callback=savepoints.append,
    )
    if family == "yolov8":
        command_type = getattr(
            module, f"{model_label}SegmentationTrainingControlCommand"
        )
        paused_error = getattr(module, f"{model_label}SegmentationTrainingPausedError")
        with pytest.raises(paused_error):
            run_training(
                replace(
                    request,
                    epoch_callback=lambda progress: command_type(pause_training=True),
                )
            )
        resume_path = tmp_path / "epoch1.pt"
        resume_path.write_bytes(savepoints[-1].latest_checkpoint_bytes)
        request = replace(
            request,
            resume_checkpoint_path=resume_path,
            previous_best_checkpoint_path=resume_path,
        )
    result = run_training(request)
    assert evaluation_calls == [(2, [2, 1]), (2, [2, 1]), (1, [])]
    history = result.validation_metrics_payload["epoch_history"]
    assert [row["map50_95"] for row in history] == [0.0, 0.0]
    for row in history:
        assert math.isfinite(row["loss"]) and row["loss"] > 0.0
        for name in ("box_loss", "class_loss", regression_key, "mask_loss"):
            assert math.isfinite(row[name])
        if family == "yolo26":
            assert row["semantic_loss"] > 0.0
    assert [savepoint.epoch for savepoint in savepoints if savepoint.is_best] == [1, 2]
    assert (
        result.best_checkpoint_saved_epoch == result.test_metrics_payload["epoch"] == 2
    )
    checkpoint = torch.load(
        io.BytesIO(result.best_checkpoint_bytes), weights_only=False
    )
    assert checkpoint["epoch"] == 2


def test_segmentation_validation_loss_uses_sample_weighting() -> None:
    """部分 batch 按实际样本数参与总损失和分项损失的均值。"""
    loss = SegmentationValidationLoss(lambda raw, targets: raw)
    loss.consume((None, {"loss": 8.0, "mask_loss": 4.0}), [{}, {}])
    loss.consume((None, {"loss": 7.0, "mask_loss": 5.0}), [{}])
    assert loss.metrics() == {"loss": 5.0, "mask_loss": 3.0}
