"""YOLO26 模型转换规划适配器。"""

from __future__ import annotations

from backend.service.application.conversions.yolox_conversion_planner import (
    DefaultYoloXConversionPlanner,
    YoloXConversionPlan as Yolo26ConversionPlan,
    YoloXConversionPlanner as Yolo26ConversionPlanner,
    YoloXConversionPlanningRequest as Yolo26ConversionPlanningRequest,
    YoloXConversionStep as Yolo26ConversionStep,
    deserialize_yolox_conversion_plan as deserialize_yolo26_conversion_plan,
    deserialize_yolox_conversion_step as deserialize_yolo26_conversion_step,
    serialize_yolox_conversion_plan as serialize_yolo26_conversion_plan,
    serialize_yolox_conversion_step as serialize_yolo26_conversion_step,
)
from backend.service.domain.files.detection_model_file_types import YOLO26_DETECTION_FILE_TYPES
from backend.service.domain.models.yolo26_model_spec import DEFAULT_YOLO26_MODEL_SPEC


class DefaultYolo26ConversionPlanner(DefaultYoloXConversionPlanner):
    """使用共用转换图谱的 YOLO26 规划器。"""

    def __init__(self) -> None:
        """初始化 YOLO26 转换规划器。"""

        super().__init__(
            file_types=YOLO26_DETECTION_FILE_TYPES,
            supported_task_types=DEFAULT_YOLO26_MODEL_SPEC.supported_tasks,
        )
