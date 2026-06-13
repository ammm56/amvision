"""YOLO26 segmentation head。"""

from __future__ import annotations

import torch
from torch import nn

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.decode import (
    build_detection_prediction,
)
from backend.service.application.models.yolo_core_common.layers import Conv
from backend.service.application.models.yolo_core_common.tasks.segmentation import (
    Proto,
    Segment,
)


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
        if feature_channels:
            base_feature_channels = feature_channels[0]
        else:
            base_feature_channels = c_
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

        if isinstance(x, (list, tuple)):
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


class Segment26(Segment):
    """YOLO26 分割头。使用 Proto26 多尺度融合 proto。"""

    def __init__(
        self,
        nc: int,
        nm: int = 32,
        npr: int = 256,
        *,
        ch: tuple[int, ...] = (),
        reg_max: int = 16,
        strides: tuple[int, ...] = (8, 16, 32),
        end2end: bool = False,
        legacy_class_head: bool = False,
    ) -> None:
        """初始化 YOLO26 分割头。"""

        super().__init__(
            nc,
            nm=nm,
            npr=npr,
            ch=ch,
            reg_max=reg_max,
            strides=strides,
            end2end=end2end,
            legacy_class_head=legacy_class_head,
        )
        self.proto = Proto26(c_=256, c2=self.nm, nc=nc, feature_channels=ch)

    def forward(
        self,
        x: list[torch.Tensor] | tuple[torch.Tensor, ...],
    ) -> dict[str, torch.Tensor] | torch.Tensor | tuple[torch.Tensor, torch.Tensor]:
        """执行分割头前向。训练时返回 raw dict，eval 时返回 (prediction, proto)。"""

        if not isinstance(x, list | tuple) or len(x) != self.nl:
            raise InvalidRequestError(
                "Segment26 头收到的特征层数量不合法",
                details={"expected_feature_count": self.nl},
            )
        proto_output = self.proto(tuple(x))
        if isinstance(proto_output, tuple):
            proto = proto_output[0]
            semseg = proto_output[1]
        else:
            proto = proto_output
            semseg = None
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
            raw_outputs = {"one2many": raw_outputs, "one2one": one2one_outputs}
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
