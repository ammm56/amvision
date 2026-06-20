"""YOLO11 detection 训练任务适配器。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.queue import QueueBackend
from backend.service.application.models.yolo11_detection_training import (
    YOLO11_IMPLEMENTATION_MODE,
    Yolo11DetectionTrainingExecutionRequest,
    run_yolo11_detection_training,
)
from backend.service.application.models.yolo11_model_service import (
    SqlAlchemyYolo11ModelService,
    Yolo11TrainingOutputRegistration,
)
from backend.service.application.models.yolo_detection_training_service import (
    SqlAlchemyYoloDetectionTrainingTaskService,
)
from backend.service.domain.files.detection_model_file_types import (
    YOLO11_DETECTION_FILE_TYPES,
)
from backend.service.domain.models.yolo11_model_spec import (
    DEFAULT_YOLO11_MODEL_SPEC,
    Yolo11ModelSpec,
)
from backend.service.domain.tasks.yolo11_task_specs import Yolo11TrainingTaskSpec
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


YOLO11_TRAINING_TASK_KIND = "yolo11-training"
YOLO11_TRAINING_QUEUE_NAME = "yolo11-trainings"


@dataclass(frozen=True)
class Yolo11TrainingTaskRequest:
    """描述一次 YOLO11 detection 训练任务创建请求。"""

    project_id: str
    recipe_id: str
    model_scale: str
    output_model_name: str
    dataset_export_id: str | None = None
    dataset_export_manifest_key: str | None = None
    warm_start_model_version_id: str | None = None
    evaluation_interval: int | None = None
    max_epochs: int | None = None
    batch_size: int | None = None
    gpu_count: int | None = None
    precision: str | None = None
    input_size: tuple[int, int] | None = None
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Yolo11TrainingTaskResult:
    """描述一次 YOLO11 detection 训练任务处理结果。"""

    task_id: str
    status: str
    dataset_export_id: str
    dataset_export_manifest_key: str
    dataset_version_id: str
    format_id: str
    output_object_prefix: str
    checkpoint_object_key: str
    latest_checkpoint_object_key: str | None = None
    labels_object_key: str | None = None
    metrics_object_key: str | None = None
    validation_metrics_object_key: str | None = None
    summary_object_key: str | None = None
    best_metric_name: str | None = None
    best_metric_value: float | None = None
    summary: dict[str, object] = field(default_factory=dict)


class SqlAlchemyYolo11TrainingTaskService(SqlAlchemyYoloDetectionTrainingTaskService):
    """基于 detection 训练任务模板的 YOLO11 训练任务适配器。"""

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
    implementation_mode = YOLO11_IMPLEMENTATION_MODE
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
