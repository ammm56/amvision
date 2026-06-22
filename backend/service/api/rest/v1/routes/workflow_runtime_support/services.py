"""workflow runtime 路由服务装配。"""

from __future__ import annotations

from fastapi import Request

from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.application.deployments import PublishedInferenceGateway
from backend.service.application.errors import PermissionDeniedError, ServiceConfigurationError
from backend.service.application.local_buffers import LocalBufferBrokerEventChannel, LocalBufferBrokerProcessSupervisor
from backend.service.application.workflows.preview_run_manager import WorkflowPreviewRunManager
from backend.service.application.workflows.runtime_service import WorkflowRuntimeService
from backend.service.application.workflows.worker.manager import WorkflowRuntimeWorkerManager
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import BackendServiceSettings


def build_workflow_runtime_service(
    request: Request,
    *,
    include_local_buffer_broker_event_channel: bool = False,
) -> WorkflowRuntimeService:
    """基于 application.state 构建 workflow runtime 控制面服务。"""

    return WorkflowRuntimeService(
        settings=require_backend_service_settings(request),
        session_factory=require_session_factory(request),
        dataset_storage=require_dataset_storage(request),
        node_catalog_registry=require_node_catalog_registry(request),
        worker_manager=require_workflow_runtime_worker_manager(request),
        preview_run_manager=read_workflow_preview_run_manager(request),
        local_buffer_broker_event_channel=(
            read_local_buffer_broker_event_channel(request)
            if include_local_buffer_broker_event_channel
            else None
        ),
        published_inference_gateway=read_published_inference_gateway(request),
    )


def require_backend_service_settings(request: Request) -> BackendServiceSettings:
    """从 application.state 中读取 BackendServiceSettings。"""

    settings = getattr(request.app.state, "backend_service_settings", None)
    if not isinstance(settings, BackendServiceSettings):
        raise ServiceConfigurationError("当前服务尚未完成 backend_service_settings 装配")
    return settings


def require_session_factory(request: Request) -> SessionFactory:
    """从 application.state 中读取 SessionFactory。"""

    session_factory = getattr(request.app.state, "session_factory", None)
    if not isinstance(session_factory, SessionFactory):
        raise ServiceConfigurationError("当前服务尚未完成 session_factory 装配")
    return session_factory


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


def require_workflow_runtime_worker_manager(request: Request) -> WorkflowRuntimeWorkerManager:
    """从 application.state 中读取 WorkflowRuntimeWorkerManager。"""

    worker_manager = getattr(request.app.state, "workflow_runtime_worker_manager", None)
    if not isinstance(worker_manager, WorkflowRuntimeWorkerManager):
        raise ServiceConfigurationError("当前服务尚未完成 workflow_runtime_worker_manager 装配")
    return worker_manager


def read_workflow_preview_run_manager(request: Request) -> WorkflowPreviewRunManager | None:
    """从 application.state 中读取 WorkflowPreviewRunManager。"""

    preview_run_manager = getattr(request.app.state, "workflow_preview_run_manager", None)
    if preview_run_manager is None:
        return None
    if not isinstance(preview_run_manager, WorkflowPreviewRunManager):
        raise ServiceConfigurationError("当前服务 workflow_preview_run_manager 装配无效")
    return preview_run_manager


def read_local_buffer_broker_event_channel(request: Request) -> LocalBufferBrokerEventChannel | None:
    """从 application.state 中读取 LocalBufferBroker 事件通道。"""

    supervisor = getattr(request.app.state, "local_buffer_broker_supervisor", None)
    if supervisor is None:
        return None
    if not isinstance(supervisor, LocalBufferBrokerProcessSupervisor):
        raise ServiceConfigurationError("当前服务 local_buffer_broker_supervisor 装配无效")
    return supervisor.get_event_channel()


def read_published_inference_gateway(request: Request) -> PublishedInferenceGateway | None:
    """从 application.state 中读取父进程 PublishedInferenceGateway。"""

    gateway = getattr(request.app.state, "published_inference_gateway", None)
    if gateway is None:
        return None
    if not callable(getattr(gateway, "infer", None)):
        raise ServiceConfigurationError("当前服务 published_inference_gateway 装配无效")
    return gateway


def ensure_project_visible(*, principal: AuthenticatedPrincipal, project_id: str) -> None:
    """校验当前主体是否可访问指定 Project。"""

    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": project_id},
        )


def build_workflow_json_service_from_request(request: Request) -> LocalWorkflowJsonService:
    """基于 application.state 构建 workflow 图编排文件服务。"""

    return LocalWorkflowJsonService(
        dataset_storage=require_dataset_storage(request),
        node_catalog_registry=require_node_catalog_registry(request),
    )


def with_created_by(metadata: dict[str, object], created_by: str) -> dict[str, object]:
    """把 created_by 写入执行元数据。"""

    payload = dict(metadata)
    payload.setdefault("created_by", created_by)
    return payload
