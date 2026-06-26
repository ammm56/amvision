"""segmentation 训练任务 service 装配。"""

from __future__ import annotations

from backend.queue import LocalFileQueueBackend
from backend.service.api.rest.v1.routes.segmentation_training_tasks.schemas import (
    SegmentationTrainingTaskCreateRequestBody,
    SegmentationTrainingTaskSubmissionResponse,
)
from backend.service.application.model_type_support import (
    require_supported_platform_model_type,
)
from backend.service.application.models.training.segmentation_training_service import (
    SqlAlchemySegmentationTrainingService,
    SegmentationTrainingRequest,
)
from backend.service.application.models.training.yolo11_segmentation_training_service import (
    SqlAlchemyYolo11SegmentationTrainingTaskService,
    Yolo11SegmentationTrainingTaskRequest,
)
from backend.service.application.models.training.yolo26_segmentation_training_service import (
    SqlAlchemyYolo26SegmentationTrainingTaskService,
    Yolo26SegmentationTrainingTaskRequest,
)
from backend.service.domain.models.model_task_types import SEGMENTATION_TASK_TYPE
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


def submit_segmentation_training_task(
    *,
    body: SegmentationTrainingTaskCreateRequestBody,
    created_by: str,
    session_factory: SessionFactory,
    queue_backend: LocalFileQueueBackend,
    dataset_storage: LocalDatasetStorage,
) -> SegmentationTrainingTaskSubmissionResponse:
    """提交 segmentation 训练任务。"""

    model_type = require_supported_platform_model_type(
        task_type=SEGMENTATION_TASK_TYPE,
        model_type=body.model_type,
        unsupported_message="当前 segmentation 训练不支持指定模型分类",
    )
    service_and_request_by_model_type = {
        "yolo11": (
            SqlAlchemyYolo11SegmentationTrainingTaskService,
            Yolo11SegmentationTrainingTaskRequest,
        ),
        "yolo26": (
            SqlAlchemyYolo26SegmentationTrainingTaskService,
            Yolo26SegmentationTrainingTaskRequest,
        ),
    }
    service_cls, request_cls = service_and_request_by_model_type.get(
        model_type,
        (
            SqlAlchemySegmentationTrainingService,
            SegmentationTrainingRequest,
        ),
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
            warm_start_model_version_id=body.warm_start_model_version_id,
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
    return SegmentationTrainingTaskSubmissionResponse(
        task_id=result["task_id"],
        status=result["status"],
        queue_name=result["queue_name"],
        queue_task_id=result["queue_task_id"],
    )
