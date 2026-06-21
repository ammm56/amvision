"""YOLO26 OBB head。"""

from __future__ import annotations

import copy

import torch
from torch import nn

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo26_core.nn.tasks.detection import Detect
from backend.service.application.models.yolo26_core.postprocess.export import (
    postprocess_yolo26_obb_export_tensor,
)
from backend.service.application.models.yolo_core_common.decode import (
    OBB_ANGLE_DECODE_MODE_RAW,
    build_obb_prediction,
)
from backend.service.application.models.yolo_core_common.layers import Conv


class OBB26(Detect):
    """YOLO26 OBB head 的项目内 full core 实现。"""

    angle_decode_mode = OBB_ANGLE_DECODE_MODE_RAW

    def __init__(
        self,
        nc: int,
        ne: int,
        ch: tuple[int, ...],
        *,
        reg_max: int = 1,
        strides: tuple[int, ...] = (8, 16, 32),
        end2end: bool = True,
        legacy_class_head: bool = False,
    ) -> None:
        """初始化 YOLO26 OBB head。"""

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
        """执行 YOLO26 OBB head 前向。"""

        if not isinstance(x, list | tuple) or len(x) != self.nl:
            raise InvalidRequestError(
                "YOLO26 OBB26 头收到的特征层数量不合法",
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
        normalized_prediction = prediction.transpose(1, 2).contiguous()
        if self.export and self.end2end:
            normalized_prediction = postprocess_yolo26_obb_export_tensor(
                torch_module=torch,
                prediction=normalized_prediction,
                num_classes=self.nc,
                angle_channels=self.ne,
                max_detections=self.max_det,
            )
        return normalized_prediction
