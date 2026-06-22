"""detection deployment 事件读取路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.detection_deployments.responses import (
    DetectionDeploymentProcessEventResponse,
    build_detection_deployment_process_event_response,
)
from backend.service.api.rest.v1.routes.detection_deployments.services import (
    get_visible_detection_deployment_view,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.deployment.deployment_event_source import DetectionDeploymentEventSource
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


detection_deployment_events_router = APIRouter()


@detection_deployment_events_router.get(
    "/detection/deployment-instances/{deployment_instance_id}/events",
    response_model=list[DetectionDeploymentProcessEventResponse],
)
def get_detection_deployment_events(
    deployment_instance_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    after_sequence: Annotated[int | None, Query(description="只返回 sequence 大于该值的事件", ge=0)] = None,
    limit: Annotated[int | None, Query(description="最多返回多少条事件", ge=1, le=500)] = None,
    runtime_mode: Annotated[str | None, Query(description="按 sync 或 async 通道过滤事件")] = None,
) -> list[DetectionDeploymentProcessEventResponse]:
    """读取一条 detection DeploymentInstance 的事件列表。"""

    get_visible_detection_deployment_view(
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        deployment_instance_id=deployment_instance_id,
    )
    if runtime_mode is not None and runtime_mode not in {"sync", "async"}:
        raise InvalidRequestError(
            "runtime_mode 仅支持 sync 或 async",
            details={"runtime_mode": runtime_mode},
        )
    event_source = DetectionDeploymentEventSource(
        dataset_storage_root_dir=str(dataset_storage.root_dir),
    )
    events = event_source.list_events(
        deployment_instance_id,
        after_sequence=after_sequence,
        runtime_mode=runtime_mode,
        limit=limit,
    )
    return [build_detection_deployment_process_event_response(item) for item in events]
