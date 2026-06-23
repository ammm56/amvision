"""YOLO 主线 OBB 训练任务事件工具。"""

from __future__ import annotations

from backend.service.application.tasks.task_service import AppendTaskEventRequest
from backend.service.domain.models.model_task_types import OBB_TASK_TYPE


def build_yolov8_obb_training_started_event(
    *,
    task_id: str,
    started_at: str,
    model_type: str,
) -> AppendTaskEventRequest:
    """构建 OBB 训练开始事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="obb training started",
        payload={
            "state": "running",
            "started_at": started_at,
            "progress": {
                "stage": "running",
                "task_type": OBB_TASK_TYPE,
                "model_type": model_type,
            },
        },
    )


def build_yolov8_obb_training_cancelled_event(
    *,
    task_id: str,
    finished_at: str,
    result: dict[str, object],
    control_metadata_key: str,
) -> AppendTaskEventRequest:
    """构建 OBB 训练取消事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="obb training cancelled",
        payload={
            "state": "cancelled",
            "finished_at": finished_at,
            "progress": {"stage": "cancelled"},
            "metadata": {control_metadata_key: {}},
            "result": result,
        },
    )


def build_yolov8_obb_training_paused_event(
    *,
    task_id: str,
    result: dict[str, object],
    control_metadata_key: str,
) -> AppendTaskEventRequest:
    """构建 OBB 训练暂停事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="obb training paused",
        payload={
            "state": "paused",
            "progress": {"stage": "paused"},
            "metadata": {control_metadata_key: {}},
            "result": result,
        },
    )


def build_yolov8_obb_training_failed_event(
    *,
    task_id: str,
    finished_at: str,
    error_message: str,
    result: dict[str, object],
) -> AppendTaskEventRequest:
    """构建 OBB 训练失败事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="status",
        message="obb training failed",
        payload={
            "state": "failed",
            "finished_at": finished_at,
            "error_message": error_message,
            "progress": {"stage": "failed"},
            "result": result,
        },
    )


def build_yolov8_obb_training_succeeded_event(
    *,
    task_id: str,
    finished_at: str,
    result: dict[str, object],
    control_metadata_key: str,
) -> AppendTaskEventRequest:
    """构建 OBB 训练成功事件。"""

    return AppendTaskEventRequest(
        task_id=task_id,
        event_type="result",
        message="obb training succeeded",
        payload={
            "state": "succeeded",
            "finished_at": finished_at,
            "progress": {"stage": "succeeded", "percent": 100.0},
            "metadata": {control_metadata_key: {}},
            "result": result,
        },
    )

