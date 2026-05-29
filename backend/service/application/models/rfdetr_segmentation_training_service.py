"""RF-DETR segmentation 训练任务服务。"""

from backend.service.application.models.yolo_primary_segmentation_training_service import (
    YOLO_PRIMARY_SEGMENTATION_TRAINING_QUEUE_NAME as RFDETR_SEGMENTATION_TRAINING_QUEUE_NAME,
    YOLO_PRIMARY_SEGMENTATION_TRAINING_TASK_KIND as RFDETR_SEGMENTATION_TRAINING_TASK_KIND,
    SqlAlchemyYoloPrimarySegmentationTrainingTaskService as SqlAlchemyRfdetrSegmentationTrainingTaskService,
    YoloPrimarySegmentationTrainingTaskRequest as RfdetrSegmentationTrainingTaskRequest,
)
