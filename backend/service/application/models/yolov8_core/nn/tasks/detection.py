"""YOLOv8 detection head。"""

from __future__ import annotations

import copy

import torch
from torch import nn

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolo_core_common.layers import (
    Conv,
    DWConv,
    DistributionFocalLossDecoder,
)
from backend.service.application.models.yolov8_core.decode import (
    build_yolov8_detection_prediction,
)


class Detect(nn.Module):
    """YOLOv8 detection head 的项目内 full core 实现。"""

    dynamic = False
    export = False
    format = None
    max_det = 300
    agnostic_nms = False
    shape = None
    xyxy = False

    def __init__(
        self,
        nc: int,
        ch: tuple[int, ...],
        *,
        reg_max: int = 16,
        strides: tuple[int, ...] = (8, 16, 32),
        end2end: bool = False,
        legacy_class_head: bool = False,
    ) -> None:
        """初始化 YOLOv8 detection head。"""

        super().__init__()
        self.nc = nc
        self.nl = len(ch)
        self.reg_max = reg_max
        self.no = nc + self.reg_max * 4
        self.strides = tuple(int(item) for item in strides)
        self.end2end = bool(end2end)
        self.legacy_class_head = bool(legacy_class_head)
        if len(self.strides) != self.nl:
            raise ServiceConfigurationError(
                "YOLOv8 Detect 头的 stride 数量与特征层数量不一致",
                details={"stride_count": len(self.strides), "feature_count": self.nl},
            )

        box_hidden_channels = max((16, ch[0] // 4, self.reg_max * 4))
        class_hidden_channels = max(ch[0], min(self.nc, 100))
        self.cv2 = nn.ModuleList(
            nn.Sequential(
                Conv(input_channels, box_hidden_channels, 3),
                Conv(box_hidden_channels, box_hidden_channels, 3),
                nn.Conv2d(box_hidden_channels, 4 * self.reg_max, 1),
            )
            for input_channels in ch
        )
        self.cv3 = self._build_class_head(
            feature_channels=ch,
            class_hidden_channels=class_hidden_channels,
        )
        self.dfl = (
            DistributionFocalLossDecoder(self.reg_max)
            if self.reg_max > 1
            else nn.Identity()
        )
        if self.end2end:
            self.one2one_cv2 = copy.deepcopy(self.cv2)
            self.one2one_cv3 = copy.deepcopy(self.cv3)

    def _build_class_head(
        self,
        *,
        feature_channels: tuple[int, ...],
        class_hidden_channels: int,
    ) -> nn.ModuleList:
        """按 YOLOv8 分类分支规则构建 class head。"""

        if self.legacy_class_head:
            return nn.ModuleList(
                nn.Sequential(
                    Conv(input_channels, class_hidden_channels, 3),
                    Conv(class_hidden_channels, class_hidden_channels, 3),
                    nn.Conv2d(class_hidden_channels, self.nc, 1),
                )
                for input_channels in feature_channels
            )
        return nn.ModuleList(
            nn.Sequential(
                nn.Sequential(
                    DWConv(input_channels, input_channels, 3),
                    Conv(input_channels, class_hidden_channels, 1),
                ),
                nn.Sequential(
                    DWConv(class_hidden_channels, class_hidden_channels, 3),
                    Conv(class_hidden_channels, class_hidden_channels, 1),
                ),
                nn.Conv2d(class_hidden_channels, self.nc, 1),
            )
            for input_channels in feature_channels
        )

    def forward(
        self,
        x: list[torch.Tensor] | tuple[torch.Tensor, ...],
    ) -> dict[str, torch.Tensor] | torch.Tensor:
        """执行 YOLOv8 detection head 前向。"""

        if not isinstance(x, list | tuple) or len(x) != self.nl:
            raise InvalidRequestError(
                "YOLOv8 Detect 头收到的特征层数量不合法",
                details={"expected_feature_count": self.nl},
            )

        raw_outputs = self._build_head_outputs(
            x,
            box_head=self.cv2,
            class_head=self.cv3,
        )
        if self.end2end:
            detached_inputs = [feature.detach() for feature in x]
            one2one_outputs = self._build_head_outputs(
                detached_inputs,
                box_head=self.one2one_cv2,
                class_head=self.one2one_cv3,
            )
            raw_outputs = {
                "one2many": raw_outputs,
                "one2one": one2one_outputs,
            }
        if self.training:
            return raw_outputs

        inference_outputs = raw_outputs["one2one"] if self.end2end else raw_outputs
        prediction = build_yolov8_detection_prediction(
            raw_outputs=inference_outputs,
            strides=self.strides,
            dfl_decoder=self.dfl,
        )
        return prediction.transpose(1, 2).contiguous()

    def _build_head_outputs(
        self,
        x: list[torch.Tensor] | tuple[torch.Tensor, ...],
        *,
        box_head: nn.ModuleList,
        class_head: nn.ModuleList,
        extra_head: nn.ModuleList | None = None,
        extra_key: str | None = None,
        extra_channels: int | None = None,
    ) -> dict[str, torch.Tensor]:
        """根据指定 head 组装 YOLOv8 原始输出。"""

        batch_size = x[0].shape[0]
        box_channels = 4 * self.reg_max if self.reg_max > 1 else 4
        box_feature_outputs = [
            box_head[index](feature).view(batch_size, box_channels, -1)
            for index, feature in enumerate(x)
        ]
        box_outputs = torch.cat(box_feature_outputs, dim=2)
        class_feature_outputs = [
            class_head[index](feature).view(batch_size, self.nc, -1)
            for index, feature in enumerate(x)
        ]
        class_outputs = torch.cat(class_feature_outputs, dim=2)
        output_bundle = {
            "boxes": box_outputs,
            "scores": class_outputs,
            "feats": tuple(x),
        }
        if extra_head is not None and extra_key is not None and extra_channels is not None:
            extra_feature_outputs = [
                extra_head[index](feature).view(batch_size, int(extra_channels), -1)
                for index, feature in enumerate(x)
            ]
            output_bundle[extra_key] = torch.cat(extra_feature_outputs, dim=2)
        return output_bundle
