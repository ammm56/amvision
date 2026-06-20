"""YOLO26 segmentation head。"""

from __future__ import annotations

import torch
from torch import nn

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo26_core.decode import (
    build_yolo26_detection_prediction,
)
from backend.service.application.models.yolo26_core.nn.tasks.detection import Detect
from backend.service.application.models.yolo_core_common.layers import Conv


class Proto(nn.Module):
    """YOLO26 segmentation 使用的原型 mask 生成头。"""

    def __init__(self, c1: int, c_: int = 256, c2: int = 32) -> None:
        """初始化 YOLO26 proto 头。"""

        super().__init__()
        self.cv1 = Conv(c1, c_, 3)
        self.upsample = nn.ConvTranspose2d(c_, c_, 2, 2, 0, bias=True)
        self.cv2 = Conv(c_, c_, 3)
        self.cv3 = Conv(c_, c2, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """根据高分辨率特征图生成原型 mask。"""

        return self.cv3(self.cv2(self.upsample(self.cv1(x))))


class Proto26(Proto):
    """YOLO26 分割 proto 头，支持多尺度特征融合。"""

    def __init__(
        self,
        c_: int = 256,
        c2: int = 32,
        nc: int = 80,
        feature_channels: tuple[int, ...] = (),
    ) -> None:
        """初始化多尺度融合 proto 头。"""

        super().__init__(c_, c_, c2)
        base_feature_channels = feature_channels[0] if feature_channels else c_
        self.feat_refine = nn.ModuleList(
            [
                Conv(channels, base_feature_channels, k=1)
                for channels in feature_channels[1:]
            ]
        )
        self.feat_fuse = Conv(base_feature_channels, c_, k=3)
        self.semseg = nn.Sequential(
            Conv(base_feature_channels, c_, k=3),
            Conv(c_, c_, k=3),
            nn.Conv2d(c_, nc, 1),
        )

    def forward(self, x) -> torch.Tensor:
        """对多尺度特征图进行融合后生成 proto mask。"""

        if isinstance(x, list | tuple):
            feat = x[0]
            for index, refine_block in enumerate(self.feat_refine):
                up_feat = refine_block(x[index + 1])
                up_feat = torch.nn.functional.interpolate(
                    up_feat,
                    size=feat.shape[2:],
                    mode="nearest",
                )
                feat = feat + up_feat
            p = super().forward(self.feat_fuse(feat))
            if self.training:
                semseg = self.semseg(feat)
                return (p, semseg)
            return p
        return super().forward(x)


class Segment26(Detect):
    """YOLO26 segmentation head 的项目内 full core 实现。"""

    def __init__(
        self,
        nc: int,
        nm: int = 32,
        npr: int = 256,
        *,
        ch: tuple[int, ...] = (),
        reg_max: int = 1,
        strides: tuple[int, ...] = (8, 16, 32),
        end2end: bool = True,
        legacy_class_head: bool = False,
    ) -> None:
        """初始化 YOLO26 segmentation head。"""

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
        self.proto = Proto26(c_=256, c2=self.nm, nc=nc, feature_channels=ch)
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
            import copy

            self.one2one_cv4 = copy.deepcopy(self.cv4)

    @property
    def one2many(self) -> dict[str, nn.ModuleList]:
        """返回 YOLO26 segmentation one-to-many head 组件。"""

        return {"box_head": self.cv2, "class_head": self.cv3, "mask_head": self.cv4}

    @property
    def one2one(self) -> dict[str, nn.ModuleList]:
        """返回 YOLO26 segmentation one-to-one head 组件。"""

        return {
            "box_head": self.one2one_cv2,
            "class_head": self.one2one_cv3,
            "mask_head": self.one2one_cv4,
        }

    def forward(
        self,
        x: list[torch.Tensor] | tuple[torch.Tensor, ...],
    ) -> dict[str, torch.Tensor] | tuple[torch.Tensor, torch.Tensor]:
        """执行 YOLO26 segmentation head 前向。"""

        if not isinstance(x, list | tuple) or len(x) != self.nl:
            raise InvalidRequestError(
                "YOLO26 Segment26 头收到的特征层数量不合法",
                details={"expected_feature_count": self.nl},
            )
        proto_output = self.proto(tuple(x))
        if isinstance(proto_output, tuple):
            proto, semseg = proto_output
        else:
            proto = proto_output
            semseg = None
        raw_outputs = self.forward_head(x, **self.one2many)
        if self.end2end:
            detached_inputs = [feature.detach() for feature in x]
            raw_outputs = {
                "one2many": raw_outputs,
                "one2one": self.forward_head(
                    detached_inputs,
                    **self.one2one,
                ),
            }
        if self.training:
            if self.end2end:
                raw_outputs["one2many"]["proto"] = proto
                raw_outputs["one2one"]["proto"] = proto.detach()
                if semseg is not None:
                    raw_outputs["one2many"]["semseg"] = semseg
                    raw_outputs["one2one"]["semseg"] = semseg.detach()
            else:
                raw_outputs["proto"] = proto
                if semseg is not None:
                    raw_outputs["semseg"] = semseg
            return raw_outputs

        inference_outputs = raw_outputs["one2one"] if self.end2end else raw_outputs
        prediction = build_yolo26_detection_prediction(
            raw_outputs=inference_outputs,
            strides=self.strides,
            dfl_decoder=self.dfl,
        )
        prediction = torch.cat((prediction, inference_outputs["mask_coefficients"]), dim=1)
        return prediction.transpose(1, 2).contiguous(), proto

    def forward_head(
        self,
        x: list[torch.Tensor] | tuple[torch.Tensor, ...],
        *,
        box_head: nn.ModuleList,
        class_head: nn.ModuleList,
        mask_head: nn.ModuleList | None = None,
    ) -> dict[str, torch.Tensor]:
        """组装 YOLO26 segmentation 的 box / class / mask 原始输出。"""

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
