"""YOLO task 训练进度回写 helper 测试。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.service.application.models.training.yolo_task_training_progress import (
    build_yolo_task_epoch_progress_event,
    build_yolo_task_train_metrics_payload,
)


@dataclass(frozen=True)
class _Progress:
    """测试用 epoch progress。"""

    epoch: int
    max_epochs: int
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]


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
    assert payload["epoch_history"] == [{"epoch": 1, "loss": 0.25, "box_loss": 0.1}]


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
