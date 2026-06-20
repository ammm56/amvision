"""YOLO11 detection 转换任务应用服务。"""

from __future__ import annotations

from backend.service.application.conversions.yolo11_conversion_planner import (
    DefaultYolo11ConversionPlanner,
    Yolo11ConversionPlanner,
    Yolo11ConversionPlanningRequest,
    deserialize_yolo11_conversion_plan,
    serialize_yolo11_conversion_plan,
)
from backend.service.application.conversions.yolo_primary_conversion_task_service import (
    SqlAlchemyYoloPrimaryConversionTaskService,
    YoloPrimaryConversionBuildSummary as Yolo11ConversionBuildSummary,
    YoloPrimaryConversionTaskRequest as Yolo11ConversionTaskRequest,
    YoloPrimaryConversionTaskResult as Yolo11ConversionTaskResult,
)
from backend.service.application.models.yolo11_model_service import (
    SqlAlchemyYolo11ModelService,
    Yolo11BuildRegistration,
)
from backend.service.application.runtime.targets.yolo11 import (
    SqlAlchemyYolo11RuntimeTargetResolver,
)


YOLO11_CONVERSION_TASK_KIND = "yolo11-conversion"
YOLO11_CONVERSION_QUEUE_NAME = "yolo11-conversions"


class SqlAlchemyYolo11ConversionTaskService(SqlAlchemyYoloPrimaryConversionTaskService):
    """基于 detection 公共链路实现的 YOLO11 转换任务服务。"""

    model_type = "yolo11"
    model_label = "YOLO11"
    task_kind = YOLO11_CONVERSION_TASK_KIND
    queue_name = YOLO11_CONVERSION_QUEUE_NAME
    planning_request_cls = Yolo11ConversionPlanningRequest
    runtime_target_resolver_cls = SqlAlchemyYolo11RuntimeTargetResolver
    model_service_cls = SqlAlchemyYolo11ModelService
    build_registration_cls = Yolo11BuildRegistration
    build_summary_cls = Yolo11ConversionBuildSummary
    request_cls = Yolo11ConversionTaskRequest
    result_cls = Yolo11ConversionTaskResult
    serialize_plan = staticmethod(serialize_yolo11_conversion_plan)
    deserialize_plan = staticmethod(deserialize_yolo11_conversion_plan)

    def __init__(self, *args, planner: Yolo11ConversionPlanner | None = None, **kwargs) -> None:
        """初始化 YOLO11 转换任务服务。"""

        super().__init__(*args, planner=planner or DefaultYolo11ConversionPlanner(), **kwargs)
