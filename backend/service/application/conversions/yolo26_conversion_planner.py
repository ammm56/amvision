"""YOLO26 detection 转换规划适配器。"""

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


class DefaultYolo26ConversionPlanner(DefaultYoloXConversionPlanner):
    """使用 detection 共用转换图谱的 YOLO26 detection 规划器。"""

    def __init__(self) -> None:
        """初始化 YOLO26 detection 转换规划器。"""

        super().__init__(file_types=YOLO26_DETECTION_FILE_TYPES)
