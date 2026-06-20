"""YOLO11 segmentation head。"""

from __future__ import annotations

import copy

import torch
from torch import nn

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.layers import Conv
from backend.service.application.models.yolo11_core.nn.tasks.detection import Detect


class Proto(nn.Module):
    """YOLO11 实例分割使用的原型 mask 生成头。"""

    def __init__(self, c1: int, c_: int = 256, c2: int = 32) -> None:
        """初始化 YOLO11 segmentation proto 头。"""

        super().__init__()
        self.cv1 = Conv(c1, c_, 3)
        self.upsample = nn.ConvTranspose2d(c_, c_, 2, 2, 0, bias=True)
        self.cv2 = Conv(c_, c_, 3)
        self.cv3 = Conv(c_, c2, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """根据高分辨率特征图生成原型 mask。"""

        return self.cv3(self.cv2(self.upsample(self.cv1(x))))


class Segment(Detect):
    """YOLO11 segmentation head 的项目内 full core 实现。"""

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
        """初始化 YOLO11 segmentation head。"""

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

    @property
    def one2many(self) -> dict[str, nn.ModuleList]:
        """返回 YOLO11 segmentation one-to-many head 组件。"""

        return {"box_head": self.cv2, "class_head": self.cv3, "mask_head": self.cv4}

    @property
    def one2one(self) -> dict[str, nn.ModuleList]:
        """返回 YOLO11 segmentation one-to-one head 组件。"""

        return {
            "box_head": self.one2one_cv2,
            "class_head": self.one2one_cv3,
            "mask_head": self.one2one_cv4,
        }

    def forward(
        self,
        x: list[torch.Tensor] | tuple[torch.Tensor, ...],
    ) -> dict[str, torch.Tensor] | tuple[torch.Tensor, torch.Tensor]:
        """执行 YOLO11 segmentation head 前向。"""

        if not isinstance(x, list | tuple) or len(x) != self.nl:
            raise InvalidRequestError(
                "YOLO11 Segment 头收到的特征层数量不合法",
                details={"expected_feature_count": self.nl},
            )
        outputs = super().forward(x)
        raw_outputs = outputs[1] if isinstance(outputs, tuple) else outputs
        proto = self.proto(x[0])
        if self.training:
            if self.end2end:
                raw_outputs["one2many"]["proto"] = proto
                raw_outputs["one2one"]["proto"] = proto.detach()
            else:
                raw_outputs["proto"] = proto
            return raw_outputs
        return (outputs, proto) if self.export else (outputs, proto)

    def _inference(self, raw_outputs: dict[str, torch.Tensor]) -> torch.Tensor:
        """按 Ultralytics Segment 推理路径拼接 detection 输出和 mask coefficients。"""

        prediction = super()._inference(raw_outputs)
        return torch.cat((prediction, raw_outputs["mask_coefficients"]), dim=1)

    def forward_head(
        self,
        x: list[torch.Tensor] | tuple[torch.Tensor, ...],
        *,
        box_head: nn.ModuleList,
        class_head: nn.ModuleList,
        mask_head: nn.ModuleList | None = None,
    ) -> dict[str, torch.Tensor]:
        """按 Ultralytics Segment.forward_head 组装 box / class / mask 原始输出。"""

        output_bundle = super().forward_head(
            x,
            box_head=box_head,
            class_head=class_head,
        )
        if mask_head is None:
            return output_bundle
        batch_size = x[0].shape[0]
        output_bundle["mask_coefficients"] = torch.cat(
            [
                mask_head[index](feature).view(batch_size, self.nm, -1)
                for index, feature in enumerate(x)
            ],
            dim=2,
        )
        return output_bundle
