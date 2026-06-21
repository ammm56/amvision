"""YOLOv8 detection 转换任务应用服务。"""

from __future__ import annotations

from backend.service.application.conversions.yolo_model_conversion_task_service import (
    SqlAlchemyYoloModelConversionTaskService,
    YoloConversionBuildSummary as YoloV8ConversionBuildSummary,
    YoloConversionResultSnapshot as YoloV8ConversionResultSnapshot,
    YoloConversionTaskRequest as YoloV8ConversionTaskRequest,
    YoloConversionTaskResult as YoloV8ConversionTaskResult,
    YoloConversionTaskSubmission as YoloV8ConversionTaskSubmission,
    YoloModelConversionRunRequest as YoloV8ConversionRunRequest,
)
from backend.service.application.conversions.yolov8_conversion_planner import (
    DefaultYoloV8ConversionPlanner,
    YoloV8ConversionPlanner,
    YoloV8ConversionPlanningRequest,
    deserialize_yolov8_conversion_plan,
    serialize_yolov8_conversion_plan,
)
from backend.service.application.models.registry.yolov8_model_service import (
    SqlAlchemyYoloV8ModelService,
    YoloV8BuildRegistration,
)
from backend.service.application.runtime.targets.yolov8 import (
    SqlAlchemyYoloV8RuntimeTargetResolver,
)


YOLOV8_CONVERSION_TASK_KIND = "yolov8-conversion"
YOLOV8_CONVERSION_QUEUE_NAME = "yolov8-conversions"


class SqlAlchemyYoloV8ConversionTaskService(SqlAlchemyYoloModelConversionTaskService):
    """基于 YOLO 系列共享链路实现的 YOLOv8 转换任务服务。"""

    model_type = "yolov8"
    model_label = "YOLOv8"
    task_kind = YOLOV8_CONVERSION_TASK_KIND
    queue_name = YOLOV8_CONVERSION_QUEUE_NAME
    planning_request_cls = YoloV8ConversionPlanningRequest
    runtime_target_resolver_cls = SqlAlchemyYoloV8RuntimeTargetResolver
    model_service_cls = SqlAlchemyYoloV8ModelService
    build_registration_cls = YoloV8BuildRegistration
    build_summary_cls = YoloV8ConversionBuildSummary
    request_cls = YoloV8ConversionTaskRequest
    result_cls = YoloV8ConversionTaskResult
    serialize_plan = staticmethod(serialize_yolov8_conversion_plan)
    deserialize_plan = staticmethod(deserialize_yolov8_conversion_plan)

    def __init__(self, *args, planner: YoloV8ConversionPlanner | None = None, **kwargs) -> None:
        """初始化 YOLOv8 转换任务服务。"""

        super().__init__(*args, planner=planner or DefaultYoloV8ConversionPlanner(), **kwargs)


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
