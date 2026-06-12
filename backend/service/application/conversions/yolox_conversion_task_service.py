"""YOLOX 转换任务应用服务。"""

from __future__ import annotations

from backend.service.application.conversions.yolo_conversion_task_service_base import (
    SqlAlchemyYoloConversionTaskServiceBase,
    YoloConversionBuildSummary as YoloXConversionBuildSummary,
    YoloConversionResultSnapshot as YoloXConversionResultSnapshot,
    YoloConversionTaskRequest as YoloXConversionTaskRequest,
    YoloConversionTaskResult as YoloXConversionTaskResult,
    YoloConversionTaskSubmission as YoloXConversionTaskSubmission,
    _resolve_openvino_ir_build_precision,
    _resolve_tensorrt_engine_build_precision,
    deserialize_yolo_conversion_build_summary as _deserialize_build_summary,
    deserialize_yolo_conversion_task_spec as _deserialize_task_spec,
    serialize_yolo_conversion_build_summary as _serialize_build_summary,
    serialize_yolo_conversion_task_spec as _serialize_task_spec,
)
from backend.service.application.conversions.yolox_conversion_planner import (
    DefaultYoloXConversionPlanner,
    YoloXConversionPlan,
    YoloXConversionPlanner,
    YoloXConversionPlanningRequest,
    deserialize_yolox_conversion_plan,
    serialize_yolox_conversion_plan,
)
from backend.service.application.models.model_service import (
    ModelBuildRegistration,
    SqlAlchemyModelService,
)
from backend.service.application.runtime.runtime_target import (
    SqlAlchemyRuntimeTargetResolver,
)
from backend.workers.conversion.yolox_conversion_runner import (
    YoloXConversionOutput,
    YoloXConversionRunRequest,
    YoloXConversionRunResult,
)


YOLOX_CONVERSION_TASK_KIND = "yolox-conversion"
YOLOX_CONVERSION_QUEUE_NAME = "yolox-conversions"


class SqlAlchemyYoloXConversionTaskService(SqlAlchemyYoloConversionTaskServiceBase):
    """基于共享基类实现的 YOLOX 转换任务服务。"""

    model_type = "yolox"
    model_label = "YOLOX"
    task_kind = YOLOX_CONVERSION_TASK_KIND
    queue_name = YOLOX_CONVERSION_QUEUE_NAME
    planning_request_cls = YoloXConversionPlanningRequest
    runtime_target_resolver_cls = SqlAlchemyRuntimeTargetResolver
    model_service_cls = SqlAlchemyModelService
    build_registration_cls = ModelBuildRegistration
    build_summary_cls = YoloXConversionBuildSummary
    request_cls = YoloXConversionTaskRequest
    result_cls = YoloXConversionTaskResult
    serialize_plan = staticmethod(serialize_yolox_conversion_plan)
    deserialize_plan = staticmethod(deserialize_yolox_conversion_plan)

    def __init__(self, *args, planner: YoloXConversionPlanner | None = None, **kwargs) -> None:
        """初始化 YOLOX 转换任务服务。"""

        super().__init__(
            *args,
            planner=planner or DefaultYoloXConversionPlanner(),
            **kwargs,
        )


__all__ = [
    "YOLOX_CONVERSION_TASK_KIND",
    "YOLOX_CONVERSION_QUEUE_NAME",
    "YoloXConversionBuildSummary",
    "YoloXConversionOutput",
    "YoloXConversionPlan",
    "YoloXConversionResultSnapshot",
    "YoloXConversionRunRequest",
    "YoloXConversionRunResult",
    "YoloXConversionTaskRequest",
    "YoloXConversionTaskResult",
    "YoloXConversionTaskSubmission",
    "SqlAlchemyYoloXConversionTaskService",
    "_deserialize_build_summary",
    "_deserialize_task_spec",
    "_resolve_openvino_ir_build_precision",
    "_resolve_tensorrt_engine_build_precision",
    "_serialize_build_summary",
    "_serialize_task_spec",
]
