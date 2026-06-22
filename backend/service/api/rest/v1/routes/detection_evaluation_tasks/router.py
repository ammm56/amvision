"""detection evaluation task REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.detection_evaluation_tasks.outputs import (
    DetectionEvaluationOutputFileSummaryResponse,
    DetectionEvaluationReportResponse,
)
from backend.service.api.rest.v1.routes.detection_evaluation_tasks.responses import (
    DetectionEvaluationTaskDetailResponse,
    DetectionEvaluationTaskSubmissionResponse,
    DetectionEvaluationTaskSummaryResponse,
)
from backend.service.api.rest.v1.routes.detection_evaluation_tasks.schemas import (
    DetectionEvaluationTaskCreateRequestBody,
)
from backend.service.api.rest.v1.routes.detection_evaluation_tasks.services import (
    create_detection_evaluation_task_response,
    get_detection_evaluation_task_detail_response,
    get_detection_evaluation_task_report_response,
    list_detection_evaluation_output_file_responses,
    list_detection_evaluation_task_responses,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


detection_evaluation_tasks_router = APIRouter(prefix="/models", tags=["models"])


@detection_evaluation_tasks_router.post(
    "/detection/evaluation-tasks",
    response_model=DetectionEvaluationTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_detection_evaluation_task(
    body: DetectionEvaluationTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read", "models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionEvaluationTaskSubmissionResponse:
    """创建一个用于数据集级回归验证的 detection evaluation task。"""

    return create_detection_evaluation_task_response(
        body=body,
        principal=principal,
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )


@detection_evaluation_tasks_router.get(
    "/detection/evaluation-tasks",
    response_model=list[DetectionEvaluationTaskSummaryResponse],
)
def list_detection_evaluation_tasks(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str | None, Query(description="所属 Project id")] = None,
    model_type: Annotated[str | None, Query(description="模型分类")] = None,
    state: Annotated[str | None, Query(description="任务状态")] = None,
    created_by: Annotated[str | None, Query(description="提交主体 id")] = None,
    dataset_export_id: Annotated[str | None, Query(description="评估输入使用的 DatasetExport id")] = None,
    dataset_export_manifest_key: Annotated[str | None, Query(description="评估输入使用的导出 manifest object key")] = None,
    model_version_id: Annotated[str | None, Query(description="待评估 ModelVersion id")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="最大返回数量")] = 100,
) -> list[DetectionEvaluationTaskSummaryResponse]:
    """按公开筛选条件列出 detection 评估任务。"""

    return list_detection_evaluation_task_responses(
        principal=principal,
        session_factory=session_factory,
        project_id=project_id,
        model_type=model_type,
        state=state,
        created_by=created_by,
        dataset_export_id=dataset_export_id,
        dataset_export_manifest_key=dataset_export_manifest_key,
        model_version_id=model_version_id,
        limit=limit,
    )


@detection_evaluation_tasks_router.get(
    "/detection/evaluation-tasks/{task_id}",
    response_model=DetectionEvaluationTaskDetailResponse,
)
def get_detection_evaluation_task_detail(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    include_events: Annotated[bool, Query(description="是否返回事件列表")] = False,
) -> DetectionEvaluationTaskDetailResponse:
    """按任务 id 返回 detection 评估任务详情。"""

    return get_detection_evaluation_task_detail_response(
        task_id=task_id,
        principal=principal,
        session_factory=session_factory,
        include_events=include_events,
    )


@detection_evaluation_tasks_router.get(
    "/detection/evaluation-tasks/{task_id}/report",
    response_model=DetectionEvaluationReportResponse,
)
def get_detection_evaluation_task_report(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionEvaluationReportResponse:
    """按任务 id 返回当前 detection 评估报告。"""

    return get_detection_evaluation_task_report_response(
        task_id=task_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )


@detection_evaluation_tasks_router.get(
    "/detection/evaluation-tasks/{task_id}/output-files",
    response_model=list[DetectionEvaluationOutputFileSummaryResponse],
)
def list_detection_evaluation_output_files(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> list[DetectionEvaluationOutputFileSummaryResponse]:
    """按任务 id 列出当前 detection 评估输出文件状态。"""

    return list_detection_evaluation_output_file_responses(
        task_id=task_id,
        principal=principal,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
