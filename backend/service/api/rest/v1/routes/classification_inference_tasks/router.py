"""classification inference tasks REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.classification_deployment_process_supervisor import (
    get_classification_async_deployment_process_supervisor,
    get_classification_async_inference_gateway_dispatcher_registry,
    get_classification_sync_deployment_process_supervisor,
)
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.classification_inference_tasks.responses import (
    ClassificationInferenceTaskSubmissionResponse,
)
from backend.service.api.rest.v1.routes.classification_inference_tasks.services import (
    get_classification_inference_task_detail_response,
    get_classification_inference_task_result_response,
    infer_classification_deployment_instance_from_request,
    list_classification_inference_task_summaries,
    submit_classification_inference_task_from_request,
)
from backend.service.api.rest.v1.routes.task_inference.responses import (
    InferenceTaskDetailResponse,
    InferenceTaskResultResponse,
    InferenceTaskSummaryResponse,
)
from backend.service.application.models.inference.classification_async_inference_gateway import (
    ClassificationAsyncInferenceGatewayDispatcherRegistry,
)
from backend.service.application.runtime.deployment.deployment_process_supervisor import (
    DeploymentProcessSupervisor,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


classification_inference_tasks_router = APIRouter(prefix="/models", tags=["models"])


@classification_inference_tasks_router.post(
    "/classification/inference-tasks",
    response_model=ClassificationInferenceTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_classification_inference_task(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    deployment_process_supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_classification_async_deployment_process_supervisor)],
    gateway_dispatcher_registry: Annotated[ClassificationAsyncInferenceGatewayDispatcherRegistry, Depends(get_classification_async_inference_gateway_dispatcher_registry)],
) -> ClassificationInferenceTaskSubmissionResponse:
    """创建一条 classification 异步推理任务。"""

    return await submit_classification_inference_task_from_request(
        request=request,
        principal=principal,
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
        deployment_process_supervisor=deployment_process_supervisor,
        gateway_dispatcher_registry=gateway_dispatcher_registry,
    )


@classification_inference_tasks_router.post(
    "/classification/deployment-instances/{deployment_instance_id}/infer",
    response_model=dict[str, object],
)
async def infer_classification_deployment_instance(
    deployment_instance_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    deployment_process_supervisor: Annotated[DeploymentProcessSupervisor, Depends(get_classification_sync_deployment_process_supervisor)],
) -> dict[str, object]:
    """直接执行一次同步 classification 推理并返回结果。"""

    return await infer_classification_deployment_instance_from_request(
        deployment_instance_id=deployment_instance_id,
        request=request,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        deployment_process_supervisor=deployment_process_supervisor,
    )


@classification_inference_tasks_router.get(
    "/classification/inference-tasks",
    response_model=list[InferenceTaskSummaryResponse],
)
def list_classification_inference_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
    state: Annotated[str | None, Query(description="任务状态")] = None,
    created_by: Annotated[str | None, Query(description="提交主体 id")] = None,
    deployment_instance_id: Annotated[str | None, Query(description="DeploymentInstance id")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
) -> list[InferenceTaskSummaryResponse]:
    """按公开筛选条件列出 classification 推理任务。"""

    return list_classification_inference_task_summaries(
        principal=principal,
        session_factory=session_factory,
        project_id=project_id,
        state=state,
        created_by=created_by,
        deployment_instance_id=deployment_instance_id,
        limit=limit,
    )


@classification_inference_tasks_router.get(
    "/classification/inference-tasks/{task_id}",
    response_model=InferenceTaskDetailResponse,
)
def get_classification_inference_task_detail(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    include_events: Annotated[bool, Query(description="是否返回事件列表")] = False,
) -> InferenceTaskDetailResponse:
    """按任务 id 返回 classification 推理任务详情。"""

    return get_classification_inference_task_detail_response(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=include_events,
    )


@classification_inference_tasks_router.get(
    "/classification/inference-tasks/{task_id}/result",
    response_model=InferenceTaskResultResponse,
)
def get_classification_inference_task_result(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> InferenceTaskResultResponse:
    """按任务 id 返回当前 classification 推理结果。"""

    return get_classification_inference_task_result_response(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
