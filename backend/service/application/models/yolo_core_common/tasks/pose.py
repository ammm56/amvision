"""YOLO 主线 pose head。"""

from __future__ import annotations

import copy

import torch
from torch import nn

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.decode import (
    build_detection_prediction,
)
from backend.service.application.models.yolo_core_common.geometry import make_anchors
from backend.service.application.models.yolo_core_common.layers import Conv
from backend.service.application.models.yolo_core_common.tasks.detection import Detect


class Pose(Detect):
    """YOLO 关键点头的项目内实现。"""

    def __init__(
        self,
        nc: int,
        kpt_shape: tuple[int, int],
        ch: tuple[int, ...],
        *,
        reg_max: int = 16,
        strides: tuple[int, ...] = (8, 16, 32),
        end2end: bool = False,
        legacy_class_head: bool = False,
    ) -> None:
        """初始化关键点头。"""

        super().__init__(
            nc,
            ch,
            reg_max=reg_max,
            strides=strides,
            end2end=end2end,
            legacy_class_head=legacy_class_head,
        )
        self.kpt_shape = tuple(int(item) for item in kpt_shape)
        self.nk = self.kpt_shape[0] * self.kpt_shape[1]
        hidden_channels = max(ch[0] // 4, self.nk)
        self.cv4 = nn.ModuleList(
            nn.Sequential(
                Conv(input_channels, hidden_channels, 3),
                Conv(hidden_channels, hidden_channels, 3),
                nn.Conv2d(hidden_channels, self.nk, 1),
            )
            for input_channels in ch
        )
        if self.end2end:
            self.one2one_cv4 = copy.deepcopy(self.cv4)

    def forward(
        self,
        x: list[torch.Tensor] | tuple[torch.Tensor, ...],
    ) -> dict[str, torch.Tensor] | torch.Tensor:
        """执行关键点头前向。"""

        if not isinstance(x, list | tuple) or len(x) != self.nl:
            raise InvalidRequestError(
                "Pose 头收到的特征层数量不合法",
                details={"expected_feature_count": self.nl},
            )
        raw_outputs = self._build_head_outputs(
            x,
            box_head=self.cv2,
            class_head=self.cv3,
            extra_head=self.cv4,
            extra_key="kpts",
            extra_channels=self.nk,
        )
        if self.end2end:
            detached_inputs = [feature.detach() for feature in x]
            one2one_outputs = self._build_head_outputs(
                detached_inputs,
                box_head=self.one2one_cv2,
                class_head=self.one2one_cv3,
                extra_head=self.one2one_cv4,
                extra_key="kpts",
                extra_channels=self.nk,
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
        prediction = build_detection_prediction(
            raw_outputs=inference_outputs,
            strides=self.strides,
            dfl_decoder=self.dfl,
        )
        prediction = torch.cat((prediction, self._decode_keypoints(inference_outputs)), dim=1)
        return prediction.transpose(1, 2).contiguous()

    def _decode_keypoints(self, raw_outputs: dict[str, torch.Tensor]) -> torch.Tensor:
        """把关键点分支输出解码成绝对坐标。"""

        anchor_points, stride_tensor = make_anchors(
            feature_maps=raw_outputs["feats"],
            strides=self.strides,
        )
        kpts = raw_outputs["kpts"]
        batch_size = int(kpts.shape[0])
        decoded = kpts.view(batch_size, self.kpt_shape[0], self.kpt_shape[1], -1).clone()
        anchor_x = anchor_points[:, 0].view(1, 1, -1)
        anchor_y = anchor_points[:, 1].view(1, 1, -1)
        stride = stride_tensor.view(1, 1, -1)
        decoded[:, :, 0, :] = (decoded[:, :, 0, :] * 2.0 + (anchor_x - 0.5)) * stride
        decoded[:, :, 1, :] = (decoded[:, :, 1, :] * 2.0 + (anchor_y - 0.5)) * stride
        if self.kpt_shape[1] > 2:
            decoded[:, :, 2:, :] = decoded[:, :, 2:, :].sigmoid()
        return decoded.view(batch_size, self.nk, -1)
