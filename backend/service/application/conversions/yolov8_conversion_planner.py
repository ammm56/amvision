"""YOLOv8 detection 转换规划适配器。"""

from __future__ import annotations

from backend.service.application.conversions.yolox_conversion_planner import (
    DefaultYoloXConversionPlanner,
    YoloXConversionPlan as YoloV8ConversionPlan,
    YoloXConversionPlanner as YoloV8ConversionPlanner,
    YoloXConversionPlanningRequest as YoloV8ConversionPlanningRequest,
    YoloXConversionStep as YoloV8ConversionStep,
    deserialize_yolox_conversion_plan as deserialize_yolov8_conversion_plan,
    deserialize_yolox_conversion_step as deserialize_yolov8_conversion_step,
    serialize_yolox_conversion_plan as serialize_yolov8_conversion_plan,
    serialize_yolox_conversion_step as serialize_yolov8_conversion_step,
)
from backend.service.domain.files.detection_model_file_types import YOLOV8_DETECTION_FILE_TYPES


class DefaultYoloV8ConversionPlanner(DefaultYoloXConversionPlanner):
    """使用 detection 共用转换图谱的 YOLOv8 detection 规划器。"""

    def __init__(self) -> None:
        """初始化 YOLOv8 detection 转换规划器。"""

        super().__init__(file_types=YOLOV8_DETECTION_FILE_TYPES)
