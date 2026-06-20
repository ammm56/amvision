"""YOLO 系列 conversion 共享任务服务。"""

from __future__ import annotations

from typing import Callable

from backend.service.application.conversions.yolo_conversion_task_service_base import (
    SqlAlchemyYoloConversionTaskServiceBase,
    YoloConversionBuildSummary,
    YoloConversionResultSnapshot,
    YoloConversionTaskRequest,
    YoloConversionTaskResult,
    YoloConversionTaskSubmission,
)
from backend.workers.conversion.yolo_model_conversion_runner import (
    YoloModelConversionRunRequest,
)


YOLO_MODEL_CONVERSION_TASK_KIND = "yolo-model-conversion"
YOLO_MODEL_CONVERSION_QUEUE_NAME = "yolo-model-conversions"
_YOLO_MODEL_EXECUTABLE_TARGET_FORMATS = frozenset(
    {"onnx", "onnx-optimized", "openvino-ir", "tensorrt-engine"}
)


class SqlAlchemyYoloModelConversionTaskService(SqlAlchemyYoloConversionTaskServiceBase):
    """基于共享基类实现的 YOLO 系列转换任务服务。"""

    model_type = "yolo-model"
    model_label = "YOLO model"
    task_kind = YOLO_MODEL_CONVERSION_TASK_KIND
    queue_name = YOLO_MODEL_CONVERSION_QUEUE_NAME
    executable_target_formats = _YOLO_MODEL_EXECUTABLE_TARGET_FORMATS
    planning_request_cls: type | None = None
    runtime_target_resolver_cls: type | None = None
    model_service_cls: type | None = None
    build_registration_cls: type | None = None
    build_summary_cls = YoloConversionBuildSummary
    request_cls = YoloConversionTaskRequest
    result_cls = YoloConversionTaskResult
    serialize_plan: Callable[[object], dict[str, object]] | None = None
    deserialize_plan: Callable[[object], object] | None = None

    def __init__(self, *args, planner: object, **kwargs) -> None:
        """初始化 YOLO 系列转换任务服务。"""

        super().__init__(*args, planner=planner, **kwargs)


__all__ = [
    "SqlAlchemyYoloModelConversionTaskService",
    "YoloConversionBuildSummary",
    "YoloConversionResultSnapshot",
    "YoloConversionTaskRequest",
    "YoloConversionTaskResult",
    "YoloConversionTaskSubmission",
    "YoloModelConversionRunRequest",
]
