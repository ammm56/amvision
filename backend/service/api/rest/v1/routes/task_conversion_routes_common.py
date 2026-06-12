"""按 task_type 生成模型转换任务 REST 路由。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.conversions.conversion_result_snapshot import (
    ConversionResultSnapshot,
)
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class TaskConversionServiceEntry:
    """描述一个模型分类对应的转换任务服务。

    字段：
    - service_cls：执行当前模型转换任务登记、查询和结果读取的服务类。
    - request_cls：当前模型转换任务创建请求类型。
    - task_kind：任务系统中保存的 task_kind。
    - queue_name：任务提交后进入的队列名。
    - request_includes_task_type：创建请求是否需要显式传入 task_type。
    """

    service_cls: type
    request_cls: type
    task_kind: str
    queue_name: str
    request_includes_task_type: bool = False


class TaskConversionTaskCreateRequestBody(BaseModel):
    """描述一次 task-native conversion 任务创建请求。"""

    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description="模型分类")
    source_model_version_id: str = Field(description="来源 ModelVersion id")
    target_formats: tuple[str, ...] = Field(min_length=1, description="目标 build 格式列表")
    runtime_profile_id: str | None = Field(default=None, description="可选 RuntimeProfile id")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加转换选项")
    display_name: str = Field(default="", description="可选任务展示名称")


class TaskConversionTaskSubmissionResponse(BaseModel):
    """描述一次 task-native conversion 任务提交响应。"""

    task_id: str = Field(description="转换任务 id")
    status: str = Field(description="转换任务当前状态")
    queue_name: str = Field(description="提交到的队列名称")
    queue_task_id: str = Field(description="队列任务 id")
    task_type: str = Field(description="任务类型")
    model_type: str = Field(description="模型分类")
    source_model_version_id: str = Field(description="来源 ModelVersion id")
    target_formats: list[str] = Field(description="固化后的目标格式列表")


class TaskConversionBuildSummaryResponse(BaseModel):
    """描述单个 conversion 输出登记后的 ModelBuild 摘要响应。"""

    model_build_id: str = Field(description="登记后的 ModelBuild id")
    build_format: str = Field(description="build 格式")
    build_file_id: str = Field(description="对应 ModelFile id")
    build_file_uri: str = Field(description="构建产物 object key 或本地 URI")
    metadata: dict[str, object] = Field(default_factory=dict, description="构建元数据")


class TaskConversionTaskSummaryResponse(BaseModel):
    """描述 task-native conversion 任务摘要响应。"""

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
    task_type: str = Field(description="任务类型")
    model_type: str = Field(description="模型分类")
    source_model_version_id: str = Field(description="来源 ModelVersion id")
    target_formats: list[str] = Field(default_factory=list, description="请求固化的目标格式列表")
    runtime_profile_id: str | None = Field(default=None, description="目标 RuntimeProfile id")
    output_object_prefix: str | None = Field(default=None, description="输出目录前缀")
    plan_object_key: str | None = Field(default=None, description="转换计划 object key")
    report_object_key: str | None = Field(default=None, description="转换结果报告 object key")
    requested_target_formats: list[str] = Field(default_factory=list, description="提交请求中的目标格式")
    produced_formats: list[str] = Field(default_factory=list, description="实际产出的格式列表")
    builds: list[TaskConversionBuildSummaryResponse] = Field(default_factory=list, description="登记成功的构建摘要列表")
    report_summary: dict[str, object] = Field(default_factory=dict, description="转换摘要")


class TaskConversionTaskEventResponse(BaseModel):
    """描述 task-native conversion 任务事件响应。"""

    event_id: str = Field(description="事件 id")
    task_id: str = Field(description="所属任务 id")
    attempt_id: str | None = Field(default=None, description="关联尝试 id")
    event_type: str = Field(description="事件类型")
    created_at: str = Field(description="事件时间")
    message: str = Field(description="事件消息")
    payload: dict[str, object] = Field(default_factory=dict, description="事件负载")


class TaskConversionTaskDetailResponse(TaskConversionTaskSummaryResponse):
    """描述 task-native conversion 任务详情响应。"""

    task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
    events: list[TaskConversionTaskEventResponse] = Field(default_factory=list, description="任务事件列表")


class TaskConversionResultResponse(BaseModel):
    """描述 task-native conversion 结果读取响应。"""

    file_status: str = Field(description="转换结果文件状态")
    task_state: str = Field(description="当前转换任务状态")
    object_key: str | None = Field(default=None, description="转换结果文件 object key")
    payload: dict[str, object] = Field(default_factory=dict, description="转换结果 JSON 内容")


def create_task_conversion_router(
    *,
    route_segment: str,
    task_type: str,
    service_entries: dict[str, TaskConversionServiceEntry],
) -> APIRouter:
    """生成一个 task_type 专用 conversion REST 路由。

    参数：
    - route_segment：URL 中的任务路径片段，例如 classification。
    - task_type：模型任务类型，例如 classification。
    - service_entries：当前任务类型支持的模型分类到服务配置的映射。

    返回：
    - APIRouter：已经挂载 create/list/detail/result 的路由对象。
    """

    router = APIRouter(prefix="/models", tags=["models"])
    supported_text = "、".join(sorted(service_entries))

    @router.post(
        f"/{route_segment}/conversion-tasks",
        response_model=TaskConversionTaskSubmissionResponse,
        status_code=status.HTTP_202_ACCEPTED,
        operation_id=f"create_{task_type}_conversion_task",
    )
    def create_conversion_task(
        body: TaskConversionTaskCreateRequestBody,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    ) -> TaskConversionTaskSubmissionResponse:
        """创建一个 task_type 专用 conversion 任务。"""

        return submit_task_conversion_task(
            body=body,
            task_type=task_type,
            supported_text=supported_text,
            service_entries=service_entries,
            principal=principal,
            session_factory=session_factory,
            queue_backend=queue_backend,
            dataset_storage=dataset_storage,
        )

    @router.get(
        f"/{route_segment}/conversion-tasks",
        response_model=list[TaskConversionTaskSummaryResponse],
        operation_id=f"list_{task_type}_conversion_tasks",
    )
    def list_conversion_tasks(
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
        model_type: Annotated[str | None, Query(description="模型分类")] = None,
        state: Annotated[str | None, Query(description="任务状态")] = None,
        created_by: Annotated[str | None, Query(description="提交主体 id")] = None,
        source_model_version_id: Annotated[str | None, Query(description="来源 ModelVersion id")] = None,
        target_format: Annotated[str | None, Query(description="目标 build 格式")] = None,
        limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
    ) -> list[TaskConversionTaskSummaryResponse]:
        """列出当前 task_type 的 conversion 任务。"""

        visible_project_ids = _resolve_visible_project_ids(principal=principal, project_id=project_id)
        task_kinds = _resolve_task_kinds(
            model_type=model_type,
            task_type=task_type,
            supported_text=supported_text,
            service_entries=service_entries,
        )
        task_service = SqlAlchemyTaskService(session_factory)
        matched_tasks: list[Any] = []
        for current_project_id in visible_project_ids:
            for task_kind in task_kinds:
                matched_tasks.extend(
                    task_service.list_tasks(
                        TaskQueryFilters(
                            project_id=current_project_id,
                            task_kind=task_kind,
                            state=state,
                            created_by=created_by,
                            limit=limit,
                        )
                    )
                )
        visible_tasks = [
            task
            for task in matched_tasks
            if _matches_task_conversion_filters(
                task=task,
                task_type=task_type,
                source_model_version_id=source_model_version_id,
                target_format=target_format,
            )
        ]
        visible_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
        return [
            build_task_conversion_task_summary_response(
                task,
                task_type=task_type,
                model_type=_resolve_model_type_from_task(
                    task=task,
                    task_type=task_type,
                    service_entries=service_entries,
                ),
            )
            for task in visible_tasks[:limit]
        ]

    @router.get(
        f"/{route_segment}/conversion-tasks/{{task_id}}",
        response_model=TaskConversionTaskDetailResponse,
        operation_id=f"get_{task_type}_conversion_task_detail",
    )
    def get_conversion_task_detail(
        task_id: str,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        include_events: Annotated[bool, Query(description="是否返回事件列表")] = False,
    ) -> TaskConversionTaskDetailResponse:
        """读取当前 task_type 的 conversion 任务详情。"""

        task_detail = require_visible_task_conversion_task(
            principal=principal,
            task_id=task_id,
            task_type=task_type,
            service_entries=service_entries,
            session_factory=session_factory,
            include_events=include_events,
        )
        model_type = _resolve_model_type_from_task(
            task=task_detail.task,
            task_type=task_type,
            service_entries=service_entries,
        )
        return build_task_conversion_task_detail_response(
            task_detail.task,
            tuple(task_detail.events),
            task_type=task_type,
            model_type=model_type,
        )

    @router.get(
        f"/{route_segment}/conversion-tasks/{{task_id}}/result",
        response_model=TaskConversionResultResponse,
        operation_id=f"get_{task_type}_conversion_task_result",
    )
    def get_conversion_task_result(
        task_id: str,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    ) -> TaskConversionResultResponse:
        """读取当前 task_type 的 conversion 结果文件状态和摘要。"""

        task_detail = require_visible_task_conversion_task(
            principal=principal,
            task_id=task_id,
            task_type=task_type,
            service_entries=service_entries,
            session_factory=session_factory,
            include_events=False,
        )
        model_type = _resolve_model_type_from_task(
            task=task_detail.task,
            task_type=task_type,
            service_entries=service_entries,
        )
        entry = service_entries[model_type]
        result_snapshot = entry.service_cls(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        ).read_conversion_result(task_id)
        return build_task_conversion_result_response(task_id, result_snapshot)

    return router


def submit_task_conversion_task(
    *,
    body: TaskConversionTaskCreateRequestBody,
    task_type: str,
    supported_text: str,
    service_entries: dict[str, TaskConversionServiceEntry],
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    queue_backend: LocalFileQueueBackend,
    dataset_storage: LocalDatasetStorage,
) -> TaskConversionTaskSubmissionResponse:
    """提交一条 task-native conversion 任务。"""

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的 Project",
            details={"project_id": body.project_id},
        )
    model_type = _normalize_model_type(
        value=body.model_type,
        task_type=task_type,
        supported_text=supported_text,
        service_entries=service_entries,
    )
    entry = service_entries[model_type]
    request_kwargs: dict[str, object] = {
        "project_id": body.project_id,
        "source_model_version_id": body.source_model_version_id,
        "target_formats": tuple(body.target_formats),
        "runtime_profile_id": body.runtime_profile_id,
        "extra_options": dict(body.extra_options),
    }
    if entry.request_includes_task_type:
        request_kwargs["task_type"] = task_type
    submission = entry.service_cls(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    ).submit_conversion_task(
        entry.request_cls(**request_kwargs),
        created_by=principal.principal_id,
        display_name=body.display_name,
    )
    return TaskConversionTaskSubmissionResponse(
        task_id=submission.task_id,
        status=submission.status,
        queue_name=submission.queue_name,
        queue_task_id=submission.queue_task_id,
        task_type=task_type,
        model_type=model_type,
        source_model_version_id=submission.source_model_version_id,
        target_formats=list(submission.target_formats),
    )


def require_visible_task_conversion_task(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    task_type: str,
    service_entries: dict[str, TaskConversionServiceEntry],
    session_factory: SessionFactory,
    include_events: bool,
):
    """读取并校验当前主体可见的 task-native conversion 任务。"""

    task_detail = SqlAlchemyTaskService(session_factory).get_task(task_id, include_events=include_events)
    if principal.project_ids and task_detail.task.project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的转换任务",
            details={"task_id": task_id},
        )
    if task_detail.task.task_kind not in _build_task_kind_set(service_entries):
        raise ResourceNotFoundError(
            f"找不到指定的 {task_type} conversion 任务",
            details={"task_id": task_id},
        )
    if _read_task_type(task_detail.task) != task_type:
        raise ResourceNotFoundError(
            f"找不到指定的 {task_type} conversion 任务",
            details={"task_id": task_id},
        )
    return task_detail


def build_task_conversion_task_summary_response(
    task: object,
    *,
    task_type: str,
    model_type: str,
) -> TaskConversionTaskSummaryResponse:
    """把 TaskRecord 转成 task-native conversion 摘要响应。"""

    task_spec = dict(task.task_spec)
    result = dict(task.result)
    metadata = dict(task.metadata)
    report_summary = result.get("report_summary")
    report_summary_payload = dict(report_summary) if isinstance(report_summary, dict) else {}
    raw_builds = result.get("builds")
    builds_payload = [
        TaskConversionBuildSummaryResponse(
            model_build_id=_read_optional_str(item, "model_build_id") or "",
            build_format=_read_optional_str(item, "build_format") or "",
            build_file_id=_read_optional_str(item, "build_file_id") or "",
            build_file_uri=_read_optional_str(item, "build_file_uri") or "",
            metadata=dict(item.get("metadata")) if isinstance(item.get("metadata"), dict) else {},
        )
        for item in raw_builds
        if isinstance(item, dict)
    ] if isinstance(raw_builds, list) else []
    return TaskConversionTaskSummaryResponse(
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
        task_type=task_type,
        model_type=model_type,
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


def build_task_conversion_task_detail_response(
    task: object,
    events: tuple[object, ...],
    *,
    task_type: str,
    model_type: str,
) -> TaskConversionTaskDetailResponse:
    """把 TaskRecord 转成 task-native conversion 详情响应。"""

    summary = build_task_conversion_task_summary_response(
        task,
        task_type=task_type,
        model_type=model_type,
    )
    return TaskConversionTaskDetailResponse(
        **summary.model_dump(),
        task_spec=dict(task.task_spec),
        events=[
            TaskConversionTaskEventResponse(
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


def build_task_conversion_result_response(
    task_id: str,
    result_snapshot: ConversionResultSnapshot,
) -> TaskConversionResultResponse:
    """把 conversion 结果快照转换为公开响应。"""

    if result_snapshot.file_status not in {"pending", "ready"}:
        raise ResourceNotFoundError(
            "找不到指定的转换结果",
            details={"task_id": task_id},
        )
    return TaskConversionResultResponse(
        file_status=result_snapshot.file_status,
        task_state=result_snapshot.task_state,
        object_key=result_snapshot.object_key,
        payload=dict(result_snapshot.payload),
    )


def _normalize_model_type(
    *,
    value: str,
    task_type: str,
    supported_text: str,
    service_entries: dict[str, TaskConversionServiceEntry],
) -> str:
    """把模型分类归一化为当前 task_type 支持的正式值。"""

    normalized_value = value.strip().lower()
    if normalized_value not in service_entries:
        raise InvalidRequestError(
            f"当前 {task_type} conversion 仅支持 {supported_text}",
            details={"model_type": value},
        )
    return normalized_value


def _resolve_task_kinds(
    *,
    model_type: str | None,
    task_type: str,
    supported_text: str,
    service_entries: dict[str, TaskConversionServiceEntry],
) -> tuple[str, ...]:
    """根据查询条件返回需要覆盖的 task_kind。"""

    if model_type is None:
        return tuple(dict.fromkeys(entry.task_kind for entry in service_entries.values()))
    normalized_model_type = _normalize_model_type(
        value=model_type,
        task_type=task_type,
        supported_text=supported_text,
        service_entries=service_entries,
    )
    return (service_entries[normalized_model_type].task_kind,)


def _resolve_model_type_from_task(
    *,
    task: object,
    task_type: str,
    service_entries: dict[str, TaskConversionServiceEntry],
) -> str:
    """从 TaskRecord 中解析模型分类。"""

    metadata = dict(getattr(task, "metadata", {}) or {})
    model_type = metadata.get("model_type")
    if isinstance(model_type, str) and model_type.strip() in service_entries:
        return model_type.strip().lower()
    task_kind = str(getattr(task, "task_kind", ""))
    for current_model_type, entry in service_entries.items():
        if entry.task_kind == task_kind:
            return current_model_type
    raise ResourceNotFoundError(
        f"找不到指定的 {task_type} conversion 任务",
        details={"task_id": getattr(task, "task_id", None)},
    )


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


def _matches_task_conversion_filters(
    *,
    task: object,
    task_type: str,
    source_model_version_id: str | None,
    target_format: str | None,
) -> bool:
    """判断 conversion 任务是否满足 task_type 和公开筛选条件。"""

    if _read_task_type(task) != task_type:
        return False
    task_spec = dict(getattr(task, "task_spec", {}) or {})
    task_result = dict(getattr(task, "result", {}) or {})
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


def _read_task_type(task: object) -> str | None:
    """从 TaskRecord 的 metadata、result 或 task_spec 中读取 task_type。"""

    for payload_name in ("metadata", "result", "task_spec"):
        payload = dict(getattr(task, payload_name, {}) or {})
        value = payload.get("task_type")
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def _build_task_kind_set(service_entries: dict[str, TaskConversionServiceEntry]) -> frozenset[str]:
    """返回当前路由支持的 task_kind 集合。"""

    return frozenset(entry.task_kind for entry in service_entries.values())


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
