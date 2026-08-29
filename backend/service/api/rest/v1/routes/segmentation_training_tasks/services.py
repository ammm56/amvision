"""segmentation 训练任务 service 装配。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.segmentation_training_tasks.schemas import (
    SegmentationTrainingTaskCreateRequestBody,
    SegmentationTrainingTaskSubmissionResponse,
)
from backend.service.application.model_type_support import (
    require_supported_platform_model_type,
)
from backend.service.domain.models.model_task_types import SEGMENTATION_TASK_TYPE
from backend.service.api.rest.v1.routes.training_execution_schemas import (
    merge_training_execution_options,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


def submit_segmentation_training_task(
    *,
    body: SegmentationTrainingTaskCreateRequestBody,
    created_by: str,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> SegmentationTrainingTaskSubmissionResponse:
    """提交 segmentation 训练任务。"""

    model_type = require_supported_platform_model_type(
        task_type=SEGMENTATION_TASK_TYPE,
        model_type=body.model_type,
        unsupported_message="当前 segmentation 训练不支持指定模型分类",
    )
    service_cls, request_cls = _resolve_segmentation_training_service(model_type)
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
    return SegmentationTrainingTaskSubmissionResponse(
        task_id=result["task_id"],
        status=result["status"],
        queue_name=result["queue_name"],
        queue_task_id=result["queue_task_id"],
    )


def _resolve_segmentation_training_service(model_type: str) -> tuple[type, type]:
    """按实际训练请求延迟加载模型执行服务。"""

    if model_type == "yolo11":
        from backend.service.application.models.training.yolo11_segmentation_training_service import (
            SqlAlchemyYolo11SegmentationTrainingTaskService,
            Yolo11SegmentationTrainingTaskRequest,
        )

        return (
            SqlAlchemyYolo11SegmentationTrainingTaskService,
            Yolo11SegmentationTrainingTaskRequest,
        )
    if model_type == "yolo26":
        from backend.service.application.models.training.yolo26_segmentation_training_service import (
            SqlAlchemyYolo26SegmentationTrainingTaskService,
            Yolo26SegmentationTrainingTaskRequest,
        )

        return (
            SqlAlchemyYolo26SegmentationTrainingTaskService,
            Yolo26SegmentationTrainingTaskRequest,
        )
    from backend.service.application.models.training.segmentation_training_service import (
        SegmentationTrainingRequest,
        SqlAlchemySegmentationTrainingService,
    )

    return SqlAlchemySegmentationTrainingService, SegmentationTrainingRequest
