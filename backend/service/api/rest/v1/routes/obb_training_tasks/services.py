"""OBB 训练任务 service 装配。"""

from __future__ import annotations

from backend.queue import LocalFileQueueBackend
from backend.service.api.rest.v1.routes.obb_training_tasks.schemas import (
    ObbTrainingTaskCreateRequestBody,
    ObbTrainingTaskSubmissionResponse,
)
from backend.service.application.model_type_support import (
    require_supported_platform_model_type,
)
from backend.service.application.models.training.yolo_task_obb_training_service import (
    SqlAlchemyYoloTaskObbTrainingService,
    YoloTaskObbTrainingRequest,
)
from backend.service.application.models.training.yolo11_obb_training_service import (
    SqlAlchemyYolo11ObbTrainingTaskService,
    Yolo11ObbTrainingTaskRequest,
)
from backend.service.application.models.training.yolo26_obb_training_service import (
    SqlAlchemyYolo26ObbTrainingTaskService,
    Yolo26ObbTrainingTaskRequest,
)
from backend.service.domain.models.model_task_types import OBB_TASK_TYPE
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


def submit_obb_training_task(
    *,
    body: ObbTrainingTaskCreateRequestBody,
    created_by: str,
    session_factory: SessionFactory,
    queue_backend: LocalFileQueueBackend,
    dataset_storage: LocalDatasetStorage,
) -> ObbTrainingTaskSubmissionResponse:
    """提交 OBB 训练任务。"""

    model_type = require_supported_platform_model_type(
        task_type=OBB_TASK_TYPE,
        model_type=body.model_type,
        unsupported_message="obb 训练不支持该模型分类",
    )
    service_cls, request_cls = _resolve_obb_training_service_and_request(model_type)
    service = service_cls(
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )
    result = service.submit_training_task(
        request_cls(
            project_id=body.project_id,
            recipe_id=body.recipe_id,
            model_type=model_type,
            model_scale=body.model_scale,
            output_model_name=body.output_model_name,
            dataset_export_id=body.dataset_export_id,
            dataset_export_manifest_key=body.dataset_export_manifest_key,
            evaluation_interval=body.evaluation_interval,
            max_epochs=body.max_epochs,
            batch_size=body.batch_size,
            input_size=body.input_size,
            precision=body.precision,
            extra_options=dict(body.extra_options),
            display_name=body.display_name,
        ),
        created_by=created_by,
    )
    return ObbTrainingTaskSubmissionResponse(
        task_id=result["task_id"],
        status=result["status"],
        queue_name=result["queue_name"],
        queue_task_id=result["queue_task_id"],
    )


def _resolve_obb_training_service_and_request(model_type: str):
    """按 model_type 返回 OBB 训练 service 与请求 DTO。"""

    if model_type == "yolo11":
        return SqlAlchemyYolo11ObbTrainingTaskService, Yolo11ObbTrainingTaskRequest
    if model_type == "yolo26":
        return SqlAlchemyYolo26ObbTrainingTaskService, Yolo26ObbTrainingTaskRequest
    return SqlAlchemyYoloTaskObbTrainingService, YoloTaskObbTrainingRequest

