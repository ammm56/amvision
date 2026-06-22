"""non-detection deployment 路由工厂。"""

from dataclasses import dataclass
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, Query, status

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.task_deployments.runtime_controls import (
    DeploymentProcessStatusResponse,
    DeploymentRuntimeHealthResponse,
    run_deployment_process_health_action,
    run_deployment_process_status_action,
)
from backend.service.application.errors import PermissionDeniedError
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class TaskDeploymentRouteConfig:
    """描述一个 task deployment 路由组需要的差异化装配项。"""

    route_segment: str
    create_body_model: type[Any]
    instance_response_model: type[Any]
    service_cls: type[Any]
    create_request_cls: type[Any]
    response_builder: Callable[[Any], Any]
    sync_supervisor_dependency: Callable[..., DeploymentProcessSupervisor]
    async_supervisor_dependency: Callable[..., DeploymentProcessSupervisor]
    async_gateway_dispatcher_registry_dependency: Callable[..., Any]


def create_task_deployment_router(config: TaskDeploymentRouteConfig) -> APIRouter:
    """创建 classification / segmentation / pose / OBB 共用 deployment 路由。"""

    router = APIRouter(prefix="/models", tags=["models"])

    def build_service(
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
    ) -> Any:
        """构建当前 task 的 deployment service。"""

        return config.service_cls(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        )

    def check_project_visible(principal: AuthenticatedPrincipal, project_id: str) -> None:
        """校验当前主体是否可以访问指定 Project。"""

        if principal.project_ids and project_id not in principal.project_ids:
            raise PermissionDeniedError("当前主体无权访问该 Project", details={"project_id": project_id})

    def build_current_service(
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
    ) -> Any:
        """按 endpoint dependency 构建当前 task deployment service。"""

        return build_service(session_factory=session_factory, dataset_storage=dataset_storage)

    @router.post(
        f"/{config.route_segment}/deployment-instances",
        response_model=config.instance_response_model,
        status_code=status.HTTP_201_CREATED,
    )
    def create_deployment_instance(
        body: config.create_body_model,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    ) -> Any:
        """创建当前 task 的 DeploymentInstance。"""

        check_project_visible(principal, body.project_id)
        service = build_current_service(session_factory, dataset_storage)
        view = service.create_deployment_instance(
            config.create_request_cls(
                project_id=body.project_id,
                model_type=body.model_type,
                model_version_id=body.model_version_id,
                model_build_id=body.model_build_id,
                runtime_profile_id=body.runtime_profile_id,
                runtime_backend=body.runtime_backend,
                runtime_precision=body.runtime_precision,
                device_name=body.device_name,
                instance_count=body.instance_count,
                display_name=body.display_name,
                metadata=dict(body.metadata),
            ),
            created_by=principal.principal_id,
        )
        return config.response_builder(view)

    @router.get(
        f"/{config.route_segment}/deployment-instances",
        response_model=list[config.instance_response_model],
    )
    def list_deployment_instances(
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
        project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
        model_type: Annotated[str | None, Query(description="模型类型")] = None,
        model_version_id: Annotated[str | None, Query(description="绑定的 ModelVersion id")] = None,
        model_build_id: Annotated[str | None, Query(description="绑定的 ModelBuild id")] = None,
        status_filter: Annotated[str | None, Query(alias="status", description="实例状态")] = None,
        limit: Annotated[int, Query(ge=1, le=200, description="最大返回数量")] = 100,
    ) -> list[Any]:
        """列出当前 task 的 DeploymentInstance。"""

        if project_id is not None:
            check_project_visible(principal, project_id)
        service = build_current_service(session_factory, dataset_storage)
        views = service.list_deployment_instances(
            project_id=project_id or "",
            model_type=model_type,
            model_version_id=model_version_id,
            model_build_id=model_build_id,
            status=status_filter,
            limit=limit,
        )
        return [config.response_builder(view) for view in views]

    @router.get(
        f"/{config.route_segment}/deployment-instances/{{deployment_instance_id}}",
        response_model=config.instance_response_model,
    )
    def get_deployment_instance(
        deployment_instance_id: str,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    ) -> Any:
        """读取当前 task 的 DeploymentInstance。"""

        service = build_current_service(session_factory, dataset_storage)
        view = service.get_deployment_instance(deployment_instance_id)
        check_project_visible(principal, view.project_id)
        return config.response_builder(view)

    @router.post(
        f"/{config.route_segment}/deployment-instances/{{deployment_instance_id}}/sync/start",
        response_model=DeploymentProcessStatusResponse,
    )
    def start_sync_deployment(
        deployment_instance_id: str,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
        supervisor: Annotated[DeploymentProcessSupervisor, Depends(config.sync_supervisor_dependency)],
    ) -> DeploymentProcessStatusResponse:
        """启动当前 task 的 sync deployment process。"""

        return run_deployment_process_status_action(
            deployment_instance_id=deployment_instance_id,
            principal=principal,
            deployment_service=build_current_service(session_factory, dataset_storage),
            supervisor=supervisor,
            runtime_mode="sync",
            action="start",
        )

    @router.post(
        f"/{config.route_segment}/deployment-instances/{{deployment_instance_id}}/sync/stop",
        response_model=DeploymentProcessStatusResponse,
    )
    def stop_sync_deployment(
        deployment_instance_id: str,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
        supervisor: Annotated[DeploymentProcessSupervisor, Depends(config.sync_supervisor_dependency)],
    ) -> DeploymentProcessStatusResponse:
        """停止当前 task 的 sync deployment process。"""

        return run_deployment_process_status_action(
            deployment_instance_id=deployment_instance_id,
            principal=principal,
            deployment_service=build_current_service(session_factory, dataset_storage),
            supervisor=supervisor,
            runtime_mode="sync",
            action="stop",
        )

    @router.get(
        f"/{config.route_segment}/deployment-instances/{{deployment_instance_id}}/sync/status",
        response_model=DeploymentProcessStatusResponse,
    )
    def get_sync_deployment_status(
        deployment_instance_id: str,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
        supervisor: Annotated[DeploymentProcessSupervisor, Depends(config.sync_supervisor_dependency)],
    ) -> DeploymentProcessStatusResponse:
        """读取当前 task 的 sync deployment process 状态。"""

        return run_deployment_process_status_action(
            deployment_instance_id=deployment_instance_id,
            principal=principal,
            deployment_service=build_current_service(session_factory, dataset_storage),
            supervisor=supervisor,
            runtime_mode="sync",
            action="status",
        )

    @router.post(
        f"/{config.route_segment}/deployment-instances/{{deployment_instance_id}}/sync/warmup",
        response_model=DeploymentRuntimeHealthResponse,
    )
    def warmup_sync_deployment(
        deployment_instance_id: str,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
        supervisor: Annotated[DeploymentProcessSupervisor, Depends(config.sync_supervisor_dependency)],
    ) -> DeploymentRuntimeHealthResponse:
        """预热当前 task 的 sync deployment process。"""

        return run_deployment_process_health_action(
            deployment_instance_id=deployment_instance_id,
            principal=principal,
            deployment_service=build_current_service(session_factory, dataset_storage),
            supervisor=supervisor,
            runtime_mode="sync",
            action="warmup",
        )

    @router.get(
        f"/{config.route_segment}/deployment-instances/{{deployment_instance_id}}/sync/health",
        response_model=DeploymentRuntimeHealthResponse,
    )
    def get_sync_deployment_health(
        deployment_instance_id: str,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
        supervisor: Annotated[DeploymentProcessSupervisor, Depends(config.sync_supervisor_dependency)],
    ) -> DeploymentRuntimeHealthResponse:
        """读取当前 task 的 sync deployment runtime 健康状态。"""

        return run_deployment_process_health_action(
            deployment_instance_id=deployment_instance_id,
            principal=principal,
            deployment_service=build_current_service(session_factory, dataset_storage),
            supervisor=supervisor,
            runtime_mode="sync",
            action="health",
        )

    @router.post(
        f"/{config.route_segment}/deployment-instances/{{deployment_instance_id}}/sync/reset",
        response_model=DeploymentRuntimeHealthResponse,
    )
    def reset_sync_deployment(
        deployment_instance_id: str,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
        supervisor: Annotated[DeploymentProcessSupervisor, Depends(config.sync_supervisor_dependency)],
    ) -> DeploymentRuntimeHealthResponse:
        """重置当前 task 的 sync deployment runtime。"""

        return run_deployment_process_health_action(
            deployment_instance_id=deployment_instance_id,
            principal=principal,
            deployment_service=build_current_service(session_factory, dataset_storage),
            supervisor=supervisor,
            runtime_mode="sync",
            action="reset",
        )

    @router.post(
        f"/{config.route_segment}/deployment-instances/{{deployment_instance_id}}/async/start",
        response_model=DeploymentProcessStatusResponse,
    )
    def start_async_deployment(
        deployment_instance_id: str,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
        supervisor: Annotated[DeploymentProcessSupervisor, Depends(config.async_supervisor_dependency)],
        gateway_dispatcher_registry: Annotated[Any, Depends(config.async_gateway_dispatcher_registry_dependency)],
    ) -> DeploymentProcessStatusResponse:
        """启动当前 task 的 async deployment process。"""

        return run_deployment_process_status_action(
            deployment_instance_id=deployment_instance_id,
            principal=principal,
            deployment_service=build_current_service(session_factory, dataset_storage),
            supervisor=supervisor,
            gateway_dispatcher_registry=gateway_dispatcher_registry,
            runtime_mode="async",
            action="start",
        )

    @router.post(
        f"/{config.route_segment}/deployment-instances/{{deployment_instance_id}}/async/stop",
        response_model=DeploymentProcessStatusResponse,
    )
    def stop_async_deployment(
        deployment_instance_id: str,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
        supervisor: Annotated[DeploymentProcessSupervisor, Depends(config.async_supervisor_dependency)],
        gateway_dispatcher_registry: Annotated[Any, Depends(config.async_gateway_dispatcher_registry_dependency)],
    ) -> DeploymentProcessStatusResponse:
        """停止当前 task 的 async deployment process。"""

        return run_deployment_process_status_action(
            deployment_instance_id=deployment_instance_id,
            principal=principal,
            deployment_service=build_current_service(session_factory, dataset_storage),
            supervisor=supervisor,
            gateway_dispatcher_registry=gateway_dispatcher_registry,
            runtime_mode="async",
            action="stop",
        )

    @router.get(
        f"/{config.route_segment}/deployment-instances/{{deployment_instance_id}}/async/status",
        response_model=DeploymentProcessStatusResponse,
    )
    def get_async_deployment_status(
        deployment_instance_id: str,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
        supervisor: Annotated[DeploymentProcessSupervisor, Depends(config.async_supervisor_dependency)],
        gateway_dispatcher_registry: Annotated[Any, Depends(config.async_gateway_dispatcher_registry_dependency)],
    ) -> DeploymentProcessStatusResponse:
        """读取当前 task 的 async deployment process 状态。"""

        return run_deployment_process_status_action(
            deployment_instance_id=deployment_instance_id,
            principal=principal,
            deployment_service=build_current_service(session_factory, dataset_storage),
            supervisor=supervisor,
            gateway_dispatcher_registry=gateway_dispatcher_registry,
            runtime_mode="async",
            action="status",
        )

    @router.post(
        f"/{config.route_segment}/deployment-instances/{{deployment_instance_id}}/async/warmup",
        response_model=DeploymentRuntimeHealthResponse,
    )
    def warmup_async_deployment(
        deployment_instance_id: str,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
        supervisor: Annotated[DeploymentProcessSupervisor, Depends(config.async_supervisor_dependency)],
        gateway_dispatcher_registry: Annotated[Any, Depends(config.async_gateway_dispatcher_registry_dependency)],
    ) -> DeploymentRuntimeHealthResponse:
        """预热当前 task 的 async deployment process。"""

        return run_deployment_process_health_action(
            deployment_instance_id=deployment_instance_id,
            principal=principal,
            deployment_service=build_current_service(session_factory, dataset_storage),
            supervisor=supervisor,
            gateway_dispatcher_registry=gateway_dispatcher_registry,
            runtime_mode="async",
            action="warmup",
        )

    @router.get(
        f"/{config.route_segment}/deployment-instances/{{deployment_instance_id}}/async/health",
        response_model=DeploymentRuntimeHealthResponse,
    )
    def get_async_deployment_health(
        deployment_instance_id: str,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
        supervisor: Annotated[DeploymentProcessSupervisor, Depends(config.async_supervisor_dependency)],
        gateway_dispatcher_registry: Annotated[Any, Depends(config.async_gateway_dispatcher_registry_dependency)],
    ) -> DeploymentRuntimeHealthResponse:
        """读取当前 task 的 async deployment runtime 健康状态。"""

        return run_deployment_process_health_action(
            deployment_instance_id=deployment_instance_id,
            principal=principal,
            deployment_service=build_current_service(session_factory, dataset_storage),
            supervisor=supervisor,
            gateway_dispatcher_registry=gateway_dispatcher_registry,
            runtime_mode="async",
            action="health",
        )

    @router.post(
        f"/{config.route_segment}/deployment-instances/{{deployment_instance_id}}/async/reset",
        response_model=DeploymentRuntimeHealthResponse,
    )
    def reset_async_deployment(
        deployment_instance_id: str,
        principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
        session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
        dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
        supervisor: Annotated[DeploymentProcessSupervisor, Depends(config.async_supervisor_dependency)],
    ) -> DeploymentRuntimeHealthResponse:
        """重置当前 task 的 async deployment runtime。"""

        return run_deployment_process_health_action(
            deployment_instance_id=deployment_instance_id,
            principal=principal,
            deployment_service=build_current_service(session_factory, dataset_storage),
            supervisor=supervisor,
            runtime_mode="async",
            action="reset",
        )

    return router
