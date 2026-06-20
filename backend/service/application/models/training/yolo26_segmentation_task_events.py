"""YOLO26 segmentation 训练任务事件工具。"""

from __future__ import annotations

from backend.service.application.models.training.yolo26_segmentation_task_control import (
    YOLO26_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY,
)
from backend.service.application.tasks.task_service import AppendTaskEventRequest
from backend.service.domain.models.model_task_types import SEGMENTATION_TASK_TYPE


def build_yolo26_segmentation_training_queue_failed_event(
    *,
    task_id: str,
    error_message: str,
    finished_at: str,
    dataset_export_id: str,
    dataset_export_manifest_key: str | None,
) -> AppendTaskEventRequest:
    """构建 YOLO26 segmentation 训练入队失败事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="YOLO26 segmentation training queue submission failed",
        payload={
            "state": "failed",
            "error_message": error_message,
            "progress": {"stage": "failed"},
            "finished_at": finished_at,
            "result": {
                "dataset_export_id": dataset_export_id,
                "dataset_export_manifest_key": dataset_export_manifest_key,
            },
        },
    )


def build_yolo26_segmentation_training_queued_event(
    *,
    task_id: str,
    queue_name: str,
    queue_task_id: str,
) -> AppendTaskEventRequest:
    """构建 YOLO26 segmentation 训练已入队事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="YOLO26 segmentation training queued",
        payload={
            "state": "queued",
            "metadata": {
                "queue_name": queue_name,
                "queue_task_id": queue_task_id,
            },
        },
    )


def build_yolo26_segmentation_training_started_event(
    *,
    task_id: str,
    started_at: str,
    model_type: str,
) -> AppendTaskEventRequest:
    """构建 YOLO26 segmentation 训练开始事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="YOLO26 segmentation training started",
        payload={
            "state": "running",
            "started_at": started_at,
            "progress": {
                "stage": "running",
                "task_type": SEGMENTATION_TASK_TYPE,
                "model_type": model_type,
            },
        },
    )


def build_yolo26_segmentation_training_cancelled_event(
    *,
    task_id: str,
    finished_at: str,
    result: dict[str, object],
) -> AppendTaskEventRequest:
    """构建 YOLO26 segmentation 训练取消事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="YOLO26 segmentation training cancelled",
        payload={
            "state": "cancelled",
            "finished_at": finished_at,
            "progress": {"stage": "cancelled"},
            "metadata": {YOLO26_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY: {}},
            "result": result,
        },
    )


def build_yolo26_segmentation_training_paused_event(
    *,
    task_id: str,
    result: dict[str, object],
) -> AppendTaskEventRequest:
    """构建 YOLO26 segmentation 训练暂停事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="YOLO26 segmentation training paused",
        payload={
            "state": "paused",
            "progress": {"stage": "paused"},
            "metadata": {YOLO26_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY: {}},
            "result": result,
        },
    )


def build_yolo26_segmentation_training_failed_event(
    *,
    task_id: str,
    finished_at: str,
    error_message: str,
    result: dict[str, object],
) -> AppendTaskEventRequest:
    """构建 YOLO26 segmentation 训练失败事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="YOLO26 segmentation training failed",
        payload={
            "state": "failed",
            "finished_at": finished_at,
            "error_message": error_message,
            "progress": {"stage": "failed"},
            "result": result,
        },
    )


def build_yolo26_segmentation_training_succeeded_event(
    *,
    task_id: str,
    finished_at: str,
    result: dict[str, object],
) -> AppendTaskEventRequest:
    """构建 YOLO26 segmentation 训练成功事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="result",
        message="YOLO26 segmentation training succeeded",
        payload={
            "state": "succeeded",
            "finished_at": finished_at,
            "progress": {"stage": "succeeded", "percent": 100.0},
            "metadata": {YOLO26_SEGMENTATION_TRAINING_CONTROL_METADATA_KEY: {}},
            "result": result,
        },
    )


__all__ = [
    "build_yolo26_segmentation_training_cancelled_event",
    "build_yolo26_segmentation_training_failed_event",
    "build_yolo26_segmentation_training_paused_event",
    "build_yolo26_segmentation_training_queue_failed_event",
    "build_yolo26_segmentation_training_queued_event",
    "build_yolo26_segmentation_training_started_event",
    "build_yolo26_segmentation_training_succeeded_event",
]
