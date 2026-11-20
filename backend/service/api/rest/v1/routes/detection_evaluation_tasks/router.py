"""detection evaluation task REST 路由。"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
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
    preview_detection_evaluation,
    read_evaluation_sample_snapshot,
)
from backend.service.api.resource_file_response import ResourceFileResponse
from backend.service.application.errors import ResourceNotFoundError
from backend.service.application.models.evaluation.detection_evaluation import find_localization_error
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


detection_evaluation_tasks_router = APIRouter(prefix="/models", tags=["models"])


@detection_evaluation_tasks_router.post("/detection/evaluation-tasks/preview")
def preview_detection_evaluation_task(
    body: DetectionEvaluationTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read", "models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> dict:
    """返回真实评估范围，供提交前复核。"""
    return preview_detection_evaluation(body, principal, session_factory, storage)


@detection_evaluation_tasks_router.post(
    "/detection/evaluation-tasks",
    response_model=DetectionEvaluationTaskSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_detection_evaluation_task(
    body: DetectionEvaluationTaskCreateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read", "models:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> DetectionEvaluationTaskSubmissionResponse:
    """创建一个用于数据集级回归验证的 detection evaluation task。"""

    return create_detection_evaluation_task_response(
        body=body,
        principal=principal,
        session_factory=session_factory,
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
    offset: Annotated[int, Query(ge=0, description="匹配结果偏移量")] = 0,
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
        offset=offset,
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


@detection_evaluation_tasks_router.get("/detection/evaluation-tasks/{task_id}/samples")
def get_detection_evaluation_samples(
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    issue: Literal["all", "errors", "false_negatives", "false_positives", "localization"] = "all",
    q: Annotated[str, Query(max_length=255)] = "",
    class_name: Annotated[str, Query(max_length=255)] = "",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
) -> dict:
    """分页回放真实标注及预测，不返回内部文件路径。"""
    _, samples = read_evaluation_sample_snapshot(task_id, principal, session_factory, storage)
    needle = q.strip().casefold()
    selected = []
    for sample in samples:
        name = PurePosixPath(str(sample.get("image_path", "")).replace("\\", "/")).name
        if needle and needle not in name.casefold():
            continue
        if issue == "localization":
            if pair := find_localization_error(sample, class_name):
                selected.append(({**sample, "localization_pair": pair}, name))
            continue
        missed, extra = sample.get("false_negatives") or 0, sample.get("false_positives") or 0
        if ((issue == "errors" and not (missed or extra))
            or (issue == "false_negatives" and not missed)
            or (issue == "false_positives" and not extra)):
            continue
        if class_name:
            layers = (
                ("ground_truth",) if issue == "false_negatives" else
                ("predictions",) if issue == "false_positives" else
                ("ground_truth", "predictions")
            )
            if not any(
                box.get("class_name") == class_name and (issue == "all" or box.get("matched") is False)
                for layer in layers for box in sample.get(layer) or ()
            ):
                continue
        selected.append((sample, name))
    return {
        "total": len(selected),
        "diagnostics_available": any(
            sample.get("false_negatives") is not None or sample.get("false_positives") is not None
            for sample in samples
        ),
        "items": [
            {**{key: value for key, value in sample.items() if key != "image_path"}, "name": name}
            for sample, name in selected[offset:offset + limit]
        ],
    }


@detection_evaluation_tasks_router.get("/detection/evaluation-tasks/{task_id}/samples/{index}/image")
def get_detection_evaluation_image(
    task_id: str, index: int,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read", "datasets:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> ResourceFileResponse:
    """只读取该评估所用导出目录里的已记录样本图片。"""
    task, samples = read_evaluation_sample_snapshot(task_id, principal, session_factory, storage, failed_index=index)
    sample = next((item for item in samples if item["image_index"] == index), None)
    with session_factory.create_session() as session:
        unit = SqlAlchemyUnitOfWork(session)
        export_id = task.task_spec.get("dataset_export_id")
        export = unit.dataset_exports.get_dataset_export(export_id) if isinstance(export_id, str) else None
    if not sample or not export or export.project_id != task.project_id or not export.export_path:
        raise ResourceNotFoundError("找不到评估图片")
    image_key = sample.get("image_path")
    if not isinstance(image_key, str) or not image_key:
        raise ResourceNotFoundError("找不到评估图片")
    candidate = storage.resolve_deletion_path(image_key)
    root = storage.resolve_deletion_path(export.export_path)
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".bmp": "image/bmp", ".webp": "image/webp"}
    media_type = mime.get(candidate.suffix.lower())
    if not candidate.is_relative_to(root) or not candidate.is_file() or not media_type:
        raise ResourceNotFoundError("找不到评估图片")
    return ResourceFileResponse(
        session_factory=session_factory, project_id=task.project_id, resource_id=task_id,
        path=candidate, media_type=media_type, headers={"X-Content-Type-Options": "nosniff"},
    )
