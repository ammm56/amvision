"""WorkflowTriggerSource route 服务装配。"""

from __future__ import annotations

from fastapi import Request

from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.application.errors import (
    PermissionDeniedError,
    ServiceConfigurationError,
)
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from backend.service.application.workflows.trigger_sources import (
    WorkflowTriggerSourceService,
)
from backend.service.application.workflows.trigger_sources.trigger_source_supervisor import (
    TriggerSourceSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


def build_trigger_source_service(request: Request) -> WorkflowTriggerSourceService:
    """基于 application.state 构建 WorkflowTriggerSourceService。"""

    return WorkflowTriggerSourceService(
        session_factory=require_session_factory(request),
        trigger_source_supervisor=read_trigger_source_supervisor(request),
    )


def build_workflow_json_service_from_request(request: Request) -> LocalWorkflowJsonService:
    """基于 application.state 构建 workflow 图编排文件服务。"""

    return LocalWorkflowJsonService(
        dataset_storage=require_dataset_storage(request),
        node_catalog_registry=require_node_catalog_registry(request),
    )


def require_session_factory(request: Request) -> SessionFactory:
    """从 application.state 中读取 SessionFactory。"""

    session_factory = getattr(request.app.state, "session_factory", None)
    if not isinstance(session_factory, SessionFactory):
        raise ServiceConfigurationError("当前服务尚未完成 session_factory 装配")
    return session_factory


def read_trigger_source_supervisor(request: Request) -> TriggerSourceSupervisor | None:
    """从 application.state 中读取 TriggerSourceSupervisor。"""

    supervisor = getattr(request.app.state, "trigger_source_supervisor", None)
    if supervisor is None:
        return None
    if not isinstance(supervisor, TriggerSourceSupervisor):
        raise ServiceConfigurationError("当前服务 trigger_source_supervisor 装配无效")
    return supervisor


def require_dataset_storage(request: Request) -> LocalDatasetStorage:
    """从 application.state 中读取 LocalDatasetStorage。"""

    dataset_storage = getattr(request.app.state, "dataset_storage", None)
    if not isinstance(dataset_storage, LocalDatasetStorage):
        raise ServiceConfigurationError("当前服务尚未完成 dataset_storage 装配")
    return dataset_storage


def require_node_catalog_registry(request: Request) -> NodeCatalogRegistry:
    """从 application.state 中读取 NodeCatalogRegistry。"""

    node_catalog_registry = getattr(request.app.state, "node_catalog_registry", None)
    if not isinstance(node_catalog_registry, NodeCatalogRegistry):
        raise ServiceConfigurationError("当前服务尚未完成 node_catalog_registry 装配")
    return node_catalog_registry


def ensure_project_visible(
    *, principal: AuthenticatedPrincipal, project_id: str
) -> None:
    """校验当前主体是否可访问指定 Project。"""

    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": project_id},
        )

