"""detection DeploymentInstance 基础管理路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.detection_deployments.responses import (
    DetectionDeploymentInstanceResponse,
    build_detection_deployment_instance_response,
)
from backend.service.api.rest.v1.routes.detection_deployments.schemas import (
    DetectionDeploymentInstanceCreateRequestBody,
)
from backend.service.api.rest.v1.routes.detection_deployments.services import (
    create_detection_deployment_view,
    delete_visible_detection_deployment_instance,
    get_visible_detection_deployment_view,
    list_visible_detection_deployment_views,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


detection_deployment_instances_router = APIRouter()


@detection_deployment_instances_router.post(
    "/detection/deployment-instances",
    response_model=DetectionDeploymentInstanceResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_detection_deployment_instance(
    body: DetectionDeploymentInstanceCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionDeploymentInstanceResponse:
    """创建一个 detection DeploymentInstance。"""

    view = create_detection_deployment_view(
        body=body,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    return build_detection_deployment_instance_response(view)


@detection_deployment_instances_router.get(
    "/detection/deployment-instances",
    response_model=list[DetectionDeploymentInstanceResponse],
)
def list_detection_deployment_instances(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
    model_type: Annotated[str | None, Query(description="模型分类")] = None,
    model_version_id: Annotated[str | None, Query(description="绑定的 ModelVersion id")] = None,
    model_build_id: Annotated[str | None, Query(description="绑定的 ModelBuild id")] = None,
    status_filter: Annotated[str | None, Query(alias="status", description="实例状态")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="最大返回数量")] = 100,
) -> list[DetectionDeploymentInstanceResponse]:
    """列出当前主体可见的 detection DeploymentInstance。"""

    views = list_visible_detection_deployment_views(
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        project_id=project_id,
        model_type=model_type,
        model_version_id=model_version_id,
        model_build_id=model_build_id,
        status_filter=status_filter,
        limit=limit,
    )
    return [build_detection_deployment_instance_response(item) for item in views]


@detection_deployment_instances_router.get(
    "/detection/deployment-instances/{deployment_instance_id}",
    response_model=DetectionDeploymentInstanceResponse,
)
def get_detection_deployment_instance(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionDeploymentInstanceResponse:
    """读取一个 detection DeploymentInstance。"""

    view = get_visible_detection_deployment_view(
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        deployment_instance_id=deployment_instance_id,
    )
    return build_detection_deployment_instance_response(view)


@detection_deployment_instances_router.delete(
    "/detection/deployment-instances/{deployment_instance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_detection_deployment_instance(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> None:
    """删除一个 detection DeploymentInstance。"""

    delete_visible_detection_deployment_instance(
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        deployment_instance_id=deployment_instance_id,
    )
