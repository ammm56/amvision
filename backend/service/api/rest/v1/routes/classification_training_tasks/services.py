"""classification 训练任务 service 装配。"""

from __future__ import annotations

from backend.queue import LocalFileQueueBackend
from backend.service.api.rest.v1.routes.classification_training_tasks.schemas import (
    ClassificationTrainingTaskCreateRequestBody,
    ClassificationTrainingTaskSubmissionResponse,
)
from backend.service.application.model_type_support import (
    require_supported_platform_model_type,
)
from backend.service.application.models.training.yolo_task_classification_training_service import (
    SqlAlchemyYoloTaskClassificationTrainingService,
    YoloTaskClassificationTrainingRequest,
)
from backend.service.application.models.training.yolo11_classification_training_service import (
    SqlAlchemyYolo11ClassificationTrainingTaskService,
    Yolo11ClassificationTrainingTaskRequest,
)
from backend.service.application.models.training.yolo26_classification_training_service import (
    SqlAlchemyYolo26ClassificationTrainingTaskService,
    Yolo26ClassificationTrainingTaskRequest,
)
from backend.service.domain.models.model_task_types import CLASSIFICATION_TASK_TYPE
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


def submit_classification_training_task(
    *,
    body: ClassificationTrainingTaskCreateRequestBody,
    created_by: str,
    session_factory: SessionFactory,
    queue_backend: LocalFileQueueBackend,
    dataset_storage: LocalDatasetStorage,
) -> ClassificationTrainingTaskSubmissionResponse:
    """提交 classification 训练任务。"""

    model_type = require_supported_platform_model_type(
        task_type=CLASSIFICATION_TASK_TYPE,
        model_type=body.model_type,
        unsupported_message="当前 classification 训练不支持指定模型分类",
    )
    service_cls_by_model_type = {
        "yolo11": SqlAlchemyYolo11ClassificationTrainingTaskService,
        "yolo26": SqlAlchemyYolo26ClassificationTrainingTaskService,
    }
    request_cls_by_model_type = {
        "yolo11": Yolo11ClassificationTrainingTaskRequest,
        "yolo26": Yolo26ClassificationTrainingTaskRequest,
    }
    service_cls = service_cls_by_model_type.get(
        model_type,
        SqlAlchemyYoloTaskClassificationTrainingService,
    )
    request_cls = request_cls_by_model_type.get(
        model_type,
        YoloTaskClassificationTrainingRequest,
    )
    service = service_cls(
        session_factory=session_factory,
        queue_backend=queue_backend,
        dataset_storage=dataset_storage,
    )
    result = service.submit_training_task(
        request_cls(
            project_id=body.project_id,
            recipe_id=body.recipe_id,
            model_scale=body.model_scale,
            output_model_name=body.output_model_name,
            dataset_export_id=body.dataset_export_id,
            dataset_export_manifest_key=body.dataset_export_manifest_key,
            max_epochs=body.max_epochs,
            batch_size=body.batch_size,
            input_size=body.input_size,
            precision=body.precision,
            extra_options=dict(body.extra_options),
            display_name=body.display_name,
            model_type=model_type,
        ),
        created_by=created_by,
    )
    return ClassificationTrainingTaskSubmissionResponse(
        task_id=result["task_id"],
        status=result["status"],
        queue_name=result["queue_name"],
        queue_task_id=result["queue_task_id"],
    )

