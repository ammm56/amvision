"""YOLO26 OBB head。"""

from __future__ import annotations

import torch

from backend.service.application.models.yolo_core_common.tasks.obb import OBB


class OBB26(OBB):
    """YOLO26 旋转框头当前阶段保留原始角度输出。"""

    def _decode_angle_logits(self, angle_logits: torch.Tensor) -> torch.Tensor:
        """YOLO26 当前阶段返回原始角度分支输出。"""

        return angle_logits
