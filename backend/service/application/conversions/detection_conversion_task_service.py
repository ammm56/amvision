"""detection conversion 共享任务服务基础类型。"""

from __future__ import annotations

from backend.service.application.conversions.yolox_conversion_task_service import (
    YOLOX_CONVERSION_QUEUE_NAME as DETECTION_CONVERSION_QUEUE_NAME,
    SqlAlchemyYoloXConversionTaskService as SqlAlchemyDetectionConversionTaskService,
    YOLOX_CONVERSION_TASK_KIND as DETECTION_CONVERSION_TASK_KIND,
    YoloXConversionBuildSummary as DetectionConversionBuildSummary,
    YoloXConversionResultSnapshot as DetectionConversionResultSnapshot,
    YoloXConversionRunRequest as DetectionConversionRunRequest,
    YoloXConversionTaskRequest as DetectionConversionTaskRequest,
    YoloXConversionTaskResult as DetectionConversionTaskResult,
    YoloXConversionTaskSubmission as DetectionConversionTaskSubmission,
    ModelBuildRegistration as DetectionBuildRegistration,
    _deserialize_task_spec as deserialize_detection_conversion_task_spec,
    _serialize_build_summary as serialize_detection_conversion_build_summary,
    _serialize_task_spec as serialize_detection_conversion_task_spec,
)


__all__ = [
    "DETECTION_CONVERSION_QUEUE_NAME",
    "DETECTION_CONVERSION_TASK_KIND",
    "DetectionBuildRegistration",
    "DetectionConversionBuildSummary",
    "DetectionConversionResultSnapshot",
    "DetectionConversionRunRequest",
    "DetectionConversionTaskRequest",
    "DetectionConversionTaskResult",
    "DetectionConversionTaskSubmission",
    "SqlAlchemyDetectionConversionTaskService",
    "deserialize_detection_conversion_task_spec",
    "serialize_detection_conversion_build_summary",
    "serialize_detection_conversion_task_spec",
]
