"""task-native conversion 路由服务装配。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.model_type_support import (
    normalize_optional_platform_model_type,
    require_platform_model_type,
)
from backend.service.application.task_type_support import require_supported_platform_task_type
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

from .deletion import delete_conversion_task_outputs
from .outputs import read_task_conversion_result_response
from .responses import (
    build_task_conversion_task_detail_response,
    build_task_conversion_task_summary_response,
)
from .schemas import (
    TaskConversionResultResponse,
    TaskConversionTaskCreateRequestBody,
    TaskConversionTaskDetailResponse,
    TaskConversionTaskSubmissionResponse,
    TaskConversionTaskSummaryResponse,
)
from .visibility import (
    matches_task_conversion_filters,
    require_visible_task_conversion_task,
    resolve_visible_project_ids,
)


@dataclass(frozen=True)
class TaskConversionServiceEntry:
    """描述一个模型分类对应的转换任务服务。"""

    service_cls: type
    request_cls: type
    task_kind: str
    queue_name: str
    request_includes_task_type: bool = False


def create_task_conversion_router(
    *,
    route_segment: str,
    task_type: str,
    service_entries: dict[str, TaskConversionServiceEntry],
) -> APIRouter:
    """生成一个 task_type 专用 conversion REST 路由。"""

    task_type = require_supported_platform_task_type(task_type)
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

        visible_project_ids = resolve_visible_project_ids(principal=principal, project_id=project_id)
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
            if matches_task_conversion_filters(
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

    @router.delete(
        f"/{route_segment}/conversion-tasks/{{task_id}}",
        status_code=status.HTTP_204_NO_CONTENT,
        operation_id=f"delete_{task_type}_conversion_task",
    )
    def delete_conversion_task(
        task_id: str,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:write", "tasks:write"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    ) -> Response:
        """删除当前 task_type 的 conversion 任务运行数据和未被部署使用的输出。"""

        task_detail = require_visible_task_conversion_task(
            principal=principal,
            task_id=task_id,
            task_type=task_type,
            service_entries=service_entries,
            session_factory=session_factory,
            include_events=False,
        )
        delete_conversion_task_outputs(
            task=task_detail.task,
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

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
        return read_task_conversion_result_response(
            task_id=task_id,
            model_type=model_type,
            service_entries=service_entries,
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        )

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


def _normalize_model_type(
    *,
    value: str,
    task_type: str,
    supported_text: str,
    service_entries: dict[str, TaskConversionServiceEntry],
) -> str:
    """把模型分类归一化为当前 task_type 支持的正式值。"""

    normalized_value = require_platform_model_type(value)
    if normalized_value not in service_entries:
        raise InvalidRequestError(
            f"当前 {task_type} conversion 仅支持 {supported_text}",
            details={
                "model_type": normalized_value,
                "supported": sorted(service_entries),
            },
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
    normalized_model_type = normalize_optional_platform_model_type(metadata.get("model_type"))
    if normalized_model_type in service_entries:
        return normalized_model_type
    task_kind = str(getattr(task, "task_kind", ""))
    for current_model_type, entry in service_entries.items():
        if entry.task_kind == task_kind:
            return current_model_type
    raise ResourceNotFoundError(
        f"找不到指定的 {task_type} conversion 任务",
        details={"task_id": getattr(task, "task_id", None)},
    )
