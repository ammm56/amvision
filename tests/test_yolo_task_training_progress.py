"""YOLO task 训练进度回写 helper 测试。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.service.application.models.training.yolo_task_training_progress import (
    build_yolo_task_epoch_progress_event,
    build_yolo_task_train_metrics_payload,
    build_yolo_task_validation_metrics_payload,
)


@dataclass(frozen=True)
class _Progress:
    """测试用 epoch progress。"""

    epoch: int
    max_epochs: int
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float] | None = None
    best_metric_value: float | None = None
    best_metric_name: str | None = None


def test_yolo_task_train_metrics_payload_records_running_epoch_metrics() -> None:
    """验证运行中 train-metrics.json payload 包含 task、epoch 和训练指标。"""

    progress = _Progress(
        epoch=1,
        max_epochs=4,
        input_size=(640, 640),
        learning_rate=0.001,
        train_metrics={"loss": 0.25, "box_loss": 0.1},
    )

    payload = build_yolo_task_train_metrics_payload(
        progress=progress,
        task_type="pose",
        model_type="yolo11",
        implementation_mode="yolo11-pose-core",
    )

    assert payload["task_type"] == "pose"
    assert payload["model_type"] == "yolo11"
    assert payload["epoch"] == 2
    assert payload["epoch_index"] == 1
    assert payload["final_metrics"] == {"loss": 0.25, "box_loss": 0.1}
    assert payload["epoch_history"] == [
        {"epoch": 2, "epoch_index": 1, "loss": 0.25, "box_loss": 0.1}
    ]


def test_yolo_task_metrics_payload_merges_resume_history_by_epoch() -> None:
    """验证运行中指标保留完整历史，并在 resume 重跑同一轮时覆盖旧值。"""

    progress = _Progress(
        epoch=1,
        max_epochs=4,
        input_size=(640, 640),
        learning_rate=0.001,
        train_metrics={"loss": 0.25},
        validation_metrics={"map50": 0.7},
    )
    previous = {
        "epoch_history": [
            {"epoch": 1, "epoch_index": 0, "loss": 0.8},
            {"epoch": 2, "epoch_index": 1, "loss": 0.5},
            {"bad": "ignored"},
        ]
    }

    train_payload = build_yolo_task_train_metrics_payload(
        progress=progress,
        task_type="pose",
        model_type="yolov8",
        implementation_mode="yolov8-pose-core",
        previous_payload=previous,
    )
    validation_payload = build_yolo_task_validation_metrics_payload(
        progress=progress,
        validation_metrics={"map50": 0.7},
        task_type="pose",
        model_type="yolov8",
        implementation_mode="yolov8-pose-core",
        previous_payload={
            "epoch_history": [
                {"epoch": 1, "epoch_index": 0, "map50": 0.2},
            ]
        },
    )

    assert train_payload["epoch_history"] == [
        {"epoch": 1, "epoch_index": 0, "loss": 0.8},
        {"epoch": 2, "epoch_index": 1, "loss": 0.25},
    ]
    assert validation_payload["epoch_history"] == [
        {"epoch": 1, "epoch_index": 0, "map50": 0.2},
        {"epoch": 2, "epoch_index": 1, "map50": 0.7},
    ]


def test_yolo_task_epoch_progress_event_updates_task_progress_and_result_keys() -> None:
    """验证 progress 事件包含页面需要展示的 epoch、percent 和输出文件 key。"""

    progress = _Progress(
        epoch=0,
        max_epochs=2,
        input_size=(320, 320),
        learning_rate=0.002,
        train_metrics={"loss": 0.5},
    )

    event = build_yolo_task_epoch_progress_event(
        task_id="task-1",
        model_label="YOLO26 OBB",
        task_type="obb",
        model_type="yolo26",
        attempt_no=1,
        output_prefix="task-runs/task-1",
        train_metrics_object_key="task-runs/task-1/output-files/train-metrics.json",
        progress=progress,
    )

    assert event.event_type == "progress"
    assert event.message == "YOLO26 OBB epoch 1/2"
    assert event.payload["state"] == "running"
    assert event.payload["progress"]["percent"] == 50.0
    assert event.payload["progress"]["train_metrics"] == {"loss": 0.5}
    assert event.payload["result"]["metrics_object_key"] == (
        "task-runs/task-1/output-files/train-metrics.json"
    )


def test_yolo_task_epoch_progress_publishes_validation_and_valid_best_metric() -> None:
    """验证结束后的 progress 必须同步公开 validation 与有限 best 指标。"""

    progress = _Progress(
        epoch=4,
        max_epochs=20,
        input_size=(640, 640),
        learning_rate=0.001,
        train_metrics={"loss": 0.5},
        validation_metrics={"map50": 0.8, "map50_95": 0.6},
        best_metric_value=0.6,
        best_metric_name="val_map50_95",
    )
    validation_key = "task-runs/task-1/output-files/validation-metrics.json"

    event = build_yolo_task_epoch_progress_event(
        task_id="task-1",
        model_label="YOLOv8 segmentation",
        task_type="segmentation",
        model_type="yolov8",
        attempt_no=1,
        output_prefix="task-runs/task-1",
        train_metrics_object_key="task-runs/task-1/output-files/train-metrics.json",
        validation_metrics_object_key=validation_key,
        progress=progress,
    )
    validation_payload = build_yolo_task_validation_metrics_payload(
        progress=progress,
        validation_metrics=dict(progress.validation_metrics or {}),
        task_type="segmentation",
        model_type="yolov8",
        implementation_mode="yolov8-segmentation-core",
    )

    assert event.payload["progress"]["validation_metrics"] == {
        "map50": 0.8,
        "map50_95": 0.6,
    }
    assert event.payload["progress"]["best_metric_value"] == 0.6
    assert event.payload["progress"]["best_metric_name"] == "val_map50_95"
    assert event.payload["result"]["validation_metrics_object_key"] == validation_key
    assert validation_payload["final_metrics"]["map50_95"] == 0.6
    assert validation_payload["epoch_history"] == [
        {
            "epoch": 5,
            "epoch_index": 4,
            "map50": 0.8,
            "map50_95": 0.6,
        }
    ]


def test_yolo_task_epoch_progress_never_publishes_invalid_best_metric() -> None:
    """内部 -1 sentinel 不得进入 progress。"""

    event = build_yolo_task_epoch_progress_event(
        task_id="task-1",
        model_label="YOLOv8 segmentation",
        task_type="segmentation",
        model_type="yolov8",
        attempt_no=1,
        output_prefix="task-runs/task-1",
        train_metrics_object_key="task-runs/task-1/output-files/train-metrics.json",
        progress=_Progress(
            epoch=0,
            max_epochs=5,
            input_size=(640, 640),
            learning_rate=0.001,
            train_metrics={"loss": 1.0},
            best_metric_value=-1.0,
            best_metric_name="val_map50_95",
        ),
    )

    assert "best_metric_value" not in event.payload["progress"]
    assert "best_metric_name" not in event.payload["progress"]
