"""detection inference 路由响应模型与辅助函数。"""

from __future__ import annotations

from fastapi import Request

from backend.service.api.rest.v1.routes.yolox_inference_tasks import (
    YoloXInferenceInputSource,
    YoloXInferencePayloadResponse,
    YoloXInferenceTaskDetailResponse,
    YoloXInferenceTaskResultResponse,
    YoloXInferenceTaskSubmissionResponse,
    YoloXInferenceTaskSummaryResponse,
    _build_inference_task_detail_response,
    _build_inference_task_summary_response,
    _ensure_visible_deployment,
    _matches_inference_filters,
    _read_async_inference_service_id,
    _read_yolox_inference_request_payload,
    _require_running_deployment_process,
    _resolve_http_request_id,
    _resolve_requested_score_threshold,
)


class DetectionInferenceTaskSubmissionResponse(YoloXInferenceTaskSubmissionResponse):
    """描述 detection 推理任务创建响应。"""


class DetectionInferencePayloadResponse(YoloXInferencePayloadResponse):
    """描述 detection 同步直返与异步结果共用的推理结果载荷。"""


class DetectionInferenceTaskSummaryResponse(YoloXInferenceTaskSummaryResponse):
    """描述 detection 推理任务摘要响应。"""


class DetectionInferenceTaskDetailResponse(YoloXInferenceTaskDetailResponse):
    """描述 detection 推理任务详情响应。"""


class DetectionInferenceTaskResultResponse(YoloXInferenceTaskResultResponse):
    """描述 detection 推理结果读取响应。"""


def _build_detection_inference_task_summary_response(
    task: object,
) -> DetectionInferenceTaskSummaryResponse:
    """把推理任务记录转换为 detection 摘要响应。"""

    response = _build_inference_task_summary_response(task)
    return DetectionInferenceTaskSummaryResponse.model_validate(response.model_dump())


def _build_detection_inference_task_detail_response(
    task: object,
    events: tuple[object, ...],
) -> DetectionInferenceTaskDetailResponse:
    """把推理任务与事件转换为 detection 详情响应。"""

    response = _build_inference_task_detail_response(task, events)
    return DetectionInferenceTaskDetailResponse.model_validate(response.model_dump())


def _ensure_visible_detection_deployment(
    *,
    principal,
    deployment_project_id: str,
    deployment_instance_id: str,
) -> None:
    """校验当前主体是否可以访问指定 detection DeploymentInstance。"""

    _ensure_visible_deployment(
        principal=principal,
        deployment_project_id=deployment_project_id,
        deployment_instance_id=deployment_instance_id,
    )


def _matches_detection_inference_filters(
    *,
    task: object,
    deployment_instance_id: str | None,
) -> bool:
    """判断 detection 推理任务是否满足额外筛选条件。"""

    return _matches_inference_filters(
        task=task,
        deployment_instance_id=deployment_instance_id,
    )


def _require_running_detection_deployment_process(
    *,
    deployment_process_supervisor,
    process_config,
    runtime_mode: str,
) -> None:
    """校验目标 detection deployment 子进程已经处于 running 状态。"""

    _require_running_deployment_process(
        deployment_process_supervisor=deployment_process_supervisor,
        process_config=process_config,
        runtime_mode=runtime_mode,
    )


async def _read_detection_inference_request_payload(
    request: Request,
) -> tuple[dict[str, object], YoloXInferenceInputSource]:
    """按 content-type 读取 detection 推理请求，并保留 one-of 输入源信息。"""

    return await _read_yolox_inference_request_payload(request)


def _resolve_detection_http_request_id(request: Request, *, prefix: str) -> str:
    """解析一个稳定的 detection HTTP 请求 id。"""

    return _resolve_http_request_id(request, prefix=prefix)


def _read_detection_async_inference_service_id(request: Request) -> str | None:
    """读取当前 detection async inference service 稳定 id。"""

    return _read_async_inference_service_id(request)


def _resolve_detection_requested_score_threshold(value: float | None) -> float:
    """解析 detection 推理阈值；未提供时回落到默认值。"""

    return _resolve_requested_score_threshold(value)

