"""YOLO 主线 classification 训练任务事件工具。"""

from __future__ import annotations

from backend.service.application.tasks.task_service import AppendTaskEventRequest
from backend.service.domain.models.model_task_types import CLASSIFICATION_TASK_TYPE


def build_yolo_task_classification_training_queue_failed_event(
    *,
    task_id: str,
    error_message: str,
    finished_at: str,
    dataset_export_id: str,
    dataset_export_manifest_key: str | None,
) -> AppendTaskEventRequest:
    """构建 classification 训练入队失败事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="classification training queue submission failed",
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


def build_yolo_task_classification_training_queued_event(
    *,
    task_id: str,
    queue_name: str,
    queue_task_id: str,
) -> AppendTaskEventRequest:
    """构建 classification 训练已入队事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="classification training queued",
        payload={
            "state": "queued",
            "metadata": {
                "queue_name": queue_name,
                "queue_task_id": queue_task_id,
            },
        },
    )


def build_yolo_task_classification_training_started_event(
    *,
    task_id: str,
    started_at: str,
    model_type: str,
) -> AppendTaskEventRequest:
    """构建 classification 训练开始事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="classification training started",
        payload={
            "state": "running",
            "started_at": started_at,
            "progress": {
                "stage": "running",
                "task_type": CLASSIFICATION_TASK_TYPE,
                "model_type": model_type,
            },
        },
    )


def build_yolo_task_classification_training_cancelled_event(
    *,
    task_id: str,
    finished_at: str,
    result: dict[str, object],
    control_metadata_key: str,
) -> AppendTaskEventRequest:
    """构建 classification 训练取消事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="classification training cancelled",
        payload={
            "state": "cancelled",
            "finished_at": finished_at,
            "progress": {"stage": "cancelled"},
            "metadata": {control_metadata_key: {}},
            "result": result,
        },
    )


def build_yolo_task_classification_training_paused_event(
    *,
    task_id: str,
    result: dict[str, object],
    control_metadata_key: str,
) -> AppendTaskEventRequest:
    """构建 classification 训练暂停事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="classification training paused",
        payload={
            "state": "paused",
            "progress": {"stage": "paused"},
            "metadata": {control_metadata_key: {}},
            "result": result,
        },
    )


def build_yolo_task_classification_training_failed_event(
    *,
    task_id: str,
    finished_at: str,
    error_message: str,
    result: dict[str, object],
) -> AppendTaskEventRequest:
    """构建 classification 训练失败事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="classification training failed",
        payload={
            "state": "failed",
            "finished_at": finished_at,
            "error_message": error_message,
            "progress": {"stage": "failed"},
            "result": result,
        },
    )


def build_yolo_task_classification_training_succeeded_event(
    *,
    task_id: str,
    finished_at: str,
    result: dict[str, object],
    control_metadata_key: str,
) -> AppendTaskEventRequest:
    """构建 classification 训练成功事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="result",
        message="classification training succeeded",
        payload={
            "state": "succeeded",
            "finished_at": finished_at,
            "progress": {"stage": "succeeded", "percent": 100.0},
            "metadata": {control_metadata_key: {}},
            "result": result,
        },
    )
