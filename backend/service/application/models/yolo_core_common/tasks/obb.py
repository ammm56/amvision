"""YOLO 主线 OBB head。"""

from __future__ import annotations

import copy
import math

import torch
from torch import nn

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.geometry import (
    dist2rbox,
    make_anchors,
)
from backend.service.application.models.yolo_core_common.layers import Conv
from backend.service.application.models.yolo_core_common.tasks.detection import Detect


class OBB(Detect):
    """YOLO 旋转框头的项目内实现。"""

    def __init__(
        self,
        nc: int,
        ne: int,
        ch: tuple[int, ...],
        *,
        reg_max: int = 16,
        strides: tuple[int, ...] = (8, 16, 32),
        end2end: bool = False,
        legacy_class_head: bool = False,
    ) -> None:
        """初始化旋转框头。"""

        super().__init__(
            nc,
            ch,
            reg_max=reg_max,
            strides=strides,
            end2end=end2end,
            legacy_class_head=legacy_class_head,
        )
        self.ne = int(ne)
        hidden_channels = max(ch[0] // 4, self.ne)
        self.cv4 = nn.ModuleList(
            nn.Sequential(
                Conv(input_channels, hidden_channels, 3),
                Conv(hidden_channels, hidden_channels, 3),
                nn.Conv2d(hidden_channels, self.ne, 1),
            )
            for input_channels in ch
        )
        if self.end2end:
            self.one2one_cv4 = copy.deepcopy(self.cv4)

    def forward(
        self,
        x: list[torch.Tensor] | tuple[torch.Tensor, ...],
    ) -> dict[str, torch.Tensor] | torch.Tensor:
        """执行旋转框头前向。"""

        if not isinstance(x, list | tuple) or len(x) != self.nl:
            raise InvalidRequestError(
                "OBB 头收到的特征层数量不合法",
                details={"expected_feature_count": self.nl},
            )
        raw_outputs = self._build_head_outputs(
            x,
            box_head=self.cv2,
            class_head=self.cv3,
            extra_head=self.cv4,
            extra_key="angle",
            extra_channels=self.ne,
        )
        if self.end2end:
            detached_inputs = [feature.detach() for feature in x]
            one2one_outputs = self._build_head_outputs(
                detached_inputs,
                box_head=self.one2one_cv2,
                class_head=self.one2one_cv3,
                extra_head=self.one2one_cv4,
                extra_key="angle",
                extra_channels=self.ne,
            )
            raw_outputs = {
                "one2many": raw_outputs,
                "one2one": one2one_outputs,
            }
        if self.training:
            return raw_outputs
        if self.end2end:
            inference_outputs = raw_outputs["one2one"]
        else:
            inference_outputs = raw_outputs
        dfl_distances = self.dfl(inference_outputs["boxes"])
        angle = self._decode_angle_logits(inference_outputs["angle"])
        anchor_points = make_anchors(
            feature_maps=inference_outputs["feats"],
            strides=self.strides,
        )[0]
        rbox = dist2rbox(dfl_distances, angle, anchor_points=anchor_points)
        class_scores = inference_outputs["scores"].sigmoid()
        prediction = torch.cat((rbox, class_scores, angle), dim=1)
        return prediction.transpose(1, 2).contiguous()

    def _decode_angle_logits(self, angle_logits: torch.Tensor) -> torch.Tensor:
        """把角度 logits 解码成旋转角。"""

        return (angle_logits.sigmoid() - 0.25) * math.pi
