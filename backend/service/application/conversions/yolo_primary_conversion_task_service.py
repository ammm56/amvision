"""YOLO primary conversion 兼容导入层。"""

from __future__ import annotations

from backend.service.application.conversions.yolo_model_conversion_task_service import (
    SqlAlchemyYoloModelConversionTaskService,
    YoloConversionBuildSummary as YoloPrimaryConversionBuildSummary,
    YoloConversionResultSnapshot as YoloPrimaryConversionResultSnapshot,
    YoloConversionTaskRequest as YoloPrimaryConversionTaskRequest,
    YoloConversionTaskResult as YoloPrimaryConversionTaskResult,
    YoloConversionTaskSubmission as YoloPrimaryConversionTaskSubmission,
    YoloModelConversionRunRequest as YoloPrimaryConversionRunRequest,
)


YOLO_PRIMARY_CONVERSION_TASK_KIND = "yolo-primary-conversion"
YOLO_PRIMARY_CONVERSION_QUEUE_NAME = "yolo-primary-conversions"


class SqlAlchemyYoloPrimaryConversionTaskService(SqlAlchemyYoloModelConversionTaskService):
    """保留给旧内部导入使用的 YOLO primary 转换任务服务。"""

    model_type = "yolo-primary"
    model_label = "YOLO primary"
    task_kind = YOLO_PRIMARY_CONVERSION_TASK_KIND
    queue_name = YOLO_PRIMARY_CONVERSION_QUEUE_NAME
    build_summary_cls = YoloPrimaryConversionBuildSummary
    request_cls = YoloPrimaryConversionTaskRequest
    result_cls = YoloPrimaryConversionTaskResult


__all__ = [
    "SqlAlchemyYoloPrimaryConversionTaskService",
    "YoloPrimaryConversionBuildSummary",
    "YoloPrimaryConversionResultSnapshot",
    "YoloPrimaryConversionRunRequest",
    "YoloPrimaryConversionTaskRequest",
    "YoloPrimaryConversionTaskResult",
    "YoloPrimaryConversionTaskSubmission",
]
