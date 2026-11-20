"""训练向导提交前的只读检查接口。"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.routes.classification_training_tasks.schemas import ClassificationTrainingTaskCreateRequestBody
from backend.service.api.rest.v1.routes.detection_training_tasks.schemas import DetectionTrainingTaskCreateRequestBody
from backend.service.api.rest.v1.routes.detection_training_tasks.responses import build_detection_training_task_detail_response
from backend.service.api.rest.v1.routes.detection_training_tasks.services import (
    _require_visible_detection_training_task,
    _resolve_detection_training_model_type_from_task,
)
from backend.service.api.rest.v1.routes.obb_training_tasks.schemas import ObbTrainingTaskCreateRequestBody
from backend.service.api.rest.v1.routes.pose_training_tasks.schemas import PoseTrainingTaskCreateRequestBody
from backend.service.api.rest.v1.routes.segmentation_training_tasks.schemas import SegmentationTrainingTaskCreateRequestBody
from backend.service.api.rest.v1.routes.task_training.catalog import TASK_KIND_TO_TASK_TYPE
from backend.service.api.rest.v1.routes.task_training.responses import build_detail_response
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.models.training.resume_checkpoint_validation import require_readable_resume_checkpoint
from backend.service.application.models.training.submission_checks import inspect_training_submission
from backend.service.application.project_access import require_explicit_project_access
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


training_preflight_router = APIRouter(prefix="/models", tags=["models"])
_REQUESTS = {
    "detection": DetectionTrainingTaskCreateRequestBody,
    "classification": ClassificationTrainingTaskCreateRequestBody,
    "segmentation": SegmentationTrainingTaskCreateRequestBody,
    "pose": PoseTrainingTaskCreateRequestBody,
    "obb": ObbTrainingTaskCreateRequestBody,
}


@training_preflight_router.post("/{task_type}/training-tasks/preview")
def preview_training_submission(
    task_type: Literal["detection", "classification", "segmentation", "pose", "obb"],
    payload: dict[str, Any],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("datasets:read", "tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> dict[str, object]:
    """按创建请求的 schema 核对配置、导出和本地权重，不创建任务。"""
    try:
        body = _REQUESTS[task_type].model_validate(payload)
    except ValidationError as exc:
        raise RequestValidationError([
            {**error, "loc": ("body", *error["loc"])}
            for error in exc.errors(include_context=False, include_url=False)
        ]) from exc
    require_explicit_project_access(visible_project_ids=principal.project_ids, project_id=body.project_id)
    return inspect_training_submission(
        session_factory=session_factory, storage=storage, project_id=body.project_id, task_type=task_type,
        model_type=body.model_type, model_scale=body.model_scale, dataset_export_id=body.dataset_export_id,
        manifest_key=body.dataset_export_manifest_key, warm_start_version_id=body.warm_start_model_version_id,
        output_model_name=body.output_model_name,
    )


@training_preflight_router.get("/{task_type}/training-tasks/{task_id}/resume/preview")
def preview_training_resume(
    task_type: Literal["detection", "classification", "segmentation", "pose", "obb"],
    task_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
) -> dict[str, object]:
    """检查同一任务的状态、导出清单及 latest checkpoint 文件。"""
    if task_type == "detection":
        task = _require_visible_detection_training_task(
            principal=principal, task_id=task_id, session_factory=session_factory, include_events=False,
        ).task
        detail = build_detection_training_task_detail_response(
            task, (), model_type=_resolve_detection_training_model_type_from_task(task),
        )
    else:
        task = SqlAlchemyTaskService(session_factory).get_visible_task(task_id, visible_project_ids=principal.project_ids).task
        if TASK_KIND_TO_TASK_TYPE.get(task.task_kind) != task_type:
            raise ResourceNotFoundError("找不到指定的训练任务")
        detail = build_detail_response(task, ())
    checkpoint_key = detail.control_status.resume_checkpoint_object_key
    if "resume" not in detail.available_actions or not checkpoint_key:
        raise InvalidRequestError("当前任务状态或检查点不允许恢复训练", details={"resume_check": "task"})
    try:
        checkpoint = storage.resolve_deletion_path(checkpoint_key)
        require_readable_resume_checkpoint(checkpoint, task_id=task_id, checkpoint_object_key=checkpoint_key)
    except InvalidRequestError as error:
        error.details["resume_check"] = "checkpoint"
        raise
    with session_factory.create_session() as session:
        unit = SqlAlchemyUnitOfWork(session)
        export_id = detail.dataset_export_id
        export = unit.dataset_exports.get_dataset_export(export_id) if export_id else None
        if (export is None or export.project_id != task.project_id or export.status != "completed"
                or export.metadata.get("files_cleaned_at") or not export.manifest_object_key
                or not storage.resolve(export.manifest_object_key).is_file()):
            raise InvalidRequestError("原训练任务的数据集导出已不可用，无法恢复训练", details={"resume_check": "dataset"})
    return {"checkpoint_name": checkpoint.name, "dataset_export_id": export_id}
