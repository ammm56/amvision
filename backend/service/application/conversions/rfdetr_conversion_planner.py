"""RF-DETR 转换规划器。"""

from __future__ import annotations
from backend.service.application.conversions.yolox_conversion_planner import DefaultYoloXConversionPlanner


class DefaultRfdetrConversionPlanner(DefaultYoloXConversionPlanner):
    """RF-DETR 转换规划器。复用标准转换规划。"""

    model_type = "rfdetr"
