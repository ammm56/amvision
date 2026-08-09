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
from backend.service.application.models.training.detection_training_rules import (
    DetectionTrainingOutputFiles,
)
from backend.service.application.models.training.yolo_detection_task_summary import (
    build_yolo_detection_resolved_extra_options_payload,
    build_yolo_detection_training_summary,
)
from backend.service.application.models.training.yolo_detection_training_execution import (
    YoloDetectionTrainingExecutionResult,
)
from backend.service.domain.datasets.dataset_export import DatasetExport
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
            (
                "l1_loss_weight"
                if training_module is yolo26_detection_training
                else "dfl_loss_weight"
            ): 1.5,
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
            cosine_schedule=False,
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
    assert metrics_payload["evaluation"]["max_detections"] == 300
    assert metrics_payload["scheduler"]["name"] == "UltralyticsLinearLambdaLR"
    expected_regression_weight_name = (
        "l1_loss_weight"
        if training_module is yolo26_detection_training
        else "dfl_loss_weight"
    )
    assert metrics_payload["loss_weights"][expected_regression_weight_name] == 1.5


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


def test_yolo_detection_summary_keeps_validation_provenance() -> None:
    """训练 summary 的 validation 区块必须包含 best、轮次和报告路径。"""

    output_files = DetectionTrainingOutputFiles(
        output_object_prefix="task-runs/training/task-1",
        checkpoint_object_key="task-runs/training/task-1/best.pt",
        validation_metrics_object_key="task-runs/training/task-1/validation.json",
    )
    execution_result = YoloDetectionTrainingExecutionResult(
        checkpoint_bytes=b"best",
        latest_checkpoint_bytes=b"latest",
        metrics_payload={},
        validation_metrics_payload={
            "final_metrics": {"map50": 0.99, "map50_95": 0.95},
            "evaluated_epochs": [5, 10],
        },
        warm_start_summary={"enabled": True},
        implementation_mode="yolov8-detection-core",
        best_metric_name="map50_95",
        best_metric_value=0.95,
        evaluation_interval=5,
        category_names=("part",),
        split_names=("train", "val"),
        sample_count=10,
        train_sample_count=8,
        input_size=(640, 640),
        batch_size=4,
        max_epochs=10,
        device="cpu",
        gpu_count=0,
        device_ids=(),
        distributed_mode="single-process",
        precision="fp32",
        validation_split_name="val",
        validation_sample_count=2,
        parameter_count=100,
    )
    request = SimpleNamespace(
        recipe_id="default",
        model_scale="m",
        output_model_name="model",
        warm_start_model_version_id="pretrained",
        evaluation_interval=5,
        max_epochs=10,
        batch_size=4,
        gpu_count=0,
        precision="fp32",
        input_size=(640, 640),
        extra_options={},
    )
    dataset_export = DatasetExport(
        dataset_export_id="export-1",
        dataset_id="dataset-1",
        project_id="project-1",
        dataset_version_id="version-1",
        format_id="coco-detection-v1",
        task_type="detection",
        manifest_object_key="datasets/export-1/manifest.json",
    )

    summary = build_yolo_detection_training_summary(
        task_id="task-1",
        request=request,
        dataset_export=dataset_export,
        execution_result=execution_result,
        output_files=output_files,
    )

    assert summary["validation"] == {
        "enabled": True,
        "split_name": "val",
        "sample_count": 2,
        "evaluation_interval": 5,
        "best_metric_name": "map50_95",
        "best_metric_value": 0.95,
        "final_metrics": {"map50": 0.99, "map50_95": 0.95},
        "evaluated_epochs": [5, 10],
        "metrics_object_key": "task-runs/training/task-1/validation.json",
    }


def test_yolo26_summary_uses_l1_weight_name_without_fake_dfl_field() -> None:
    """YOLO26 摘要应保留公开 L1 语义，不能重新写回 DFL 名称。"""

    payload = build_yolo_detection_resolved_extra_options_payload(
        metrics_payload={
            "loss_weights": {
                "class_loss_weight": 0.5,
                "box_loss_weight": 7.5,
                "l1_loss_weight": 1.5,
            }
        }
    )

    assert payload["l1_loss_weight"] == 1.5
    assert "dfl_loss_weight" not in payload
