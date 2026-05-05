"""YOLOX conversion task REST 路由。"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.conversions.yolox_conversion_task_service import (
    SqlAlchemyYoloXConversionTaskService,
    YoloXConversionTaskRequest,
    YoloXConversionResultSnapshot,
)
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


yolox_conversion_tasks_router = APIRouter(prefix="/models", tags=["models"])

YoloXConversionTargetLiteral = Literal[
    "onnx",
    "onnx-optimized",
    "openvino-ir",
    "tensorrt-engine",
    "rknn",
]


class YoloXConversionTaskCreateRequestBody(BaseModel):
    """描述 YOLOX conversion 任务创建请求体。

    字段：
    - project_id：所属 Project id。
    - source_model_version_id：来源 ModelVersion id。
    - target_formats：目标 build 格式列表。
    - runtime_profile_id：可选 RuntimeProfile id。
    - extra_options：附加转换选项。
    - display_name：可选任务展示名称。
    """

    project_id: str = Field(description="所属 Project id")
    source_model_version_id: str = Field(description="来源 ModelVersion id")
    target_formats: list[YoloXConversionTargetLiteral] = Field(description="目标 build 格式列表")
    runtime_profile_id: str | None = Field(default=None, description="可选 RuntimeProfile id")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加转换选项")
    display_name: str = Field(default="", description="可选任务展示名称")


class YoloXConversionTaskSubmissionResponse(BaseModel):
    """描述 YOLOX conversion 任务创建响应。

    字段：
    - task_id：转换任务 id。
    - status：转换任务当前状态。
    - queue_name：提交到的队列名称。
    - queue_task_id：队列任务 id。
    - source_model_version_id：来源 ModelVersion id。
    - target_formats：固化后的目标格式列表。
    """

    task_id: str = Field(description="转换任务 id")
    status: str = Field(description="转换任务当前状态")
    queue_name: str = Field(description="提交到的队列名称")
    queue_task_id: str = Field(description="队列任务 id")
    source_model_version_id: str = Field(description="来源 ModelVersion id")
    target_formats: list[YoloXConversionTargetLiteral] = Field(description="固化后的目标格式列表")


class YoloXConversionBuildSummaryResponse(BaseModel):
    """描述单个转换输出登记后的 ModelBuild 摘要响应。

    字段：
    - model_build_id：登记后的 ModelBuild id。
    - build_format：build 格式。
    - build_file_id：对应 ModelFile id。
    - build_file_uri：构建产物 object key 或本地 URI。
    - metadata：构建元数据。
    """

    model_build_id: str = Field(description="登记后的 ModelBuild id")
    build_format: str = Field(description="build 格式")
    build_file_id: str = Field(description="对应 ModelFile id")
    build_file_uri: str = Field(description="构建产物 object key 或本地 URI")
    metadata: dict[str, object] = Field(default_factory=dict, description="构建元数据")


class YoloXConversionTaskSummaryResponse(BaseModel):
    """描述 YOLOX conversion 任务摘要响应。

    字段：
    - task_id：转换任务 id。
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
    - source_model_version_id：来源 ModelVersion id。
    - target_formats：请求固化的目标格式列表。
    - runtime_profile_id：目标 RuntimeProfile id。
    - output_object_prefix：输出目录前缀。
    - plan_object_key：转换计划 object key。
    - report_object_key：转换结果报告 object key。
    - requested_target_formats：提交请求中的目标格式。
    - produced_formats：实际产出的格式列表。
    - builds：登记成功的构建摘要列表。
    - report_summary：转换摘要。
    """

    task_id: str = Field(description="转换任务 id")
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
    source_model_version_id: str = Field(description="来源 ModelVersion id")
    target_formats: list[str] = Field(default_factory=list, description="请求固化的目标格式列表")
    runtime_profile_id: str | None = Field(default=None, description="目标 RuntimeProfile id")
    output_object_prefix: str | None = Field(default=None, description="输出目录前缀")
    plan_object_key: str | None = Field(default=None, description="转换计划 object key")
    report_object_key: str | None = Field(default=None, description="转换结果报告 object key")
    requested_target_formats: list[str] = Field(default_factory=list, description="提交请求中的目标格式")
    produced_formats: list[str] = Field(default_factory=list, description="实际产出的格式列表")
    builds: list[YoloXConversionBuildSummaryResponse] = Field(default_factory=list, description="登记成功的构建摘要列表")
    report_summary: dict[str, object] = Field(default_factory=dict, description="转换摘要")


class YoloXConversionTaskEventResponse(BaseModel):
    """描述 YOLOX conversion 任务事件响应。"""

    event_id: str = Field(description="事件 id")
    task_id: str = Field(description="所属任务 id")
    attempt_id: str | None = Field(default=None, description="关联尝试 id")
    event_type: str = Field(description="事件类型")
    created_at: str = Field(description="事件时间")
    message: str = Field(description="事件消息")
    payload: dict[str, object] = Field(default_factory=dict, description="事件负载")


class YoloXConversionTaskDetailResponse(YoloXConversionTaskSummaryResponse):
    """描述 YOLOX conversion 任务详情响应。"""

    task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
    events: list[YoloXConversionTaskEventResponse] = Field(default_factory=list, description="任务事件列表")


class YoloXConversionResultResponse(BaseModel):
    """描述 YOLOX conversion 结果读取响应。"""

    file_status: Literal["pending", "ready"] = Field(description="转换结果文件状态")
    task_state: str = Field(description="当前转换任务状态")
    object_key: str | None = Field(default=None, description="转换结果文件 object key")
    payload: dict[str, object] = Field(default_factory=dict, description="转换结果 JSON 内容")


@yolox_conversion_tasks_router.post(
    "/yolox/conversion-tasks",
    response_model=YoloXConversionTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_yolox_conversion_task(
    body: YoloXConversionTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> YoloXConversionTaskSubmissionResponse:
    """创建一个 YOLOX conversion task。"""

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": body.project_id},
        )
    service = SqlAlchemyYoloXConversionTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    submission = service.submit_conversion_task(
        YoloXConversionTaskRequest(
            project_id=body.project_id,
            source_model_version_id=body.source_model_version_id,
            target_formats=tuple(body.target_formats),
            runtime_profile_id=body.runtime_profile_id,
            extra_options=dict(body.extra_options),
        ),
        created_by=principal.principal_id,
        display_name=body.display_name,
    )
    return YoloXConversionTaskSubmissionResponse(
        task_id=submission.task_id,
        status=submission.status,
        queue_name=submission.queue_name,
        queue_task_id=submission.queue_task_id,
        source_model_version_id=submission.source_model_version_id,
        target_formats=list(submission.target_formats),
    )


@yolox_conversion_tasks_router.get(
    "/yolox/conversion-tasks",
    response_model=list[YoloXConversionTaskSummaryResponse],
)
def list_yolox_conversion_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
    state: Annotated[str | None, Query(description="任务状态")] = None,
    created_by: Annotated[str | None, Query(description="提交主体 id")] = None,
    source_model_version_id: Annotated[str | None, Query(description="来源 ModelVersion id")] = None,
    target_format: Annotated[str | None, Query(description="目标 build 格式")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
) -> list[YoloXConversionTaskSummaryResponse]:
    """按公开筛选条件列出 YOLOX conversion 任务。"""

    project_ids = _resolve_visible_project_ids(principal=principal, project_id=project_id)
    service = SqlAlchemyYoloXConversionTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    matched_tasks = []
    for current_project_id in project_ids:
        matched_tasks.extend(
            service.list_conversion_tasks(
                project_id=current_project_id,
                state=state,  # type: ignore[arg-type]
                created_by=created_by,
                limit=limit,
            )
        )

    visible_tasks = [
        task
        for task in matched_tasks
        if _matches_yolox_conversion_filters(
            task=task,
            source_model_version_id=source_model_version_id,
            target_format=target_format,
        )
    ]
    visible_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
    return [_build_yolox_conversion_task_summary_response(task) for task in visible_tasks[:limit]]


@yolox_conversion_tasks_router.get(
    "/yolox/conversion-tasks/{task_id}",
    response_model=YoloXConversionTaskDetailResponse,
)
def get_yolox_conversion_task_detail(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    include_events: Annotated[bool, Query(description="是否返回事件列表")] = True,
) -> YoloXConversionTaskDetailResponse:
    """按任务 id 返回 YOLOX conversion 任务详情。"""

    task_detail = _require_visible_yolox_conversion_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        include_events=include_events,
    )
    return _build_yolox_conversion_task_detail_response(task_detail.task, tuple(task_detail.events))


@yolox_conversion_tasks_router.get(
    "/yolox/conversion-tasks/{task_id}/result",
    response_model=YoloXConversionResultResponse,
)
def get_yolox_conversion_task_result(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> YoloXConversionResultResponse:
    """按任务 id 返回当前 YOLOX conversion 结果。"""

    service = SqlAlchemyYoloXConversionTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    task_detail = _require_visible_yolox_conversion_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        include_events=False,
    )
    result_snapshot = service.read_conversion_result(task_id)
    return _build_yolox_conversion_result_response(task_detail.task.task_id, result_snapshot)


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

    raise InvalidRequestError("查询转换任务列表时必须提供 project_id")


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


def _matches_yolox_conversion_filters(
    *,
    task: object,
    source_model_version_id: str | None,
    target_format: str | None,
) -> bool:
    """判断 YOLOX conversion 任务是否满足额外筛选条件。"""

    task_spec = dict(task.task_spec)
    task_result = dict(task.result)
    if (
        source_model_version_id is not None
        and task_spec.get("source_model_version_id") != source_model_version_id
        and task_result.get("source_model_version_id") != source_model_version_id
    ):
        return False
    if target_format is not None:
        requested_target_formats = task_spec.get("target_formats")
        produced_formats = task_result.get("produced_formats")
        requested_matches = isinstance(requested_target_formats, list) and target_format in requested_target_formats
        produced_matches = isinstance(produced_formats, list) and target_format in produced_formats
        if not requested_matches and not produced_matches:
            return False
    return True


def _require_visible_yolox_conversion_task(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    include_events: bool,
):
    """读取并校验当前主体可见的 YOLOX conversion 任务。"""

    service = SqlAlchemyYoloXConversionTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    task_detail = service.get_conversion_task_detail(task_id, include_events=include_events)
    _ensure_task_visible(
        principal=principal,
        task_id=task_id,
        task_project_id=task_detail.task.project_id,
    )
    return task_detail


def _build_yolox_conversion_task_summary_response(task: object) -> YoloXConversionTaskSummaryResponse:
    """把 YOLOX conversion TaskRecord 转成摘要响应。"""

    task_spec = dict(task.task_spec)
    result = dict(task.result)
    metadata = dict(task.metadata)
    report_summary = result.get("report_summary")
    report_summary_payload = dict(report_summary) if isinstance(report_summary, dict) else {}
    raw_builds = result.get("builds")
    builds_payload = [
        YoloXConversionBuildSummaryResponse(
            model_build_id=_read_optional_str(item, "model_build_id") or "",
            build_format=_read_optional_str(item, "build_format") or "",
            build_file_id=_read_optional_str(item, "build_file_id") or "",
            build_file_uri=_read_optional_str(item, "build_file_uri") or "",
            metadata=dict(item.get("metadata")) if isinstance(item.get("metadata"), dict) else {},
        )
        for item in raw_builds
        if isinstance(item, dict)
    ] if isinstance(raw_builds, list) else []
    return YoloXConversionTaskSummaryResponse(
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
        source_model_version_id=(
            _read_optional_str(task_spec, "source_model_version_id")
            or _read_optional_str(result, "source_model_version_id")
            or _read_optional_str(metadata, "source_model_version_id")
            or ""
        ),
        target_formats=_read_optional_str_list(task_spec, "target_formats"),
        runtime_profile_id=(
            _read_optional_str(task_spec, "runtime_profile_id")
            or _read_optional_str(metadata, "runtime_profile_id")
        ),
        output_object_prefix=_read_optional_str(result, "output_object_prefix"),
        plan_object_key=_read_optional_str(result, "plan_object_key"),
        report_object_key=_read_optional_str(result, "report_object_key"),
        requested_target_formats=_read_optional_str_list(result, "requested_target_formats"),
        produced_formats=_read_optional_str_list(result, "produced_formats"),
        builds=builds_payload,
        report_summary=report_summary_payload,
    )


def _build_yolox_conversion_task_detail_response(
    task: object,
    events: tuple[object, ...],
) -> YoloXConversionTaskDetailResponse:
    """把 YOLOX conversion TaskRecord 转成详情响应。"""

    summary_response = _build_yolox_conversion_task_summary_response(task)
    return YoloXConversionTaskDetailResponse(
        **summary_response.model_dump(),
        task_spec=dict(task.task_spec),
        events=[
            YoloXConversionTaskEventResponse(
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


def _build_yolox_conversion_result_response(
    task_id: str,
    result_snapshot: YoloXConversionResultSnapshot,
) -> YoloXConversionResultResponse:
    """把 conversion 结果快照转换为公开响应。"""

    if result_snapshot.file_status not in {"pending", "ready"}:
        raise ResourceNotFoundError(
            "找不到指定的转换结果",
            details={"task_id": task_id},
        )
    return YoloXConversionResultResponse(
        file_status=result_snapshot.file_status,  # type: ignore[arg-type]
        task_state=result_snapshot.task_state,
        object_key=result_snapshot.object_key,
        payload=dict(result_snapshot.payload),
    )


def _read_optional_str(payload: dict[str, object], key: str) -> str | None:
    """从字典中读取可选字符串字段。"""

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _read_optional_str_list(payload: dict[str, object], key: str) -> list[str]:
    """从字典中读取可选字符串列表字段。"""

    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]