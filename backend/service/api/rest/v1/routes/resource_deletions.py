"""版本化资源删除受理、进度及重试 API。"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.service.api.deps.auth import (
    AuthenticatedPrincipal,
    require_principal,
    require_scopes,
)
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import (
    PermissionDeniedError,
    ResourceNotFoundError,
)
from backend.service.application.project_access import require_explicit_project_access
from backend.service.application.resource_deletion import ResourceDeletionService
from backend.service.domain.resource_deletion import ResourceDeletionOperation
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.infrastructure.queue.local_file import LocalFileQueueBackend


class ResourceDeletionRequest(BaseModel):
    """仅接受对象身份，禁止客户端指定删除路径或表。"""

    model_config = ConfigDict(extra="forbid")
    format_id: Literal["amvision.resource-deletion-request.v1"] = (
        "amvision.resource-deletion-request.v1"
    )
    kind: Literal[
        "task", "dataset", "dataset-version", "dataset-import", "dataset-export"
    ]
    resource_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)


class ResourceDeletionStatus(BaseModel):
    """删除进度不公开内部文件清单。"""

    operation_id: str
    project_id: str
    resource_kind: str
    resource_id: str
    state: Literal["prepared", "committed", "completed", "rolled_back"]
    error: str | None = None


resource_deletions_router = APIRouter(
    prefix="/resource-deletions", tags=["resource-deletions"]
)


def _authorize(principal: AuthenticatedPrincipal, kind: str, project_id: str) -> None:
    """删除状态和重试继承目标对象的权限与 Project 可见性。"""
    scope = (
        "datasets:write"
        if kind.startswith("dataset")
        else "tasks:write"
        if kind == "task"
        else "models:write"
    )
    require_scopes(scope)(principal)
    require_explicit_project_access(
        visible_project_ids=principal.project_ids, project_id=project_id
    )


def _status(operation: ResourceDeletionOperation) -> ResourceDeletionStatus:
    """将权威状态转换为简洁公开响应。"""
    return ResourceDeletionStatus(
        operation_id=operation.plan.operation_id,
        project_id=operation.plan.project_id,
        resource_kind=operation.plan.target.kind,
        resource_id=operation.plan.target.resource_id,
        state=operation.state,
        error=operation.error,
    )


@resource_deletions_router.post(
    "", status_code=202, response_model=ResourceDeletionStatus
)
def submit_resource_deletion(
    body: ResourceDeletionRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> ResourceDeletionStatus:
    """提交数据库删除，物理清理由现有 dataset-export Worker 中的清理消费者完成。"""
    _authorize(principal, body.kind, body.project_id)
    operation_id = ResourceDeletionService(
        session_factory=factory, dataset_storage=storage, queue_backend=queue
    ).delete(
        kind=body.kind,
        resource_id=body.resource_id,
        project_id=body.project_id,
        asynchronous=True,
    )
    return get_resource_deletion(operation_id, principal, factory)


@resource_deletions_router.get("", response_model=list[ResourceDeletionStatus])
def list_resource_deletions(
    project_id: Annotated[str, Query(min_length=1)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> list[ResourceDeletionStatus]:
    """列出当前 Project 尚未清理完成的操作，刷新页面后仍可重试。"""
    require_explicit_project_access(
        visible_project_ids=principal.project_ids, project_id=project_id
    )
    unit = SqlAlchemyUnitOfWork(factory.create_session())
    try:
        operations = unit.resource_deletions.list_pending()
    finally:
        unit.close()
    visible = []
    for operation in operations:
        if operation.plan.project_id != project_id:
            continue
        try:
            _authorize(principal, operation.plan.target.kind, project_id)
        except PermissionDeniedError:
            continue
        visible.append(_status(operation))
    return visible


@resource_deletions_router.get("/{operation_id}", response_model=ResourceDeletionStatus)
def get_resource_deletion(
    operation_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> ResourceDeletionStatus:
    """查询准确阶段，完成回执只短期保留。"""
    unit = SqlAlchemyUnitOfWork(factory.create_session())
    try:
        operation = unit.resource_deletions.get(operation_id)
    finally:
        unit.close()
    if operation is None:
        raise ResourceNotFoundError("删除操作不存在或完成回执已过期")
    _authorize(principal, operation.plan.target.kind, operation.plan.project_id)
    return _status(operation)


@resource_deletions_router.post("/{operation_id}/retry", status_code=204)
def retry_resource_deletion(
    operation_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> Response:
    """显式重试尚未完成的清理，成功前不会返回 204。"""
    get_resource_deletion(operation_id, principal, factory)
    ResourceDeletionService(
        session_factory=factory, dataset_storage=storage, queue_backend=queue
    ).retry(operation_id)
    return Response(status_code=204)
