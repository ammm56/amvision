"""YOLOX evaluation task REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.yolox_output_files import (
    YoloXEvaluationOutputFileSummaryResponse,
    YoloXEvaluationReportResponse,
    _YOLOX_EVALUATION_OUTPUT_FILE_ORDER,
    _build_yolox_evaluation_output_file_summary_response,
    _read_yolox_evaluation_report,
)
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError
from backend.service.application.models.yolox_evaluation_task_service import (
    YOLOX_EVALUATION_TASK_KIND,
    SqlAlchemyYoloXEvaluationTaskService,
    YoloXEvaluationTaskRequest,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


yolox_evaluation_tasks_router = APIRouter(prefix="/models", tags=["models"])


class YoloXEvaluationTaskCreateRequestBody(BaseModel):
    """描述 YOLOX 数据集级评估任务创建请求体。

    字段：
    - project_id：所属 Project id。
    - model_version_id：待评估 ModelVersion id。
    - dataset_export_id：评估输入使用的 DatasetExport id。
    - dataset_export_manifest_key：评估输入使用的导出 manifest object key。
    - score_threshold：评估 score threshold。
    - nms_threshold：评估 NMS threshold。
    - save_result_package：是否输出结果包。
    - extra_options：附加评估选项。
    - display_name：可选的任务展示名称。
    """

    project_id: str = Field(description="所属 Project id")
    model_version_id: str = Field(description="待评估 ModelVersion id")
    dataset_export_id: str | None = Field(default=None, description="评估输入使用的 DatasetExport id")
    dataset_export_manifest_key: str | None = Field(default=None, description="评估输入使用的导出 manifest object key")
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="评估 score threshold")
    nms_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="评估 NMS threshold")
    save_result_package: bool = Field(default=True, description="是否输出结果包")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加评估选项")
    display_name: str = Field(default="", description="可选的任务展示名称")


class YoloXEvaluationTaskSubmissionResponse(BaseModel):
    """描述 YOLOX 评估任务创建响应。

    字段：
    - task_id：评估任务 id。
    - status：评估任务当前状态。
    - queue_name：提交到的队列名称。
    - queue_task_id：队列任务 id。
    - dataset_export_id：解析后的 DatasetExport id。
    - dataset_export_manifest_key：解析后的导出 manifest object key。
    - dataset_version_id：导出来源的 DatasetVersion id。
    - format_id：评估使用的数据集导出格式 id。
    - model_version_id：待评估 ModelVersion id。
    """

    task_id: str = Field(description="评估任务 id")
    status: str = Field(description="评估任务当前状态")
    queue_name: str = Field(description="提交到的队列名称")
    queue_task_id: str = Field(description="队列任务 id")
    dataset_export_id: str = Field(description="解析后的 DatasetExport id")
    dataset_export_manifest_key: str = Field(description="解析后的导出 manifest object key")
    dataset_version_id: str = Field(description="导出来源的 DatasetVersion id")
    format_id: str = Field(description="评估使用的数据集导出格式 id")
    model_version_id: str = Field(description="待评估 ModelVersion id")


class YoloXEvaluationTaskSummaryResponse(BaseModel):
    """描述 YOLOX 评估任务摘要响应。

    字段：
    - task_id：评估任务 id。
    - display_name：展示名称。
    - project_id：所属 Project id。
    - created_by：提交主体 id。
    - created_at：创建时间。
    - worker_pool：worker pool 名称。
    - state：当前状态。
    - current_attempt_no：当前尝试序号。
    - started_at：开始时间。
    - finished_at：结束时间。
    - progress：进度快照。
    - result：结果快照。
    - error_message：错误消息。
    - metadata：附加元数据。
    - dataset_export_id：评估输入使用的 DatasetExport id。
    - dataset_export_manifest_key：评估输入使用的导出 manifest object key。
    - dataset_version_id：评估输入使用的 DatasetVersion id。
    - format_id：评估输入导出格式 id。
    - model_version_id：待评估 ModelVersion id。
    - score_threshold：评估 score threshold。
    - nms_threshold：评估 NMS threshold。
    - save_result_package：是否输出结果包。
    - output_object_prefix：评估输出目录前缀。
    - report_object_key：评估报告 object key。
    - detections_object_key：检测结果 object key。
    - result_package_object_key：评估结果包 object key。
    - map50：当前评估 map50。
    - map50_95：当前评估 map50_95。
    - report_summary：评估摘要。
    """

    task_id: str = Field(description="评估任务 id")
    display_name: str = Field(description="展示名称")
    project_id: str = Field(description="所属 Project id")
    created_by: str | None = Field(default=None, description="提交主体 id")
    created_at: str = Field(description="创建时间")
    worker_pool: str | None = Field(default=None, description="worker pool 名称")
    state: str = Field(description="当前状态")
    current_attempt_no: int = Field(description="当前尝试序号")
    started_at: str | None = Field(default=None, description="开始时间")
    finished_at: str | None = Field(default=None, description="结束时间")
    progress: dict[str, object] = Field(default_factory=dict, description="进度快照")
    result: dict[str, object] = Field(default_factory=dict, description="结果快照")
    error_message: str | None = Field(default=None, description="错误消息")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")
    dataset_export_id: str | None = Field(default=None, description="评估输入使用的 DatasetExport id")
    dataset_export_manifest_key: str | None = Field(default=None, description="评估输入使用的导出 manifest object key")
    dataset_version_id: str | None = Field(default=None, description="评估输入使用的 DatasetVersion id")
    format_id: str | None = Field(default=None, description="评估输入导出格式 id")
    model_version_id: str = Field(description="待评估 ModelVersion id")
    score_threshold: float | None = Field(default=None, description="评估 score threshold")
    nms_threshold: float | None = Field(default=None, description="评估 NMS threshold")
    save_result_package: bool = Field(description="是否输出结果包")
    output_object_prefix: str | None = Field(default=None, description="评估输出目录前缀")
    report_object_key: str | None = Field(default=None, description="评估报告 object key")
    detections_object_key: str | None = Field(default=None, description="检测结果 object key")
    result_package_object_key: str | None = Field(default=None, description="评估结果包 object key")
    map50: float | None = Field(default=None, description="当前评估 map50")
    map50_95: float | None = Field(default=None, description="当前评估 map50_95")
    report_summary: dict[str, object] = Field(default_factory=dict, description="评估摘要")


class YoloXEvaluationTaskEventResponse(BaseModel):
    """描述 YOLOX 评估任务事件响应。

    字段：
    - event_id：事件 id。
    - task_id：所属任务 id。
    - attempt_id：关联尝试 id。
    - event_type：事件类型。
    - created_at：事件时间。
    - message：事件消息。
    - payload：事件负载。
    """

    event_id: str = Field(description="事件 id")
    task_id: str = Field(description="所属任务 id")
    attempt_id: str | None = Field(default=None, description="关联尝试 id")
    event_type: str = Field(description="事件类型")
    created_at: str = Field(description="事件时间")
    message: str = Field(description="事件消息")
    payload: dict[str, object] = Field(default_factory=dict, description="事件负载")


class YoloXEvaluationTaskDetailResponse(YoloXEvaluationTaskSummaryResponse):
    """描述 YOLOX 评估任务详情响应。

    字段：
    - task_spec：任务规格。
    - events：任务事件列表。
    """

    task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
    events: list[YoloXEvaluationTaskEventResponse] = Field(default_factory=list, description="任务事件列表")


@yolox_evaluation_tasks_router.post(
    "/yolox/evaluation-tasks",
    response_model=YoloXEvaluationTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_yolox_evaluation_task(
    body: YoloXEvaluationTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read", "models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> YoloXEvaluationTaskSubmissionResponse:
    """创建一个用于数据集级回归验证的 YOLOX evaluation task。"""

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": body.project_id},
        )
    service = SqlAlchemyYoloXEvaluationTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    submission = service.submit_evaluation_task(
        YoloXEvaluationTaskRequest(
            project_id=body.project_id,
            model_version_id=body.model_version_id,
            dataset_export_id=body.dataset_export_id,
            dataset_export_manifest_key=body.dataset_export_manifest_key,
            score_threshold=body.score_threshold,
            nms_threshold=body.nms_threshold,
            save_result_package=body.save_result_package,
            extra_options=dict(body.extra_options),
        ),
        created_by=principal.principal_id,
        display_name=body.display_name,
    )
    return YoloXEvaluationTaskSubmissionResponse(
        task_id=submission.task_id,
        status=submission.status,
        queue_name=submission.queue_name,
        queue_task_id=submission.queue_task_id,
        dataset_export_id=submission.dataset_export_id,
        dataset_export_manifest_key=submission.dataset_export_manifest_key,
        dataset_version_id=submission.dataset_version_id,
        format_id=submission.format_id,
        model_version_id=submission.model_version_id,
    )


@yolox_evaluation_tasks_router.get(
    "/yolox/evaluation-tasks",
    response_model=list[YoloXEvaluationTaskSummaryResponse],
)
def list_yolox_evaluation_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
    state: Annotated[str | None, Query(description="任务状态")] = None,
    created_by: Annotated[str | None, Query(description="提交主体 id")] = None,
    dataset_export_id: Annotated[str | None, Query(description="评估输入使用的 DatasetExport id")] = None,
    dataset_export_manifest_key: Annotated[
        str | None,
        Query(description="评估输入使用的导出 manifest object key"),
    ] = None,
    model_version_id: Annotated[str | None, Query(description="待评估 ModelVersion id")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
) -> list[YoloXEvaluationTaskSummaryResponse]:
    """按公开筛选条件列出 YOLOX 评估任务。"""

    project_ids = _resolve_visible_project_ids(principal=principal, project_id=project_id)
    service = SqlAlchemyTaskService(session_factory)
    matched_tasks = []
    for current_project_id in project_ids:
        matched_tasks.extend(
            service.list_tasks(
                TaskQueryFilters(
                    project_id=current_project_id,
                    task_kind=YOLOX_EVALUATION_TASK_KIND,
                    state=state,
                    created_by=created_by,
                    limit=limit,
                )
            )
        )

    visible_tasks = [
        task
        for task in matched_tasks
        if _matches_yolox_evaluation_filters(
            task=task,
            dataset_export_id=dataset_export_id,
            dataset_export_manifest_key=dataset_export_manifest_key,
            model_version_id=model_version_id,
        )
    ]
    visible_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
    return [_build_yolox_evaluation_task_summary_response(task) for task in visible_tasks[:limit]]


@yolox_evaluation_tasks_router.get(
    "/yolox/evaluation-tasks/{task_id}",
    response_model=YoloXEvaluationTaskDetailResponse,
)
def get_yolox_evaluation_task_detail(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    include_events: Annotated[bool, Query(description="是否返回事件列表")] = True,
) -> YoloXEvaluationTaskDetailResponse:
    """按任务 id 返回 YOLOX 评估任务详情。"""

    task_detail = _require_visible_yolox_evaluation_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=include_events,
    )
    return _build_yolox_evaluation_task_detail_response(task_detail.task, tuple(task_detail.events))


@yolox_evaluation_tasks_router.get(
    "/yolox/evaluation-tasks/{task_id}/report",
    response_model=YoloXEvaluationReportResponse,
)
def get_yolox_evaluation_task_report(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> YoloXEvaluationReportResponse:
    """按任务 id 返回当前 YOLOX 评估报告。"""

    task_detail = _require_visible_yolox_evaluation_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    return _read_yolox_evaluation_report(task=task_detail.task, dataset_storage=dataset_storage)


@yolox_evaluation_tasks_router.get(
    "/yolox/evaluation-tasks/{task_id}/output-files",
    response_model=list[YoloXEvaluationOutputFileSummaryResponse],
)
def list_yolox_evaluation_output_files(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> list[YoloXEvaluationOutputFileSummaryResponse]:
    """按任务 id 列出当前 YOLOX 评估输出文件状态。"""

    task_detail = _require_visible_yolox_evaluation_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    return [
        _build_yolox_evaluation_output_file_summary_response(
            task=task_detail.task,
            file_name=file_name,
            dataset_storage=dataset_storage,
        )
        for file_name in _YOLOX_EVALUATION_OUTPUT_FILE_ORDER
    ]


def _resolve_visible_project_ids(
    *,
    principal: AuthenticatedPrincipal,
    project_id: str | None,
) -> tuple[str, ...]:
    """根据主体权限和查询条件解析可查询的 Project 范围。"""

    if project_id is not None:
        if principal.project_ids and project_id not in principal.project_ids:
            raise ResourceNotFoundError(
                "找不到指定的任务范围",
                details={"project_id": project_id},
            )
        return (project_id,)

    if principal.project_ids:
        return principal.project_ids

    raise InvalidRequestError("查询评估任务列表时必须提供 project_id")


def _ensure_task_visible(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    task_project_id: str,
) -> None:
    """校验当前主体是否可以访问指定任务。"""

    if principal.project_ids and task_project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的任务",
            details={"task_id": task_id},
        )


def _matches_yolox_evaluation_filters(
    *,
    task: object,
    dataset_export_id: str | None,
    dataset_export_manifest_key: str | None,
    model_version_id: str | None,
) -> bool:
    """判断 YOLOX 评估任务是否满足额外筛选条件。"""

    task_spec = dict(task.task_spec)
    manifest_object_key = task_spec.get("manifest_object_key")
    if dataset_export_id is not None and task_spec.get("dataset_export_id") != dataset_export_id:
        return False
    if model_version_id is not None and task_spec.get("model_version_id") != model_version_id:
        return False
    if (
        dataset_export_manifest_key is not None
        and task_spec.get("dataset_export_manifest_key") != dataset_export_manifest_key
        and manifest_object_key != dataset_export_manifest_key
    ):
        return False
    return True


def _require_visible_yolox_evaluation_task(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    session_factory: SessionFactory,
    include_events: bool,
):
    """读取并校验当前主体可见的 YOLOX 评估任务。"""

    service = SqlAlchemyTaskService(session_factory)
    task_detail = service.get_task(task_id, include_events=include_events)
    _ensure_task_visible(
        principal=principal,
        task_id=task_id,
        task_project_id=task_detail.task.project_id,
    )
    if task_detail.task.task_kind != YOLOX_EVALUATION_TASK_KIND:
        raise ResourceNotFoundError(
            "找不到指定的 YOLOX 评估任务",
            details={"task_id": task_id},
        )
    return task_detail


def _build_yolox_evaluation_task_summary_response(
    task: object,
) -> YoloXEvaluationTaskSummaryResponse:
    """把 YOLOX 评估 TaskRecord 转成摘要响应。"""

    task_spec = dict(task.task_spec)
    result = dict(task.result)
    metadata = dict(task.metadata)
    report_summary = result.get("report_summary")
    report_summary_payload = dict(report_summary) if isinstance(report_summary, dict) else {}
    map50 = result.get("map50")
    map50_95 = result.get("map50_95")
    model_version_id = _read_optional_str(task_spec, "model_version_id")
    if model_version_id is None:
        model_version_id = _read_optional_str(result, "model_version_id") or ""
    return YoloXEvaluationTaskSummaryResponse(
        task_id=task.task_id,
        display_name=task.display_name,
        project_id=task.project_id,
        created_by=task.created_by,
        created_at=task.created_at,
        worker_pool=task.worker_pool,
        state=task.state,
        current_attempt_no=task.current_attempt_no,
        started_at=task.started_at,
        finished_at=task.finished_at,
        progress=dict(task.progress),
        result=result,
        error_message=task.error_message,
        metadata=metadata,
        dataset_export_id=_read_optional_str(task_spec, "dataset_export_id"),
        dataset_export_manifest_key=(
            _read_optional_str(task_spec, "dataset_export_manifest_key")
            or _read_optional_str(task_spec, "manifest_object_key")
        ),
        dataset_version_id=_read_optional_str(result, "dataset_version_id")
        or _read_optional_str(metadata, "dataset_version_id"),
        format_id=_read_optional_str(result, "format_id")
        or _read_optional_str(metadata, "format_id"),
        model_version_id=model_version_id,
        score_threshold=(
            float(task_spec["score_threshold"])
            if isinstance(task_spec.get("score_threshold"), int | float)
            else None
        ),
        nms_threshold=(
            float(task_spec["nms_threshold"])
            if isinstance(task_spec.get("nms_threshold"), int | float)
            else None
        ),
        save_result_package=bool(task_spec.get("save_result_package") is True),
        output_object_prefix=(
            _read_optional_str(result, "output_object_prefix")
            or _read_optional_str(metadata, "output_object_prefix")
        ),
        report_object_key=_read_optional_str(result, "report_object_key"),
        detections_object_key=_read_optional_str(result, "detections_object_key"),
        result_package_object_key=_read_optional_str(result, "result_package_object_key"),
        map50=float(map50) if isinstance(map50, int | float) else None,
        map50_95=float(map50_95) if isinstance(map50_95, int | float) else None,
        report_summary=report_summary_payload,
    )


def _build_yolox_evaluation_task_detail_response(
    task: object,
    events: tuple[object, ...],
) -> YoloXEvaluationTaskDetailResponse:
    """把 YOLOX 评估 TaskRecord 转成详情响应。"""

    summary_response = _build_yolox_evaluation_task_summary_response(task)
    return YoloXEvaluationTaskDetailResponse(
        **summary_response.model_dump(),
        task_spec=dict(task.task_spec),
        events=[
            YoloXEvaluationTaskEventResponse(
                event_id=event.event_id,
                task_id=event.task_id,
                attempt_id=event.attempt_id,
                event_type=event.event_type,
                created_at=event.created_at,
                message=event.message,
                payload=dict(event.payload),
            )
            for event in events
        ],
    )


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从字典中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None