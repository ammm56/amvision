"""YOLOv8 obb 模型配置。"""

from __future__ import annotations

from backend.service.application.models.support.yolo_core_config_utils import clone_detection_variant
from backend.service.application.models.yolov8_core.cfg.detection import (
    YOLOV8_DETECTION_MODEL_CONFIG,
)


YOLOV8_OBB_MODEL_CONFIG: dict[str, object] = clone_detection_variant(
    YOLOV8_DETECTION_MODEL_CONFIG,
    head_module_name="OBB",
    head_args=("nc", 1),
)
