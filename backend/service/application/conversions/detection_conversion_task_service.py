"""detection conversion 共享任务服务基础类型。"""

from __future__ import annotations

from backend.service.application.conversions.yolox_conversion_task_service import (
    SqlAlchemyYoloXConversionTaskService as SqlAlchemyDetectionConversionTaskService,
    YoloXBuildRegistration as DetectionBuildRegistration,
    YoloXConversionBuildSummary as DetectionConversionBuildSummary,
    YoloXConversionResultSnapshot as DetectionConversionResultSnapshot,
    YoloXConversionRunRequest as DetectionConversionRunRequest,
    YoloXConversionTaskRequest as DetectionConversionTaskRequest,
    YoloXConversionTaskResult as DetectionConversionTaskResult,
    YoloXConversionTaskSubmission as DetectionConversionTaskSubmission,
    _deserialize_task_spec as deserialize_detection_conversion_task_spec,
    _serialize_build_summary as serialize_detection_conversion_build_summary,
    _serialize_task_spec as serialize_detection_conversion_task_spec,
)


__all__ = [
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

