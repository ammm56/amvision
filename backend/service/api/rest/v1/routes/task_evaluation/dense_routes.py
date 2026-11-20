"""语义分割和异常检测独立评估提交与任务查询。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, UploadFile
from starlette.concurrency import run_in_threadpool

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.rest.v1.routes.task_evaluation.reports import Factory, Principal, Storage
from backend.service.api.rest.v1.routes.task_evaluation.services import (
    get_evaluation_task_record,
    list_evaluation_task_records,
    require_evaluation_project_access,
)
from backend.service.application.models.evaluation.dense_evaluation import DenseKind
from backend.service.application.models.evaluation.dense_evaluation_tasks import submit_dense_evaluation

dense_evaluation_router = APIRouter(prefix="/models/{kind}/evaluation-tasks", tags=["models"])
Requester = Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write", "models:read", "datasets:read"))]


def _record(task) -> dict:
    """返回列表和详情共用的评估任务字段。"""
    return {
        "task_id": task.task_id, "project_id": task.project_id, "display_name": task.display_name,
        "state": task.state, "created_at": task.created_at, "finished_at": task.finished_at,
        "progress": task.progress,
        "error_message": task.error_message, "sample_count": task.result.get("sample_count"),
        "miou": task.result.get("miou"), "image_auroc": task.result.get("image_auroc"),
        "result": {"report_object_key": task.result.get("report_object_key")},
    }


@dense_evaluation_router.post("", status_code=202)
async def create_dense_evaluation(
    kind: DenseKind, file: UploadFile, principal: Requester, factory: Factory, storage: Storage,
    project_id: Annotated[str, Form(min_length=1, max_length=128)],
    display_name: Annotated[str, Form(max_length=160)] = "",
    threshold: Annotated[float, Form(ge=0, le=1)] = 0.5,
) -> dict:
    """上传已生成预测的 ZIP 并提交独立评估。"""
    require_evaluation_project_access(principal=principal, project_id=project_id)
    task = await run_in_threadpool(
        submit_dense_evaluation, factory, storage, project_id=project_id, kind=kind,
        display_name=display_name, threshold=threshold, stream=file.file, created_by=principal.principal_id,
    )
    return {"task_id": task.task_id}


@dense_evaluation_router.get("")
def list_dense_evaluations(
    kind: DenseKind, project_id: str, principal: Principal, factory: Factory,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict]:
    """列出当前项目的独立评估。"""
    require_evaluation_project_access(principal=principal, project_id=project_id)
    return [_record(task) for task in list_evaluation_task_records(
        session_factory=factory, project_id=project_id, task_kind=f"{kind}-evaluation", state=None, limit=limit,
    )]


@dense_evaluation_router.get("/{task_id}")
def get_dense_evaluation(kind: DenseKind, task_id: str, principal: Principal, factory: Factory) -> dict:
    """读取评估详情供任务进度和失败提示使用。"""
    return _record(get_evaluation_task_record(
        principal=principal, session_factory=factory, task_id=task_id, expected_task_kind=f"{kind}-evaluation",
    ))
