"""YOLO26 模型转换规划适配器。"""

from __future__ import annotations

from backend.service.application.conversions.yolo_model_conversion_planner import (
    DefaultYoloModelConversionPlanner,
    YoloModelConversionPlan as Yolo26ConversionPlan,
    YoloModelConversionPlanner as Yolo26ConversionPlanner,
    YoloModelConversionPlanningRequest as Yolo26ConversionPlanningRequest,
    YoloModelConversionStep as Yolo26ConversionStep,
    deserialize_yolo_model_conversion_plan as deserialize_yolo26_conversion_plan,
    deserialize_yolo_model_conversion_step as deserialize_yolo26_conversion_step,
    serialize_yolo_model_conversion_plan as serialize_yolo26_conversion_plan,
    serialize_yolo_model_conversion_step as serialize_yolo26_conversion_step,
)
from backend.service.domain.files.detection_model_file_types import YOLO26_DETECTION_FILE_TYPES
from backend.service.domain.models.yolo26_model_spec import DEFAULT_YOLO26_MODEL_SPEC


class DefaultYolo26ConversionPlanner(DefaultYoloModelConversionPlanner):
    """使用共用转换图谱的 YOLO26 规划器。"""

    def __init__(self) -> None:
        """初始化 YOLO26 转换规划器。"""

        super().__init__(
            file_types=YOLO26_DETECTION_FILE_TYPES,
            supported_task_types=DEFAULT_YOLO26_MODEL_SPEC.supported_tasks,
        )


__all__ = [
    "DefaultYolo26ConversionPlanner",
    "Yolo26ConversionPlan",
    "Yolo26ConversionPlanner",
    "Yolo26ConversionPlanningRequest",
    "Yolo26ConversionStep",
    "deserialize_yolo26_conversion_plan",
    "deserialize_yolo26_conversion_step",
    "serialize_yolo26_conversion_plan",
    "serialize_yolo26_conversion_step",
]
