"""数据集及独立版本的完整删除入口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import ResourceNotFoundError
from backend.service.application.project_access import require_explicit_project_access
from backend.service.application.resource_deletion import ResourceDeletionService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.infrastructure.queue.local_file import LocalFileQueueBackend

dataset_deletion_router = APIRouter()


@dataset_deletion_router.delete("/versions/{dataset_version_id}", status_code=204)
def delete_dataset_version(
    dataset_version_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:write"))],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> Response:
    """删除版本、样本标注及其导入/导出，外部依赖阻止删除。"""
    unit = SqlAlchemyUnitOfWork(factory.create_session())
    try:
        version = unit.datasets.get_dataset_version(dataset_version_id)
    finally:
        unit.close()
    if version is None:
        raise ResourceNotFoundError("找不到指定数据集版本")
    require_explicit_project_access(visible_project_ids=principal.project_ids, project_id=version.project_id)
    ResourceDeletionService(session_factory=factory, dataset_storage=storage, queue_backend=queue).delete(kind="dataset-version", resource_id=dataset_version_id, project_id=version.project_id)
    return Response(status_code=204)


@dataset_deletion_router.delete("/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: str,
    project_id: Annotated[str, Query(min_length=1)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:write"))],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> Response:
    """删除数据集的全部所属版本及成功/失败导入、导出。"""
    require_explicit_project_access(visible_project_ids=principal.project_ids, project_id=project_id)
    ResourceDeletionService(session_factory=factory, dataset_storage=storage, queue_backend=queue).delete(kind="dataset", resource_id=dataset_id, project_id=project_id)
    return Response(status_code=204)
