"""YOLO26 OBB head。"""

from backend.service.application.models.yolo_core_common.decode import (
    OBB_ANGLE_DECODE_MODE_RAW,
)
from backend.service.application.models.yolo_core_common.tasks.obb import OBB


class OBB26(OBB):
    """YOLO26 旋转框头当前阶段保留原始角度输出。"""

    angle_decode_mode = OBB_ANGLE_DECODE_MODE_RAW
