"""YOLO 主线 segmentation head。"""

from __future__ import annotations

import copy

import torch
from torch import nn

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.decode import (
    build_detection_prediction,
)
from backend.service.application.models.yolo_core_common.layers import Conv
from backend.service.application.models.yolo_core_common.tasks.detection import Detect


class Proto(nn.Module):
    """实例分割使用的原型 mask 生成头。"""

    def __init__(self, c1: int, c_: int = 256, c2: int = 32) -> None:
        """初始化分割 proto 头。"""

        super().__init__()
        self.cv1 = Conv(c1, c_, 3)
        self.upsample = nn.ConvTranspose2d(c_, c_, 2, 2, 0, bias=True)
        self.cv2 = Conv(c_, c_, 3)
        self.cv3 = Conv(c_, c2, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """根据高分辨率特征图生成原型 mask。"""

        return self.cv3(self.cv2(self.upsample(self.cv1(x))))


class Segment(Detect):
    """YOLO 实例分割头的项目内实现。"""

    def __init__(
        self,
        nc: int,
        nm: int,
        npr: int,
        ch: tuple[int, ...],
        *,
        reg_max: int = 16,
        strides: tuple[int, ...] = (8, 16, 32),
        end2end: bool = False,
        legacy_class_head: bool = False,
    ) -> None:
        """初始化分割头。"""

        super().__init__(
            nc,
            ch,
            reg_max=reg_max,
            strides=strides,
            end2end=end2end,
            legacy_class_head=legacy_class_head,
        )
        self.nm = int(nm)
        self.npr = int(npr)
        self.proto = Proto(ch[0], self.npr, self.nm)
        hidden_channels = max(ch[0] // 4, self.nm)
        self.cv4 = nn.ModuleList(
            nn.Sequential(
                Conv(input_channels, hidden_channels, 3),
                Conv(hidden_channels, hidden_channels, 3),
                nn.Conv2d(hidden_channels, self.nm, 1),
            )
            for input_channels in ch
        )
        if self.end2end:
            self.one2one_cv4 = copy.deepcopy(self.cv4)

    def forward(
        self,
        x: list[torch.Tensor] | tuple[torch.Tensor, ...],
    ) -> dict[str, torch.Tensor] | tuple[torch.Tensor, torch.Tensor]:
        """执行实例分割头前向。"""

        if not isinstance(x, list | tuple) or len(x) != self.nl:
            raise InvalidRequestError(
                "Segment 头收到的特征层数量不合法",
                details={"expected_feature_count": self.nl},
            )
        proto = self.proto(x[0])
        raw_outputs = self._build_head_outputs(
            x,
            box_head=self.cv2,
            class_head=self.cv3,
            extra_head=self.cv4,
            extra_key="mask_coefficients",
            extra_channels=self.nm,
        )
        if self.end2end:
            detached_inputs = [feature.detach() for feature in x]
            one2one_outputs = self._build_head_outputs(
                detached_inputs,
                box_head=self.one2one_cv2,
                class_head=self.one2one_cv3,
                extra_head=self.one2one_cv4,
                extra_key="mask_coefficients",
                extra_channels=self.nm,
            )
            raw_outputs = {
                "one2many": raw_outputs,
                "one2one": one2one_outputs,
            }
        if self.training:
            if self.end2end:
                raw_outputs["one2many"]["proto"] = proto
                raw_outputs["one2one"]["proto"] = proto.detach()
            else:
                raw_outputs["proto"] = proto
            return raw_outputs

        if self.end2end:
            inference_outputs = raw_outputs["one2one"]
        else:
            inference_outputs = raw_outputs
        prediction = build_detection_prediction(
            raw_outputs=inference_outputs,
            strides=self.strides,
            dfl_decoder=self.dfl,
        )
        prediction = torch.cat((prediction, inference_outputs["mask_coefficients"]), dim=1)
        return prediction.transpose(1, 2).contiguous(), proto
