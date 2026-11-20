"""下载可见转换任务的受管报告。"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.queue import get_queue_backend
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.resource_file_response import ResourceFileResponse
from backend.service.api.rest.v1.routes.classification_conversion_tasks.services import CLASSIFICATION_CONVERSION_SERVICE_ENTRIES
from backend.service.api.rest.v1.routes.detection_conversion_tasks.visibility import require_visible_detection_conversion_task
from backend.service.api.rest.v1.routes.obb_conversion_tasks.services import OBB_CONVERSION_SERVICE_ENTRIES
from backend.service.api.rest.v1.routes.pose_conversion_tasks.services import POSE_CONVERSION_SERVICE_ENTRIES
from backend.service.api.rest.v1.routes.segmentation_conversion_tasks.services import SEGMENTATION_CONVERSION_SERVICE_ENTRIES
from backend.service.api.rest.v1.routes.task_conversion.visibility import require_visible_task_conversion_task
from backend.service.api.rest.v1.routes.task_conversion.deletion import delete_conversion_task_record
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.ports.queue import normalize_queue_path_component
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.infrastructure.queue.local_file import LocalFileQueueBackend


conversion_report_downloads_router = APIRouter(prefix="/models", tags=["models"])
_SERVICE_ENTRIES = {
    "classification": CLASSIFICATION_CONVERSION_SERVICE_ENTRIES,
    "segmentation": SEGMENTATION_CONVERSION_SERVICE_ENTRIES,
    "pose": POSE_CONVERSION_SERVICE_ENTRIES,
    "obb": OBB_CONVERSION_SERVICE_ENTRIES,
}


def _visible_conversion_task(
    task_type: str, task_id: str, principal: AuthenticatedPrincipal, session_factory: SessionFactory,
) -> TaskRecord:
    """读取并校验任务类型与项目可见性。"""
    normalize_queue_path_component(task_id, field_name="task_id")
    if task_type == "detection":
        detail = require_visible_detection_conversion_task(
            principal=principal, task_id=task_id, session_factory=session_factory, include_events=False,
        )
    else:
        detail = require_visible_task_conversion_task(
            principal=principal, task_id=task_id, task_type=task_type,
            service_entries=_SERVICE_ENTRIES[task_type], session_factory=session_factory, include_events=False,
        )
    return detail.task


def _owned_file_response(
    *, task: TaskRecord, object_key: object, folder: Literal["reports", "builds"],
    session_factory: SessionFactory, storage: LocalDatasetStorage, media_type: str,
) -> ResourceFileResponse:
    """只允许读取任务自身的受管文件。"""
    if not isinstance(object_key, str) or not object_key:
        raise ResourceNotFoundError("转换文件尚不可用")
    try:
        path = storage.resolve_deletion_path(object_key)
        root = storage.resolve(f"task-runs/conversion/{task.task_id}/artifacts/{folder}").absolute()
        if not path.is_relative_to(root) or path == root or not path.is_file():
            raise ResourceNotFoundError("转换文件不存在或归属无法确认")
    except (OSError, InvalidRequestError, ValueError) as error:
        raise ResourceNotFoundError("转换文件不可读取") from error
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", path.name)[:160] or "conversion-output"
    return ResourceFileResponse(
        session_factory=session_factory, project_id=task.project_id, resource_id=task.task_id,
        path=path, filename=filename, media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


@conversion_report_downloads_router.delete(
    "/{task_type}/conversion-tasks/{task_id}/record", status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversion_record(
    task_type: Literal["detection", "classification", "segmentation", "pose", "obb"],
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:write", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    queue_backend: Annotated[LocalFileQueueBackend, Depends(get_queue_backend)],
) -> Response:
    """仅删除可见转换任务的记录和专属运行文件。"""
    task = _visible_conversion_task(task_type, task_id, principal, session_factory)
    delete_conversion_task_record(
        task=task, session_factory=session_factory, dataset_storage=storage, queue_backend=queue_backend,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@conversion_report_downloads_router.get("/{task_type}/conversion-tasks/{task_id}/report/download")
def download_conversion_report(
    task_type: Literal["detection", "classification", "segmentation", "pose", "obb"],
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> Response:
    """下载登记的报告，或从失败任务生成仅含数值校验结果的诊断。"""
    task = _visible_conversion_task(task_type, task_id, principal, session_factory)
    if task.state == "failed":
        diagnostic = _read_numeric_validation(task.result.get("error_details"))
        if not isinstance(diagnostic, dict) or not diagnostic.get("failures"):
            raise ResourceNotFoundError("转换诊断报告尚不可用")
        return JSONResponse(
            {"task_id": task.task_id, "status": "failed", "published": False, "numeric_validation": diagnostic},
            headers={"Content-Disposition": 'attachment; filename="conversion-diagnostic.json"', "Cache-Control": "no-store"},
        )
    return _owned_file_response(task=task, object_key=task.result.get("report_object_key"), folder="reports",
                                session_factory=session_factory, storage=storage, media_type="application/json")


def _read_numeric_validation(details: object) -> dict[str, object] | None:
    """读取直接执行或受监督 Worker 产生的 OpenVINO、TensorRT 校验诊断。"""
    if not isinstance(details, dict):
        return None
    child_error = details.get("child_error")
    child_details = child_error.get("details") if isinstance(child_error, dict) else None
    for attempt_details in (details, child_details):
        if not isinstance(attempt_details, dict):
            continue
        diagnostic = attempt_details.get("numeric_validation")
        if isinstance(diagnostic, dict):
            return diagnostic
        build_error = attempt_details.get("build_error")
        worker_details = build_error.get("details") if isinstance(build_error, dict) else None
        diagnostic = worker_details.get("numeric_validation") if isinstance(worker_details, dict) else None
        if isinstance(diagnostic, dict):
            return diagnostic
    return None


@conversion_report_downloads_router.get("/{task_type}/conversion-tasks/{task_id}/builds/{build_id}/{part}/download")
def download_conversion_build_file(
    task_type: Literal["detection", "classification", "segmentation", "pose", "obb"],
    task_id: str,
    build_id: str,
    part: Literal["primary", "weights"],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> ResourceFileResponse:
    """下载任务报告登记的构建文件或 OpenVINO 权重文件。"""
    task = _visible_conversion_task(task_type, task_id, principal, session_factory)
    builds = task.result.get("builds")
    if not isinstance(builds, list):
        raise ResourceNotFoundError("转换产物尚不可用")
    build = next((item for item in builds if isinstance(item, dict) and item.get("model_build_id") == build_id), None)
    if build is None:
        raise ResourceNotFoundError("找不到指定的转换产物")
    metadata = build.get("metadata")
    object_key = build.get("build_file_uri") if part == "primary" else metadata.get("weights_object_uri") if isinstance(metadata, dict) else None
    return _owned_file_response(task=task, object_key=object_key, folder="builds", session_factory=session_factory,
                                storage=storage, media_type="application/octet-stream")
