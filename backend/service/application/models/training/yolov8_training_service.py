"""YOLOv8 detection 训练任务适配器。"""

from __future__ import annotations

from backend.service.application.models.training.yolov8_detection_training import (
    YoloV8DetectionTrainingExecutionRequest,
    YOLOV8_IMPLEMENTATION_MODE,
    run_yolov8_detection_training,
)
from backend.service.application.models.training.yolo_detection_training_service import (
    SqlAlchemyYoloDetectionTrainingTaskService,
    YoloDetectionTrainingTaskRequest as YoloV8TrainingTaskRequest,
    YoloDetectionTrainingTaskResult as YoloV8TrainingTaskResult,
    YoloDetectionTrainingTaskSubmission as YoloV8TrainingTaskSubmission,
)
from backend.service.application.models.registry.yolov8_model_service import (
    SqlAlchemyYoloV8ModelService,
    YoloV8TrainingOutputRegistration,
)
from backend.service.domain.files.detection_model_file_types import (
    YOLOV8_DETECTION_FILE_TYPES,
)
from backend.service.domain.models.yolov8_model_spec import (
    DEFAULT_YOLOV8_MODEL_SPEC,
)
from backend.service.domain.tasks.yolov8_task_specs import YoloV8TrainingTaskSpec


YOLOV8_TRAINING_TASK_KIND = "yolov8-training"
YOLOV8_TRAINING_QUEUE_NAME = "yolov8-trainings"


class SqlAlchemyYoloV8TrainingTaskService(SqlAlchemyYoloDetectionTrainingTaskService):
    """YOLOv8 detection 训练任务正式入口。"""

    model_type = "yolov8"
    model_label = "YOLOv8"
    training_task_kind = YOLOV8_TRAINING_TASK_KIND
    training_queue_name = YOLOV8_TRAINING_QUEUE_NAME
    model_service_cls = SqlAlchemyYoloV8ModelService
    output_registration_cls = YoloV8TrainingOutputRegistration
    task_spec_cls = YoloV8TrainingTaskSpec
    request_cls = YoloV8TrainingTaskRequest
    task_result_cls = YoloV8TrainingTaskResult
    execution_request_cls = YoloV8DetectionTrainingExecutionRequest
    training_runner = staticmethod(run_yolov8_detection_training)
    implementation_mode = YOLOV8_IMPLEMENTATION_MODE
    file_types = YOLOV8_DETECTION_FILE_TYPES
    default_spec = DEFAULT_YOLOV8_MODEL_SPEC


__all__ = [
    "YOLOV8_TRAINING_TASK_KIND",
    "YOLOV8_TRAINING_QUEUE_NAME",
    "YoloV8TrainingTaskRequest",
    "YoloV8TrainingTaskSubmission",
    "YoloV8TrainingTaskResult",
    "SqlAlchemyYoloV8TrainingTaskService",
]
