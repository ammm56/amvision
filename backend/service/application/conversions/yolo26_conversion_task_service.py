"""YOLO26 detection 转换任务应用服务。"""

from __future__ import annotations

from backend.service.application.conversions.yolo26_conversion_planner import (
    DefaultYolo26ConversionPlanner,
    Yolo26ConversionPlanner,
    Yolo26ConversionPlanningRequest,
    deserialize_yolo26_conversion_plan,
    serialize_yolo26_conversion_plan,
)
from backend.service.application.conversions.yolo_model_conversion_task_service import (
    SqlAlchemyYoloModelConversionTaskService,
    YoloConversionBuildSummary as Yolo26ConversionBuildSummary,
    YoloConversionTaskRequest as Yolo26ConversionTaskRequest,
    YoloConversionTaskResult as Yolo26ConversionTaskResult,
)
from backend.service.application.models.registry.yolo26_model_service import (
    SqlAlchemyYolo26ModelService,
    Yolo26BuildRegistration,
)
from backend.service.application.runtime.targets.yolo26 import (
    SqlAlchemyYolo26RuntimeTargetResolver,
)


YOLO26_CONVERSION_TASK_KIND = "yolo26-conversion"
YOLO26_CONVERSION_QUEUE_NAME = "yolo26-conversions"


class SqlAlchemyYolo26ConversionTaskService(SqlAlchemyYoloModelConversionTaskService):
    """基于 YOLO 系列共享链路实现的 YOLO26 转换任务服务。"""

    model_type = "yolo26"
    model_label = "YOLO26"
    task_kind = YOLO26_CONVERSION_TASK_KIND
    queue_name = YOLO26_CONVERSION_QUEUE_NAME
    planning_request_cls = Yolo26ConversionPlanningRequest
    runtime_target_resolver_cls = SqlAlchemyYolo26RuntimeTargetResolver
    model_service_cls = SqlAlchemyYolo26ModelService
    build_registration_cls = Yolo26BuildRegistration
    build_summary_cls = Yolo26ConversionBuildSummary
    request_cls = Yolo26ConversionTaskRequest
    result_cls = Yolo26ConversionTaskResult
    serialize_plan = staticmethod(serialize_yolo26_conversion_plan)
    deserialize_plan = staticmethod(deserialize_yolo26_conversion_plan)

    def __init__(self, *args, planner: Yolo26ConversionPlanner | None = None, **kwargs) -> None:
        """初始化 YOLO26 转换任务服务。"""

        super().__init__(*args, planner=planner or DefaultYolo26ConversionPlanner(), **kwargs)
