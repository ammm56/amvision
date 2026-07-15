"""detection deployment 路由 service helper。"""

from __future__ import annotations

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.api.rest.v1.routes.task_deployments.runtime_controls import (
    delete_stopped_deployment_instance,
)
from backend.service.api.rest.v1.routes.detection_deployments.schemas import (
    DetectionDeploymentInstanceCreateRequestBody,
)
from backend.service.application.deployments.detection_deployment_service import (
    DetectionDeploymentInstanceCreateRequest,
    DetectionDeploymentInstanceView,
    SqlAlchemyDetectionDeploymentService,
)
from backend.service.application.errors import PermissionDeniedError, ResourceNotFoundError
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


def create_detection_deployment_view(
    *,
    body: DetectionDeploymentInstanceCreateRequestBody,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> DetectionDeploymentInstanceView:
    """创建 detection DeploymentInstance 并返回服务视图。"""

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": body.project_id},
        )
    service = build_detection_deployment_service(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    return service.create_deployment_instance(
        DetectionDeploymentInstanceCreateRequest(
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


def list_visible_detection_deployment_views(
    *,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    project_id: str | None,
    model_type: str | None,
    model_version_id: str | None,
    model_build_id: str | None,
    status_filter: str | None,
    limit: int,
) -> list[DetectionDeploymentInstanceView]:
    """按可见 Project 范围列出 detection DeploymentInstance。"""

    resolved_project_id = resolve_detection_deployment_project_id(
        principal=principal,
        project_id=project_id,
    )
    service = build_detection_deployment_service(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    return service.list_deployment_instances(
        project_id=resolved_project_id,
        model_type=model_type,
        model_version_id=model_version_id,
        model_build_id=model_build_id,
        status=status_filter,
        limit=limit,
    )


def get_visible_detection_deployment_view(
    *,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    deployment_instance_id: str,
) -> DetectionDeploymentInstanceView:
    """读取并校验当前主体可见的 detection DeploymentInstance。"""

    service = build_detection_deployment_service(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    view = service.get_deployment_instance(deployment_instance_id)
    ensure_detection_deployment_visible(principal=principal, view=view)
    return view


def delete_visible_detection_deployment_instance(
    *,
    principal: AuthenticatedPrincipal,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    deployment_instance_id: str,
    sync_supervisor: DeploymentProcessSupervisor,
    async_supervisor: DeploymentProcessSupervisor,
) -> None:
    """删除当前主体可见且已经停止的 detection DeploymentInstance。"""

    service = build_detection_deployment_service(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    delete_stopped_deployment_instance(
        deployment_instance_id=deployment_instance_id,
        principal=principal,
        deployment_service=service,
        sync_supervisor=sync_supervisor,
        async_supervisor=async_supervisor,
    )


def ensure_detection_deployment_visible(
    *,
    principal: AuthenticatedPrincipal,
    view: DetectionDeploymentInstanceView,
) -> None:
    """校验当前主体是否可以访问指定 detection DeploymentInstance。"""

    if principal.project_ids and view.project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的 DeploymentInstance",
            details={"deployment_instance_id": view.deployment_instance_id},
        )


def resolve_detection_deployment_project_id(
    *,
    principal: AuthenticatedPrincipal,
    project_id: str | None,
) -> str:
    """根据主体权限和查询条件解析 Project id。"""

    visible_project_ids = tuple(principal.project_ids or ())
    resolved_project_id = project_id.strip() if isinstance(project_id, str) and project_id.strip() else None
    if resolved_project_id is None:
        if not visible_project_ids:
            raise PermissionDeniedError("当前主体缺少可访问 Project 范围")
        return visible_project_ids[0]
    if visible_project_ids and resolved_project_id not in visible_project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": resolved_project_id},
        )
    return resolved_project_id


def build_detection_deployment_service(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> SqlAlchemyDetectionDeploymentService:
    """创建 detection deployment 应用服务。"""

    return SqlAlchemyDetectionDeploymentService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
