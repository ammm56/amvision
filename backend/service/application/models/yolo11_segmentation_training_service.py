"""YOLO11 segmentation 训练任务服务。"""

from backend.service.application.models.yolo_primary_segmentation_training_service import (
    YOLO_PRIMARY_SEGMENTATION_TRAINING_TASK_KIND as YOLO11_SEGMENTATION_TRAINING_TASK_KIND,
    YOLO_PRIMARY_SEGMENTATION_TRAINING_QUEUE_NAME as YOLO11_SEGMENTATION_TRAINING_QUEUE_NAME,
    SqlAlchemyYoloPrimarySegmentationTrainingTaskService as SqlAlchemyYolo11SegmentationTrainingTaskService,
    YoloPrimarySegmentationTrainingTaskRequest as Yolo11SegmentationTrainingTaskRequest,
)
