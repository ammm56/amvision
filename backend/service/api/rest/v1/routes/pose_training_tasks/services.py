"""pose 训练任务 service 装配。"""

from __future__ import annotations

from backend.queue import LocalFileQueueBackend
from backend.service.api.rest.v1.routes.pose_training_tasks.schemas import (
    PoseTrainingTaskCreateRequestBody,
    PoseTrainingTaskSubmissionResponse,
)
from backend.service.application.model_type_support import (
    require_supported_platform_model_type,
)
from backend.service.application.models.training.yolov8_pose_training_service import (
    SqlAlchemyYoloV8PoseTrainingService,
    YoloV8PoseTrainingRequest,
)
from backend.service.application.models.training.yolo11_pose_training_service import (
    SqlAlchemyYolo11PoseTrainingTaskService,
    Yolo11PoseTrainingTaskRequest,
)
from backend.service.application.models.training.yolo26_pose_training_service import (
    SqlAlchemyYolo26PoseTrainingTaskService,
    Yolo26PoseTrainingTaskRequest,
)
from backend.service.domain.models.model_task_types import POSE_TASK_TYPE
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


def submit_pose_training_task(
    *,
    body: PoseTrainingTaskCreateRequestBody,
    created_by: str,
    session_factory: SessionFactory,
    queue_backend: LocalFileQueueBackend,
    dataset_storage: LocalDatasetStorage,
) -> PoseTrainingTaskSubmissionResponse:
    """提交 pose 训练任务。"""

    model_type = require_supported_platform_model_type(
        task_type=POSE_TASK_TYPE,
        model_type=body.model_type,
        unsupported_message="pose 训练不支持该模型分类",
    )
    service_cls_by_model_type = {
        "yolo11": SqlAlchemyYolo11PoseTrainingTaskService,
        "yolo26": SqlAlchemyYolo26PoseTrainingTaskService,
    }
    request_cls_by_model_type = {
        "yolo11": Yolo11PoseTrainingTaskRequest,
        "yolo26": Yolo26PoseTrainingTaskRequest,
    }
    service_cls = service_cls_by_model_type.get(
        model_type,
        SqlAlchemyYoloV8PoseTrainingService,
    )
    request_cls = request_cls_by_model_type.get(
        model_type,
        YoloV8PoseTrainingRequest,
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
            model_type=model_type,
            model_scale=body.model_scale,
            output_model_name=body.output_model_name,
            dataset_export_id=body.dataset_export_id,
            dataset_export_manifest_key=body.dataset_export_manifest_key,
            warm_start_model_version_id=body.warm_start_model_version_id,
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
    return PoseTrainingTaskSubmissionResponse(
        task_id=result["task_id"],
        status=result["status"],
        queue_name=result["queue_name"],
        queue_task_id=result["queue_task_id"],
    )


