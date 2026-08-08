"""YOLO detection 训练收尾与控制异常回归测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.service.application.models.training import yolo11_detection_training
from backend.service.application.models.training import yolo26_detection_training
from backend.service.application.models.training import yolov8_detection_training
from backend.service.application.models.training.yolo_detection_training_control import (
    YoloDetectionTrainingPausedError,
    YoloDetectionTrainingTerminatedError,
)
from backend.service.application.models.yolov8_core.training.detection_execution import (
    YoloV8DetectionTrainingPausedError,
    YoloV8DetectionTrainingSavePoint,
    YoloV8DetectionTrainingTerminatedError,
)


@pytest.mark.parametrize(
    "training_module,builder_name",
    [
        (yolo11_detection_training, "_build_yolo11_metrics_payload"),
        (yolo26_detection_training, "_build_yolo26_metrics_payload"),
    ],
)
def test_yolo11_yolo26_completed_training_builds_all_final_metrics(
    training_module: object,
    builder_name: str,
) -> None:
    """验证 completed 收尾不会因参数错位失败，并包含 train/val/test。"""

    builder = getattr(training_module, builder_name)
    validation_payload = {
        "enabled": True,
        "final_metrics": {"map50": 0.8, "map50_95": 0.6},
    }
    test_payload = {
        "available": True,
        "metrics": {"map50": 0.75, "map50_95": 0.55},
    }
    metrics_payload = builder(
        request=SimpleNamespace(implementation_mode="core"),
        resolved_splits=(SimpleNamespace(sample_count=3),),
        train_split_name="train",
        validation_split_name="val",
        train_sample_count=2,
        validation_sample_count=1,
        category_names=("part",),
        input_size=(64, 96),
        batch_size=2,
        max_epochs=1,
        evaluation_interval=1,
        device="cpu",
        gpu_count=0,
        device_ids=(),
        distributed_mode="single-process",
        runtime_precision="fp32",
        best_metric_name="val_map50_95",
        best_metric_value=0.6,
        metrics_history=[{"epoch": 1, "train_total_loss": 0.4}],
        parameter_count=100,
        warm_start_summary={"enabled": False},
        training_options={
            "min_lr_ratio": 0.01,
            "evaluation_confidence_threshold": 0.001,
            "evaluation_nms_threshold": 0.7,
            "class_loss_weight": 0.5,
            "box_loss_weight": 7.5,
            "dfl_loss_weight": 1.5,
            "assign_topk": 10,
            "assign_alpha": 0.5,
            "assign_beta": 6.0,
            "grad_clip_norm": 10.0,
        },
        optimizer=SimpleNamespace(param_groups=[{"lr": 0.001}]),
        training_schedule=SimpleNamespace(
            optimizer_name="SGD",
            initial_lr=0.01,
            weight_decay=0.0005,
            scaled_weight_decay=0.0005,
            nominal_batch_size=64,
            accumulate=1,
            warmup_iterations=0,
            warmup_momentum=0.8,
            warmup_bias_lr=0.1,
        ),
        validation_metrics_payload=validation_payload,
        test_metrics_payload=test_payload,
        augmentation_options=None,
    )

    assert metrics_payload["final_metrics"] == {
        "epoch": 1,
        "train_total_loss": 0.4,
    }
    assert metrics_payload["validation"] == validation_payload
    assert metrics_payload["test"] == test_payload


def test_yolov8_pause_error_is_translated_to_platform_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 YOLOv8 pause 不会绕过 detection 任务服务的统一异常处理。"""

    core_savepoint = YoloV8DetectionTrainingSavePoint(
        epoch=2,
        latest_checkpoint_bytes=b"latest",
        best_checkpoint_bytes=b"best",
        best_metric_name="val_map50_95",
        best_metric_value=0.5,
    )

    def pause_core(_request: object) -> object:
        raise YoloV8DetectionTrainingPausedError(core_savepoint)

    monkeypatch.setattr(
        yolov8_detection_training,
        "run_yolov8_detection_training_core",
        pause_core,
    )

    with pytest.raises(YoloDetectionTrainingPausedError) as captured:
        yolov8_detection_training.run_yolov8_detection_training(SimpleNamespace())

    assert captured.value.savepoint.epoch == 2
    assert captured.value.savepoint.latest_checkpoint_bytes == b"latest"
    assert captured.value.savepoint.best_checkpoint_bytes == b"best"


def test_yolov8_terminate_error_is_translated_to_platform_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 YOLOv8 terminate 同样使用平台统一异常类型。"""

    def terminate_core(_request: object) -> object:
        raise YoloV8DetectionTrainingTerminatedError()

    monkeypatch.setattr(
        yolov8_detection_training,
        "run_yolov8_detection_training_core",
        terminate_core,
    )

    with pytest.raises(YoloDetectionTrainingTerminatedError):
        yolov8_detection_training.run_yolov8_detection_training(SimpleNamespace())
