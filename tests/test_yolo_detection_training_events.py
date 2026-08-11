"""YOLO detection 训练事件语义回归测试。"""

from backend.service.application.models.training.detection_training_rules import (
    DetectionTrainingOutputFiles,
)
from backend.service.application.models.training.yolo_detection_task_events import (
    build_yolo_detection_training_epoch_progress_event,
    build_yolo_detection_training_paused_event,
)
from backend.service.application.models.training.yolo_detection_training_control import (
    YoloDetectionTrainingEpochProgress,
)


def test_paused_event_preserves_actual_training_percent() -> None:
    """暂停只改变阶段，不得把未完成的训练伪装成 100%。"""

    event = build_yolo_detection_training_paused_event(
        task_id="task-1",
        model_type="yolov8",
        finished_at="2026-08-09T00:00:00+00:00",
        progress={"stage": "training", "percent": 42.5, "epoch": 85},
        control_metadata_key="training_control",
        control={},
        result={"status": "paused"},
    )

    assert event.payload["state"] == "paused"
    assert event.payload["progress"] == {
        "stage": "paused",
        "batch_metrics": {},
        "percent": 42.5,
        "epoch": 85,
    }


def test_non_validation_epoch_preserves_latest_validation_snapshot() -> None:
    """非验证轮次的 patch 不能清空任务中已有的最近验证指标。"""

    event = build_yolo_detection_training_epoch_progress_event(
        task_id="task-1",
        model_type="yolo11",
        attempt_no=1,
        progress=YoloDetectionTrainingEpochProgress(
            epoch=6,
            max_epochs=10,
            evaluation_interval=5,
            validation_ran=False,
            evaluated_epochs=(5,),
            train_metrics={"loss": 1.5},
            validation_metrics={},
            train_metrics_snapshot={},
            validation_snapshot=None,
            current_metric_name="val_map50_95",
            current_metric_value=None,
            best_metric_name="val_map50_95",
            best_metric_value=0.9,
        ),
        percent=60.0,
        output_files=DetectionTrainingOutputFiles(
            output_object_prefix="task-runs/task-1",
            checkpoint_object_key="task-runs/task-1/best.pt",
        ),
        requested_precision="fp32",
        requested_gpu_count=1,
        requested_evaluation_interval=5,
        control_metadata_key="training_control",
        control={},
    )

    progress_payload = event.payload["progress"]
    assert "validation_metrics" not in progress_payload
    assert "current_metric_name" not in progress_payload
    assert "current_metric_value" not in progress_payload
