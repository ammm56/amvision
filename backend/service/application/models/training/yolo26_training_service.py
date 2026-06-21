"""YOLO26 detection 训练任务适配器。"""

from __future__ import annotations

from backend.queue import QueueBackend
from backend.service.application.models.training.yolo26_detection_training import (
    YOLO26_IMPLEMENTATION_MODE,
    Yolo26DetectionTrainingExecutionRequest,
    run_yolo26_detection_training,
)
from backend.service.application.models.registry.yolo26_model_service import (
    SqlAlchemyYolo26ModelService,
    Yolo26TrainingOutputRegistration,
)
from backend.service.application.models.training.yolo_detection_training_service import (
    SqlAlchemyYoloDetectionTrainingTaskService,
    YoloDetectionTrainingTaskRequest as Yolo26TrainingTaskRequest,
    YoloDetectionTrainingTaskResult as Yolo26TrainingTaskResult,
)
from backend.service.domain.files.detection_model_file_types import (
    YOLO26_DETECTION_FILE_TYPES,
)
from backend.service.domain.models.yolo26_model_spec import (
    DEFAULT_YOLO26_MODEL_SPEC,
    Yolo26ModelSpec,
)
from backend.service.domain.tasks.yolo26_task_specs import Yolo26TrainingTaskSpec
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


YOLO26_TRAINING_TASK_KIND = "yolo26-training"
YOLO26_TRAINING_QUEUE_NAME = "yolo26-trainings"


class SqlAlchemyYolo26TrainingTaskService(SqlAlchemyYoloDetectionTrainingTaskService):
    """基于 detection 公共训练链的 YOLO26 训练任务适配器。"""

    model_type = "yolo26"
    model_label = "YOLO26"
    training_task_kind = YOLO26_TRAINING_TASK_KIND
    training_queue_name = YOLO26_TRAINING_QUEUE_NAME
    model_service_cls = SqlAlchemyYolo26ModelService
    output_registration_cls = Yolo26TrainingOutputRegistration
    task_spec_cls = Yolo26TrainingTaskSpec
    request_cls = Yolo26TrainingTaskRequest
    task_result_cls = Yolo26TrainingTaskResult
    execution_request_cls = Yolo26DetectionTrainingExecutionRequest
    training_runner = staticmethod(run_yolo26_detection_training)
    implementation_mode = YOLO26_IMPLEMENTATION_MODE
    file_types = YOLO26_DETECTION_FILE_TYPES

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None = None,
        queue_backend: QueueBackend | None = None,
        spec: Yolo26ModelSpec = DEFAULT_YOLO26_MODEL_SPEC,
    ) -> None:
        """初始化 YOLO26 detection 训练任务适配器。"""

        super().__init__(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
            spec=spec,
        )
