"""YOLOv8 detection 训练任务适配器。"""

from __future__ import annotations

from backend.service.application.models.yolov8_detection_training import (
    YOLOV8_BOOTSTRAP_IMPLEMENTATION_MODE,
)
from backend.service.application.models.yolo_primary_training_service import (
    YOLO_PRIMARY_TRAINING_QUEUE_NAME as YOLOV8_TRAINING_QUEUE_NAME,
    YOLO_PRIMARY_TRAINING_TASK_KIND as YOLOV8_TRAINING_TASK_KIND,
    SqlAlchemyYoloPrimaryTrainingTaskService,
    YoloPrimaryTrainingTaskRequest as YoloV8TrainingTaskRequest,
    YoloPrimaryTrainingTaskResult as YoloV8TrainingTaskResult,
    YoloPrimaryTrainingTaskSubmission as YoloV8TrainingTaskSubmission,
)


class SqlAlchemyYoloV8TrainingTaskService(SqlAlchemyYoloPrimaryTrainingTaskService):
    """YOLOv8 detection 训练任务正式入口。"""

    implementation_mode = YOLOV8_BOOTSTRAP_IMPLEMENTATION_MODE


__all__ = [
    "YOLOV8_TRAINING_TASK_KIND",
    "YOLOV8_TRAINING_QUEUE_NAME",
    "YoloV8TrainingTaskRequest",
    "YoloV8TrainingTaskSubmission",
    "YoloV8TrainingTaskResult",
    "SqlAlchemyYoloV8TrainingTaskService",
]
