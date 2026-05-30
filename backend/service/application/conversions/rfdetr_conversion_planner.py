"""RF-DETR 转换规划器。"""

from __future__ import annotations

from backend.service.application.models.rfdetr_model_service import (
    RFDETR_DETECTION_FILE_TYPES,
)
from backend.service.domain.models.rfdetr_model_spec import (
    RFDETR_SUPPORTED_TASKS,
)
from backend.service.application.conversions.yolox_conversion_planner import DefaultYoloXConversionPlanner


class DefaultRfdetrConversionPlanner(DefaultYoloXConversionPlanner):
    """RF-DETR 转换规划器。复用标准转换规划。"""

    model_type = "rfdetr"

    def __init__(self) -> None:
        """初始化 RF-DETR 转换规划器。"""

        super().__init__(
            file_types=RFDETR_DETECTION_FILE_TYPES,
            supported_task_types=RFDETR_SUPPORTED_TASKS,
        )
