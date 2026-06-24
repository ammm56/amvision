"""YOLO26 detection head。"""

from __future__ import annotations

import copy

import torch
from torch import nn

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.models.yolo26_core.decode import (
    build_yolo26_detection_prediction,
)
from backend.service.application.models.yolo26_core.postprocess.export import (
    postprocess_yolo26_detection_export_tensor,
)
from backend.service.application.models.yolo_core_common.layers import (
    Conv,
    DWConv,
    DistributionFocalLossDecoder,
)


class Detect(nn.Module):
    """YOLO26 detection head 的项目内 full core 实现。"""

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
        reg_max: int = 1,
        strides: tuple[int, ...] = (8, 16, 32),
        end2end: bool = True,
        legacy_class_head: bool = False,
    ) -> None:
        """初始化 YOLO26 detection head。"""

        super().__init__()
        self.nc = nc
        self.nl = len(ch)
        self.reg_max = int(reg_max)
        self.no = nc + self.reg_max * 4
        self.strides = tuple(int(item) for item in strides)
        self.end2end = bool(end2end)
        self.legacy_class_head = bool(legacy_class_head)
        if len(self.strides) != self.nl:
            raise ServiceConfigurationError(
                "YOLO26 Detect 头的 stride 数量与特征层数量不一致",
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

    @property
    def one2many(self) -> dict[str, nn.ModuleList]:
        """返回 YOLO26 one-to-many head 组件。"""

        return {"box_head": self.cv2, "class_head": self.cv3}

    @property
    def one2one(self) -> dict[str, nn.ModuleList]:
        """返回 YOLO26 one-to-one head 组件。"""

        return {"box_head": self.one2one_cv2, "class_head": self.one2one_cv3}

    def _build_class_head(
        self,
        *,
        feature_channels: tuple[int, ...],
        class_hidden_channels: int,
    ) -> nn.ModuleList:
        """按 YOLO26 分类分支规则构建 class head。"""

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
        """执行 YOLO26 detection head 前向。"""

        if not isinstance(x, list | tuple) or len(x) != self.nl:
            raise InvalidRequestError(
                "YOLO26 Detect 头收到的特征层数量不合法",
                details={"expected_feature_count": self.nl},
            )

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
            return raw_outputs

        inference_outputs = raw_outputs["one2one"] if self.end2end else raw_outputs
        prediction = self._inference(inference_outputs)
        normalized_prediction = prediction.transpose(1, 2).contiguous()
        if self.end2end:
            processed_prediction = postprocess_yolo26_detection_export_tensor(
                torch_module=torch,
                prediction=normalized_prediction,
                num_classes=self.nc,
                max_detections=self.max_det,
            )
            return (
                processed_prediction
                if self.export
                else (processed_prediction, raw_outputs)
            )
        return prediction if self.export else (normalized_prediction, raw_outputs)

    def _inference(self, raw_outputs: dict[str, torch.Tensor]) -> torch.Tensor:
        """按 YOLO26 Detect 推理路径解码 detection 输出。"""

        return build_yolo26_detection_prediction(
            raw_outputs=raw_outputs,
            strides=self.strides,
            dfl_decoder=self.dfl,
        )

    def forward_head(
        self,
        x: list[torch.Tensor] | tuple[torch.Tensor, ...],
        *,
        box_head: nn.ModuleList,
        class_head: nn.ModuleList,
    ) -> dict[str, torch.Tensor]:
        """组装 box / class 原始输出。"""

        return self._build_head_outputs(
            x,
            box_head=box_head,
            class_head=class_head,
        )

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
        """根据指定 head 组装 YOLO26 原始输出。"""

        batch_size = x[0].shape[0]
        box_channels = 4 * self.reg_max if self.reg_max > 1 else 4
        box_outputs = torch.cat(
            [
                box_head[index](feature).view(batch_size, box_channels, -1)
                for index, feature in enumerate(x)
            ],
            dim=2,
        )
        class_outputs = torch.cat(
            [
                class_head[index](feature).view(batch_size, self.nc, -1)
                for index, feature in enumerate(x)
            ],
            dim=2,
        )
        output_bundle = {
            "boxes": box_outputs,
            "scores": class_outputs,
            "feats": tuple(x),
        }
        if (
            extra_head is not None
            and extra_key is not None
            and extra_channels is not None
        ):
            output_bundle[extra_key] = torch.cat(
                [
                    extra_head[index](feature).view(batch_size, int(extra_channels), -1)
                    for index, feature in enumerate(x)
                ],
                dim=2,
            )
        return output_bundle
