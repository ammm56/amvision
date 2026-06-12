"""detection 评估任务 REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from backend.queue import LocalFileQueueBackend
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.detection_evaluation_route_models import (
    DetectionEvaluationTaskDetailResponse,
    DetectionEvaluationTaskSubmissionResponse,
    DetectionEvaluationTaskSummaryResponse,
    build_detection_evaluation_task_detail_response,
    build_detection_evaluation_task_summary_response,
)
from backend.service.api.rest.v1.routes.detection_output_files import (
    DetectionEvaluationOutputFileSummaryResponse,
    DetectionEvaluationReportResponse,
    _DETECTION_EVALUATION_OUTPUT_FILE_ORDER,
    _build_detection_evaluation_output_file_summary_response,
    _read_detection_evaluation_report,
)
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError
from backend.service.application.model_type_support import (
    require_optional_supported_platform_model_type,
    require_supported_platform_model_type,
)
from backend.service.application.models.detection_evaluation_task_service import (
    DETECTION_EVALUATION_TASK_KIND,
    DetectionEvaluationTaskRequest,
    SqlAlchemyDetectionEvaluationTaskService,
)
from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.domain.models.platform_model_support import (
    build_platform_model_type_field_description,
    normalize_platform_model_type,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService, TaskQueryFilters
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


detection_evaluation_tasks_router = APIRouter(prefix="/models", tags=["models"])

class DetectionEvaluationTaskCreateRequestBody(BaseModel):
    """描述 detection 数据集级评估任务创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description=build_platform_model_type_field_description(DETECTION_TASK_TYPE))
    model_version_id: str = Field(description="待评估 ModelVersion id")
    dataset_export_id: str | None = Field(default=None, description="评估输入使用的 DatasetExport id")
    dataset_export_manifest_key: str | None = Field(default=None, description="评估输入使用的导出 manifest object key")
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="评估 score threshold")
    nms_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="评估 NMS threshold")
    save_result_package: bool = Field(default=True, description="是否输出结果包")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加评估选项")
    display_name: str = Field(default="", description="可选的任务展示名称")


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

    if principal.project_ids and body.project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": body.project_id},
        )
    model_type = _normalize_detection_evaluation_model_type(body.model_type)
    service = SqlAlchemyDetectionEvaluationTaskService(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    submission = service.submit_evaluation_task(
        DetectionEvaluationTaskRequest(
            project_id=body.project_id,
            model_type=model_type,
            model_version_id=body.model_version_id,
            dataset_export_id=body.dataset_export_id,
            dataset_export_manifest_key=body.dataset_export_manifest_key,
            score_threshold=body.score_threshold,
            nms_threshold=body.nms_threshold,
            save_result_package=body.save_result_package,
            extra_options=dict(body.extra_options),
        ),
        created_by=principal.principal_id,
        display_name=body.display_name,
    )
    return DetectionEvaluationTaskSubmissionResponse(
        task_id=submission.task_id,
        status=submission.status,
        queue_name=submission.queue_name,
        queue_task_id=submission.queue_task_id,
        model_type=model_type,
        dataset_export_id=submission.dataset_export_id,
        dataset_export_manifest_key=submission.dataset_export_manifest_key,
        dataset_version_id=submission.dataset_version_id,
        format_id=submission.format_id,
        model_version_id=submission.model_version_id,
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

    normalized_model_type = _normalize_optional_detection_evaluation_model_type(model_type)
    visible_project_ids = _resolve_visible_project_ids(principal=principal, project_id=project_id)
    service = SqlAlchemyTaskService(session_factory)
    matched_tasks = []
    for current_project_id in visible_project_ids:
        matched_tasks.extend(
            service.list_tasks(
                TaskQueryFilters(
                    project_id=current_project_id,
                    task_kind=DETECTION_EVALUATION_TASK_KIND,
                    state=state,
                    created_by=created_by,
                    limit=limit,
                )
            )
        )
    visible_tasks = [
        task
        for task in matched_tasks
        if _matches_detection_evaluation_filters(
            task=task,
            model_type=normalized_model_type,
            dataset_export_id=dataset_export_id,
            dataset_export_manifest_key=dataset_export_manifest_key,
            model_version_id=model_version_id,
        )
    ]
    visible_tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
    return [
        build_detection_evaluation_task_summary_response(
            task,
            model_type=_resolve_detection_evaluation_model_type_from_task(task),
        )
        for task in visible_tasks[:limit]
    ]


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

    task_detail = _require_visible_detection_evaluation_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=include_events,
    )
    return build_detection_evaluation_task_detail_response(
        task_detail.task,
        tuple(task_detail.events),
        model_type=_resolve_detection_evaluation_model_type_from_task(task_detail.task),
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

    task_detail = _require_visible_detection_evaluation_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    return _read_detection_evaluation_report(task=task_detail.task, dataset_storage=dataset_storage)


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

    task_detail = _require_visible_detection_evaluation_task(
        principal=principal,
        task_id=task_id,
        session_factory=session_factory,
        include_events=False,
    )
    return [
        _build_detection_evaluation_output_file_summary_response(
            task=task_detail.task,
            file_name=file_name,
            dataset_storage=dataset_storage,
        )
        for file_name in _DETECTION_EVALUATION_OUTPUT_FILE_ORDER
    ]


def _normalize_detection_evaluation_model_type(model_type: str) -> str:
    """把模型分类归一化为 detection evaluation 正式值。"""

    return require_supported_platform_model_type(
        task_type=DETECTION_TASK_TYPE,
        model_type=model_type,
        unsupported_message="当前 detection evaluation 不支持指定模型分类",
    )


def _normalize_optional_detection_evaluation_model_type(model_type: str | None) -> str | None:
    """把可选模型分类归一化为 detection evaluation 正式值。"""

    return require_optional_supported_platform_model_type(
        task_type=DETECTION_TASK_TYPE,
        model_type=model_type,
        unsupported_message="当前 detection evaluation 不支持指定模型分类",
    )


def _resolve_visible_project_ids(
    *,
    principal: AuthenticatedPrincipal,
    project_id: str | None,
) -> tuple[str, ...]:
    """根据主体权限和查询条件解析可查询的 Project 范围。"""

    if project_id is not None:
        if principal.project_ids and project_id not in principal.project_ids:
            raise ResourceNotFoundError(
                "找不到指定的任务范围",
                details={"project_id": project_id},
            )
        return (project_id,)
    if principal.project_ids:
        return principal.project_ids
    raise InvalidRequestError("查询评估任务列表时必须提供 project_id")


def _ensure_detection_evaluation_task_visible(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    task_project_id: str,
) -> None:
    """校验当前主体是否可以访问指定 detection 评估任务。"""

    if principal.project_ids and task_project_id not in principal.project_ids:
        raise ResourceNotFoundError(
            "找不到指定的评估任务",
            details={"task_id": task_id},
        )


def _resolve_detection_evaluation_model_type_from_task(task: object) -> str:
    """从任务记录中解析 detection 评估模型分类。"""

    metadata = dict(getattr(task, "metadata", {}))
    normalized_model_type = normalize_platform_model_type(metadata.get("model_type"))
    if normalized_model_type is not None:
        return _normalize_detection_evaluation_model_type(normalized_model_type)
    result = dict(getattr(task, "result", {}))
    report_summary = result.get("report_summary")
    if isinstance(report_summary, dict):
        normalized_summary_model_type = normalize_platform_model_type(report_summary.get("model_type"))
        if normalized_summary_model_type is not None:
            return _normalize_detection_evaluation_model_type(normalized_summary_model_type)
    raise ResourceNotFoundError(
        "找不到指定的 detection 评估模型分类",
        details={"task_id": getattr(task, "task_id", None)},
    )


def _matches_detection_evaluation_filters(
    *,
    task: object,
    model_type: str | None,
    dataset_export_id: str | None,
    dataset_export_manifest_key: str | None,
    model_version_id: str | None,
) -> bool:
    """判断 detection 评估任务是否满足额外筛选条件。"""

    if model_type is not None and _resolve_detection_evaluation_model_type_from_task(task) != model_type:
        return False
    task_spec = dict(task.task_spec)
    manifest_object_key = task_spec.get("manifest_object_key")
    if dataset_export_id is not None and task_spec.get("dataset_export_id") != dataset_export_id:
        return False
    if model_version_id is not None and task_spec.get("model_version_id") != model_version_id:
        return False
    if (
        dataset_export_manifest_key is not None
        and task_spec.get("dataset_export_manifest_key") != dataset_export_manifest_key
        and manifest_object_key != dataset_export_manifest_key
    ):
        return False
    return True


def _require_visible_detection_evaluation_task(
    *,
    principal: AuthenticatedPrincipal,
    task_id: str,
    session_factory: SessionFactory,
    include_events: bool,
):
    """读取并校验当前主体可见的 detection 评估任务。"""

    service = SqlAlchemyTaskService(session_factory)
    task_detail = service.get_task(task_id, include_events=include_events)
    _ensure_detection_evaluation_task_visible(
        principal=principal,
        task_id=task_id,
        task_project_id=task_detail.task.project_id,
    )
    if task_detail.task.task_kind != DETECTION_EVALUATION_TASK_KIND:
        raise ResourceNotFoundError(
            "找不到指定的 detection 评估任务",
            details={"task_id": task_id},
        )
    _resolve_detection_evaluation_model_type_from_task(task_detail.task)
    return task_detail
