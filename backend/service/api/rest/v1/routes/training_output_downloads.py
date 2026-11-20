"""按任务身份下载训练输出文件。"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.resource_file_response import ResourceFileResponse
from backend.service.api.rest.v1.routes.detection_training_tasks.output_files import (
    _parse_detection_training_output_file_name,
    _resolve_detection_training_output_file_object_key,
)
from backend.service.api.rest.v1.routes.detection_training_tasks.services import (
    _require_visible_detection_training_task,
)
from backend.service.api.rest.v1.routes.task_training.catalog import TASK_KIND_TO_TASK_TYPE
from backend.service.api.rest.v1.routes.task_training.output_files import (
    _parse_training_output_file_name,
    _resolve_training_output_file_object_key,
)
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.ports.queue import normalize_queue_path_component
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


training_output_downloads_router = APIRouter(prefix="/models", tags=["models"])


@training_output_downloads_router.get(
    "/{task_type}/training-tasks/{task_id}/output-files/{file_name}/download"
)
def download_training_output_file(
    task_type: Literal["detection", "classification", "segmentation", "pose", "obb"],
    task_id: str,
    file_name: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> ResourceFileResponse:
    """只允许下载当前可见任务的已登记输出，并在发送时保护其所属项目。"""
    normalize_queue_path_component(task_id, field_name="task_id")
    if task_type == "detection":
        task = _require_visible_detection_training_task(
            principal=principal, task_id=task_id, session_factory=session_factory,
            include_events=False,
        ).task
        object_key = _resolve_detection_training_output_file_object_key(
            task=task, file_name=_parse_detection_training_output_file_name(file_name),
        )
    else:
        task = SqlAlchemyTaskService(session_factory).get_visible_task(
            task_id, visible_project_ids=principal.project_ids,
        ).task
        if TASK_KIND_TO_TASK_TYPE.get(task.task_kind) != task_type:
            raise ResourceNotFoundError("找不到指定的训练任务")
        object_key = _resolve_training_output_file_object_key(
            task=task, file_name=_parse_training_output_file_name(file_name),
        )
    if not object_key:
        raise ResourceNotFoundError("训练输出文件尚不可用")
    try:
        path = storage.resolve_deletion_path(object_key)
        # 不从客户端接收路径；旧记录中的路径也必须属于该任务的受管目录。
        roots = (
            storage.resolve(f"task-runs/{task_id}").absolute(),
            storage.resolve(f"task-runs/training/{task_id}").absolute(),
        )
        if not any(path.is_relative_to(root) and path != root for root in roots) or not path.is_file():
            raise ResourceNotFoundError("训练输出文件不存在或归属无法确认")
    except (OSError, InvalidRequestError, ValueError) as error:
        raise ResourceNotFoundError("训练输出文件不可读取") from error
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", path.name)[:160] or "training-output"
    return ResourceFileResponse(
        session_factory=session_factory, project_id=task.project_id, resource_id=task_id,
        path=path, filename=filename, media_type="application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )
