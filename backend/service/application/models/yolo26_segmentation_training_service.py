"""YOLO26 segmentation 训练任务服务。"""

from backend.service.application.models.yolo_primary_segmentation_training_service import (
    YOLO_PRIMARY_SEGMENTATION_TRAINING_TASK_KIND as YOLO26_SEGMENTATION_TRAINING_TASK_KIND,
    YOLO_PRIMARY_SEGMENTATION_TRAINING_QUEUE_NAME as YOLO26_SEGMENTATION_TRAINING_QUEUE_NAME,
    SqlAlchemyYoloPrimarySegmentationTrainingTaskService as SqlAlchemyYolo26SegmentationTrainingTaskService,
    YoloPrimarySegmentationTrainingTaskRequest as Yolo26SegmentationTrainingTaskRequest,
)
