"""通用 task inference 可见性和列表查询工具。"""

from __future__ import annotations

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.api.rest.v1.routes.task_inference.responses import (
    InferenceTaskDetailResponse,
    InferenceTaskResultResponse,
    InferenceTaskSummaryResponse,
    build_inference_task_detail_response,
    build_inference_task_summary_response,
    read_inference_task_result,
)
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


def list_inference_task_summaries(
    *,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    task_kind: str,
    project_id: str | None,
    state: str | None,
    created_by: str | None,
    deployment_instance_id: str | None,
    limit: int,
) -> list[InferenceTaskSummaryResponse]:
    """按公开筛选条件列出 inference task 摘要。"""

    visible_project_ids = resolve_visible_project_ids(
        principal=principal,
        project_id=project_id,
    )
    service = SqlAlchemyTaskService(session_factory)
    matched_tasks = []
    for current_project_id in visible_project_ids:
        matched_tasks.extend(
            service.list_tasks(
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
        if matches_deployment_instance(task=task, deployment_instance_id=deployment_instance_id)
    ]
    visible_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
    return [build_inference_task_summary_response(task) for task in visible_tasks[:limit]]


def get_inference_task_detail_response(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    session_factory: SessionFactory,
    task_kind: str,
    resource_label: str,
    include_events: bool,
) -> InferenceTaskDetailResponse:
    """按任务 id 返回 inference task 详情响应。"""

    task_detail = require_visible_inference_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        task_kind=task_kind,
        resource_label=resource_label,
        include_events=include_events,
    )
    return build_inference_task_detail_response(task_detail.task, tuple(task_detail.events))


def get_inference_task_result_response(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    task_kind: str,
    resource_label: str,
) -> InferenceTaskResultResponse:
    """按任务 id 返回 inference task 结果响应。"""

    task_detail = require_visible_inference_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        task_kind=task_kind,
        resource_label=resource_label,
        include_events=False,
    )
    return read_inference_task_result(
        task_state=task_detail.task.state,
        result_payload=dict(task_detail.task.result),
        dataset_storage=dataset_storage,
    )


def require_visible_inference_task(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    session_factory: SessionFactory,
    task_kind: str,
    resource_label: str,
    include_events: bool,
):
    """读取并校验当前主体可见的 inference task。"""

    service = SqlAlchemyTaskService(session_factory)
    task_detail = service.get_task(task_id, include_events=include_events)
    if principal.project_ids and task_detail.task.project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            f"找不到指定的{resource_label}",
            details={"task_id": task_id},
        )
    if task_detail.task.task_kind != task_kind:
        raise ResourceNotFoundError(
            f"找不到指定的{resource_label}",
            details={"task_id": task_id},
        )
    return task_detail


def resolve_visible_project_ids(
    *,
    principal: AuthenticatedPrincipal,
    project_id: str | None,
) -> list[str]:
    """解析当前查询允许访问的项目列表。"""

    visible_project_ids: list[str] = []
    if project_id is not None:
        if principal.project_ids and project_id not in principal.project_ids:
            raise PermissionDeniedError(
                "当前主体无权访问该 Project",
                details={"project_id": project_id},
            )
        visible_project_ids.append(project_id)
    elif principal.project_ids:
        visible_project_ids.extend(principal.project_ids)
    else:
        raise InvalidRequestError("查询推理任务列表时必须提供 project_id")
    return visible_project_ids


def matches_deployment_instance(*, task: object, deployment_instance_id: str | None) -> bool:
    """判断推理任务是否满足 deployment_instance_id 过滤条件。"""

    if deployment_instance_id is None:
        return True
    task_spec = dict(task.task_spec)
    return task_spec.get("deployment_instance_id") == deployment_instance_id
