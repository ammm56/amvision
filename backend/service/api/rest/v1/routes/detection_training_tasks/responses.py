"""detection 训练任务 API 响应组装。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.detection_training_route_models import (
    DetectionTrainingTaskActionName,
    DetectionTrainingTaskControlStatusResponse,
    DetectionTrainingTaskDetailResponse,
    DetectionTrainingTaskEventResponse,
    DetectionTrainingTaskSummaryResponse,
    build_detection_training_task_available_actions,
    build_detection_training_task_control_status,
    build_detection_training_task_detail_response,
    build_detection_training_task_event_response,
    build_detection_training_task_summary_response,
)

from .services import _resolve_detection_training_model_type_from_task


def _build_detection_training_task_summary_response(
    task: object,
) -> DetectionTrainingTaskSummaryResponse:
    """把 detection 训练 TaskRecord 转成摘要响应。"""

    return build_detection_training_task_summary_response(
        task,
        model_type=_resolve_detection_training_model_type_from_task(task),
    )


def _build_detection_training_task_control_status(
    task: object,
) -> DetectionTrainingTaskControlStatusResponse:
    """把训练控制元数据归一成 detection 正式控制状态响应。"""

    return build_detection_training_task_control_status(task)


def _build_detection_training_task_available_actions(
    task: object,
) -> list[DetectionTrainingTaskActionName]:
    """根据当前任务状态构建 detection 建议展示的控制动作列表。"""

    return build_detection_training_task_available_actions(task)


def _build_detection_training_task_event_response(
    event: object,
) -> DetectionTrainingTaskEventResponse:
    """把训练任务事件转换为 detection 事件响应。"""

    return build_detection_training_task_event_response(event)


def _build_detection_training_task_detail_response(
    task: object,
    events: tuple[object, ...],
) -> DetectionTrainingTaskDetailResponse:
    """把 detection 训练任务和事件转换为详情响应。"""

    return build_detection_training_task_detail_response(
        task,
        events,
        model_type=_resolve_detection_training_model_type_from_task(task),
    )

