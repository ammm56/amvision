"""YOLO11 OBB head。"""

from __future__ import annotations

import copy

import torch
from torch import nn

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.decode import (
    OBB_ANGLE_DECODE_MODE_SIGMOID_MINUS_QUARTER_PI,
    build_obb_prediction,
)
from backend.service.application.models.yolo_core_common.layers import Conv
from backend.service.application.models.yolo11_core.nn.tasks.detection import Detect


class OBB(Detect):
    """YOLO11 OBB head 的项目内 full core 实现。"""

    angle_decode_mode = OBB_ANGLE_DECODE_MODE_SIGMOID_MINUS_QUARTER_PI

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
        """初始化 YOLO11 OBB head。"""

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
        """执行 YOLO11 OBB head 前向。"""

        if not isinstance(x, list | tuple) or len(x) != self.nl:
            raise InvalidRequestError(
                "YOLO11 OBB 头收到的特征层数量不合法",
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
            raw_outputs = {
                "one2many": raw_outputs,
                "one2one": self._build_head_outputs(
                    detached_inputs,
                    box_head=self.one2one_cv2,
                    class_head=self.one2one_cv3,
                    extra_head=self.one2one_cv4,
                    extra_key="angle",
                    extra_channels=self.ne,
                ),
            }
        if self.training:
            return raw_outputs
        inference_outputs = raw_outputs["one2one"] if self.end2end else raw_outputs
        prediction = build_obb_prediction(
            raw_outputs=inference_outputs,
            strides=self.strides,
            dfl_decoder=self.dfl,
            angle_decode_mode=self.angle_decode_mode,
        )
        return prediction.transpose(1, 2).contiguous()
