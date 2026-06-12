"""YOLO 主线 conversion 共享适配层。"""

from __future__ import annotations

from typing import Callable

from backend.service.application.conversions.yolo_conversion_task_service_base import (
    SqlAlchemyYoloConversionTaskServiceBase,
    YoloConversionBuildSummary as YoloPrimaryConversionBuildSummary,
    YoloConversionResultSnapshot as YoloPrimaryConversionResultSnapshot,
    YoloConversionTaskRequest as YoloPrimaryConversionTaskRequest,
    YoloConversionTaskResult as YoloPrimaryConversionTaskResult,
    YoloConversionTaskSubmission as YoloPrimaryConversionTaskSubmission,
)
from backend.workers.conversion.yolox_conversion_runner import (
    YoloXConversionRunRequest as YoloPrimaryConversionRunRequest,
)


YOLO_PRIMARY_CONVERSION_TASK_KIND = "yolo-primary-conversion"
YOLO_PRIMARY_CONVERSION_QUEUE_NAME = "yolo-primary-conversions"
_YOLO_PRIMARY_EXECUTABLE_TARGET_FORMATS = frozenset(
    {"onnx", "onnx-optimized", "openvino-ir", "tensorrt-engine"}
)


class SqlAlchemyYoloPrimaryConversionTaskService(SqlAlchemyYoloConversionTaskServiceBase):
    """基于共享基类实现的 YOLO 主线转换任务服务。"""

    model_type = "yolo-primary"
    model_label = "YOLO primary"
    task_kind = YOLO_PRIMARY_CONVERSION_TASK_KIND
    queue_name = YOLO_PRIMARY_CONVERSION_QUEUE_NAME
    executable_target_formats = _YOLO_PRIMARY_EXECUTABLE_TARGET_FORMATS
    planning_request_cls: type | None = None
    runtime_target_resolver_cls: type | None = None
    model_service_cls: type | None = None
    build_registration_cls: type | None = None
    build_summary_cls = YoloPrimaryConversionBuildSummary
    request_cls = YoloPrimaryConversionTaskRequest
    result_cls = YoloPrimaryConversionTaskResult
    serialize_plan: Callable[[object], dict[str, object]] | None = None
    deserialize_plan: Callable[[object], object] | None = None

    def __init__(self, *args, planner: object, **kwargs) -> None:
        """初始化 YOLO 主线转换任务服务。"""

        super().__init__(*args, planner=planner, **kwargs)
