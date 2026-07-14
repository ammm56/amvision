"""YOLO26 pose 训练任务事件工具。"""

from __future__ import annotations

from backend.service.application.task_failure_payloads import build_task_failure_payload_from_message
from backend.service.application.models.training.yolo26_pose_task_control import (
    YOLO26_POSE_TRAINING_CONTROL_METADATA_KEY,
)
from backend.service.application.tasks.task_service import AppendTaskEventRequest
from backend.service.domain.models.model_task_types import POSE_TASK_TYPE


def build_yolo26_pose_training_queue_failed_event(
    *,
    task_id: str,
    error_message: str,
    finished_at: str,
    dataset_export_id: str,
    dataset_export_manifest_key: str | None,
    error: BaseException | None = None,
) -> AppendTaskEventRequest:
    """构建 YOLO26 pose 训练入队失败事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="YOLO26 pose training queue submission failed",
        payload=build_task_failure_payload_from_message(
            error_message=error_message,
            error=error,
            finished_at=finished_at,
            progress={"stage": "failed"},
            result={
                "dataset_export_id": dataset_export_id,
                "dataset_export_manifest_key": dataset_export_manifest_key,
            },
        ),
    )


def build_yolo26_pose_training_queued_event(
    *,
    task_id: str,
    queue_name: str,
    queue_task_id: str,
) -> AppendTaskEventRequest:
    """构建 YOLO26 pose 训练已入队事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="YOLO26 pose training queued",
        payload={
            "state": "queued",
            "metadata": {
                "queue_name": queue_name,
                "queue_task_id": queue_task_id,
            },
        },
    )


def build_yolo26_pose_training_started_event(
    *,
    task_id: str,
    started_at: str,
    model_type: str,
) -> AppendTaskEventRequest:
    """构建 YOLO26 pose 训练开始事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="YOLO26 pose training started",
        payload={
            "state": "running",
            "started_at": started_at,
            "progress": {
                "stage": "running",
                "task_type": POSE_TASK_TYPE,
                "model_type": model_type,
            },
        },
    )


def build_yolo26_pose_training_cancelled_event(
    *,
    task_id: str,
    finished_at: str,
    result: dict[str, object],
) -> AppendTaskEventRequest:
    """构建 YOLO26 pose 训练取消事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="YOLO26 pose training cancelled",
        payload={
            "state": "cancelled",
            "finished_at": finished_at,
            "progress": {"stage": "cancelled"},
            "metadata": {YOLO26_POSE_TRAINING_CONTROL_METADATA_KEY: {}},
            "result": result,
        },
    )


def build_yolo26_pose_training_paused_event(
    *,
    task_id: str,
    result: dict[str, object],
) -> AppendTaskEventRequest:
    """构建 YOLO26 pose 训练暂停事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="YOLO26 pose training paused",
        payload={
            "state": "paused",
            "progress": {"stage": "paused"},
            "metadata": {YOLO26_POSE_TRAINING_CONTROL_METADATA_KEY: {}},
            "result": result,
        },
    )


def build_yolo26_pose_training_failed_event(
    *,
    task_id: str,
    finished_at: str,
    error_message: str,
    result: dict[str, object],
    error: BaseException | None = None,
) -> AppendTaskEventRequest:
    """构建 YOLO26 pose 训练失败事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="YOLO26 pose training failed",
        payload=build_task_failure_payload_from_message(
            error_message=error_message,
            error=error,
            finished_at=finished_at,
            progress={"stage": "failed"},
            result=result,
        ),
    )


def build_yolo26_pose_training_succeeded_event(
    *,
    task_id: str,
    finished_at: str,
    result: dict[str, object],
) -> AppendTaskEventRequest:
    """构建 YOLO26 pose 训练成功事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="result",
        message="YOLO26 pose training succeeded",
        payload={
            "state": "succeeded",
            "finished_at": finished_at,
            "progress": {"stage": "succeeded", "percent": 100.0},
            "metadata": {YOLO26_POSE_TRAINING_CONTROL_METADATA_KEY: {}},
            "result": result,
        },
    )


__all__ = [
    "build_yolo26_pose_training_cancelled_event",
    "build_yolo26_pose_training_failed_event",
    "build_yolo26_pose_training_paused_event",
    "build_yolo26_pose_training_queue_failed_event",
    "build_yolo26_pose_training_queued_event",
    "build_yolo26_pose_training_started_event",
    "build_yolo26_pose_training_succeeded_event",
]





