"""YOLO11 detection 训练任务适配器。"""

from __future__ import annotations

from backend.service.application.models.yolo11_detection_training import (
    Yolo11DetectionTrainingExecutionRequest,
    run_yolo11_detection_training,
)
from backend.service.application.models.yolo11_model_service import (
    SqlAlchemyYolo11ModelService,
    Yolo11TrainingOutputRegistration,
)
from backend.service.application.models.yolo_primary_training_service import (
    SqlAlchemyYoloPrimaryTrainingTaskService,
    YoloPrimaryTrainingTaskRequest as Yolo11TrainingTaskRequest,
    YoloPrimaryTrainingTaskResult as Yolo11TrainingTaskResult,
    YoloPrimaryTrainingTaskSubmission as Yolo11TrainingTaskSubmission,
)
from backend.service.domain.files.detection_model_file_types import YOLO11_DETECTION_FILE_TYPES
from backend.service.domain.models.yolo11_model_spec import (
    DEFAULT_YOLO11_MODEL_SPEC,
    Yolo11ModelSpec,
)
from backend.service.domain.tasks.yolo11_task_specs import Yolo11TrainingTaskSpec
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.queue import QueueBackend


YOLO11_TRAINING_TASK_KIND = "yolo11-training"
YOLO11_TRAINING_QUEUE_NAME = "yolo11-trainings"


class SqlAlchemyYolo11TrainingTaskService(SqlAlchemyYoloPrimaryTrainingTaskService):
    """基于 detection 公共训练链的 YOLO11 训练任务适配器。"""

    model_type = "yolo11"
    model_label = "YOLO11"
    training_task_kind = YOLO11_TRAINING_TASK_KIND
    training_queue_name = YOLO11_TRAINING_QUEUE_NAME
    model_service_cls = SqlAlchemyYolo11ModelService
    output_registration_cls = Yolo11TrainingOutputRegistration
    task_spec_cls = Yolo11TrainingTaskSpec
    request_cls = Yolo11TrainingTaskRequest
    task_result_cls = Yolo11TrainingTaskResult
    execution_request_cls = Yolo11DetectionTrainingExecutionRequest
    training_runner = staticmethod(run_yolo11_detection_training)
    file_types = YOLO11_DETECTION_FILE_TYPES

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage | None = None,
        queue_backend: QueueBackend | None = None,
        spec: Yolo11ModelSpec = DEFAULT_YOLO11_MODEL_SPEC,
    ) -> None:
        """初始化 YOLO11 detection 训练任务适配器。"""

        super().__init__(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            queue_backend=queue_backend,
            spec=spec,
        )
