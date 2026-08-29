"""classification 训练任务 service 装配。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.classification_training_tasks.schemas import (
    ClassificationTrainingTaskCreateRequestBody,
    ClassificationTrainingTaskSubmissionResponse,
)
from backend.service.application.model_type_support import (
    require_supported_platform_model_type,
)
from backend.service.domain.models.model_task_types import CLASSIFICATION_TASK_TYPE
from backend.service.api.rest.v1.routes.training_execution_schemas import (
    merge_training_execution_options,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


def submit_classification_training_task(
    *,
    body: ClassificationTrainingTaskCreateRequestBody,
    created_by: str,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> ClassificationTrainingTaskSubmissionResponse:
    """提交 classification 训练任务。"""

    model_type = require_supported_platform_model_type(
        task_type=CLASSIFICATION_TASK_TYPE,
        model_type=body.model_type,
        unsupported_message="当前 classification 训练不支持指定模型分类",
    )
    service_cls, request_cls = _resolve_classification_training_service(
        model_type
    )
    service = service_cls(
        session_factory=session_factory,
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
            warm_start_model_version_id=body.warm_start_model_version_id,
            evaluation_interval=body.execution.validation.interval_epochs,
            max_epochs=body.execution.max_epochs,
            batch_size=body.execution.fixed_batch_size,
            input_size=(
                body.execution.input_size.hw
                if body.execution.input_size is not None
                else None
            ),
            precision=body.execution.requested_precision,
            extra_options=merge_training_execution_options(
                execution=body.execution,
                model_options=body.parameters.to_execution_options(),
            ),
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


def _resolve_classification_training_service(model_type: str) -> tuple[type, type]:
    """按实际训练请求延迟加载模型执行服务。"""

    if model_type == "yolo11":
        from backend.service.application.models.training.yolo11_classification_training_service import (
            SqlAlchemyYolo11ClassificationTrainingTaskService,
            Yolo11ClassificationTrainingTaskRequest,
        )

        return (
            SqlAlchemyYolo11ClassificationTrainingTaskService,
            Yolo11ClassificationTrainingTaskRequest,
        )
    if model_type == "yolo26":
        from backend.service.application.models.training.yolo26_classification_training_service import (
            SqlAlchemyYolo26ClassificationTrainingTaskService,
            Yolo26ClassificationTrainingTaskRequest,
        )

        return (
            SqlAlchemyYolo26ClassificationTrainingTaskService,
            Yolo26ClassificationTrainingTaskRequest,
        )
    from backend.service.application.models.training.yolov8_classification_training_service import (
        SqlAlchemyYoloV8ClassificationTrainingService,
        YoloV8ClassificationTrainingRequest,
    )

    return (
        SqlAlchemyYoloV8ClassificationTrainingService,
        YoloV8ClassificationTrainingRequest,
    )
