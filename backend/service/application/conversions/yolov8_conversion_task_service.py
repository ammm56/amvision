"""YOLOv8 detection 转换任务应用服务。"""

from __future__ import annotations

from backend.service.application.conversions.yolo_primary_conversion_task_service import (
    YOLO_PRIMARY_CONVERSION_QUEUE_NAME as YOLOV8_CONVERSION_QUEUE_NAME,
    YOLO_PRIMARY_CONVERSION_TASK_KIND as YOLOV8_CONVERSION_TASK_KIND,
    SqlAlchemyYoloPrimaryConversionTaskService as SqlAlchemyYoloV8ConversionTaskService,
    YoloPrimaryConversionBuildSummary as YoloV8ConversionBuildSummary,
    YoloPrimaryConversionResultSnapshot as YoloV8ConversionResultSnapshot,
    YoloPrimaryConversionRunRequest as YoloV8ConversionRunRequest,
    YoloPrimaryConversionTaskRequest as YoloV8ConversionTaskRequest,
    YoloPrimaryConversionTaskResult as YoloV8ConversionTaskResult,
    YoloPrimaryConversionTaskSubmission as YoloV8ConversionTaskSubmission,
)


__all__ = [
    "YOLOV8_CONVERSION_TASK_KIND",
    "YOLOV8_CONVERSION_QUEUE_NAME",
    "YoloV8ConversionTaskRequest",
    "YoloV8ConversionTaskSubmission",
    "YoloV8ConversionBuildSummary",
    "YoloV8ConversionTaskResult",
    "YoloV8ConversionResultSnapshot",
    "YoloV8ConversionRunRequest",
    "SqlAlchemyYoloV8ConversionTaskService",
]
