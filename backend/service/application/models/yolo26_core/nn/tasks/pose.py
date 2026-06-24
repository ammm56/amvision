"""YOLO26 pose head。"""

from __future__ import annotations

import copy

import torch
from torch import nn

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo26_core.decode import (
    build_yolo26_detection_prediction,
)
from backend.service.application.models.yolo26_core.nn.tasks.detection import Detect
from backend.service.application.models.yolo26_core.postprocess.export import (
    postprocess_yolo26_extra_export_tensor,
)
from backend.service.application.models.yolo_core_common.decode import (
    decode_pose_keypoints,
)
from backend.service.application.models.yolo_core_common.layers import Conv


class RealNVP(nn.Module):
    """RealNVP 流模型。用于 YOLO26 关键点概率建模。"""

    @staticmethod
    def _nets():
        """构建 scale 分支网络。"""

        return nn.Sequential(
            nn.Linear(2, 64),
            nn.SiLU(),
            nn.Linear(64, 64),
            nn.SiLU(),
            nn.Linear(64, 2),
            nn.Tanh(),
        )

    @staticmethod
    def _nett():
        """构建 translate 分支网络。"""

        return nn.Sequential(
            nn.Linear(2, 64),
            nn.SiLU(),
            nn.Linear(64, 64),
            nn.SiLU(),
            nn.Linear(64, 2),
        )

    def __init__(self) -> None:
        """初始化 RealNVP 流模型。"""

        super().__init__()
        self.register_buffer("loc", torch.zeros(2))
        self.register_buffer("cov", torch.eye(2))
        mask = torch.tensor([[0, 1], [1, 0]] * 3, dtype=torch.float32)
        self.register_buffer("mask", mask)
        self.s = nn.ModuleList([self._nets() for _ in range(len(mask))])
        self.t = nn.ModuleList([self._nett() for _ in range(len(mask))])
        self._init_weights()

    def _init_weights(self) -> None:
        """初始化权重。"""

        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight, gain=0.01)

    def _backward_p(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """把数据空间映射到潜空间，计算 Jacobian 的行列式对数。"""

        log_det = x.new_zeros(x.shape[0])
        z = x
        for index in reversed(range(len(self.t))):
            z_masked = self.mask[index] * z
            scale = self.s[index](z_masked) * (1 - self.mask[index])
            translate = self.t[index](z_masked) * (1 - self.mask[index])
            z = (1 - self.mask[index]) * (z - translate) * torch.exp(-scale) + z_masked
            log_det = log_det - scale.sum(dim=1)
        return z, log_det

    def log_prob(self, x: torch.Tensor) -> torch.Tensor:
        """计算给定数据点的 log 概率。"""

        if x.dtype == torch.float32 and self.s[0][0].weight.dtype != torch.float32:
            self.float()
        z, log_det = self._backward_p(x)
        prior = torch.distributions.MultivariateNormal(self.loc, self.cov)
        return prior.log_prob(z) + log_det


class Pose26(Detect):
    """YOLO26 pose head 的项目内 full core 实现。"""

    def __init__(
        self,
        nc: int,
        kpt_shape: tuple[int, int],
        ch: tuple[int, ...],
        *,
        reg_max: int = 1,
        strides: tuple[int, ...] = (8, 16, 32),
        end2end: bool = True,
        legacy_class_head: bool = False,
    ) -> None:
        """初始化 YOLO26 pose head。"""

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
        self.flow_model = RealNVP()
        c4 = max(ch[0] // 4, self.nk + self.kpt_shape[0] * 2)
        self.cv4 = nn.ModuleList(nn.Sequential(Conv(x, c4, 3), Conv(c4, c4, 3)) for x in ch)
        self.cv4_kpts = nn.ModuleList(nn.Conv2d(c4, self.nk, 1) for _ in ch)
        self.nk_sigma = self.kpt_shape[0] * 2
        self.cv4_sigma = nn.ModuleList(nn.Conv2d(c4, self.nk_sigma, 1) for _ in ch)
        if self.end2end:
            self.one2one_cv4 = copy.deepcopy(self.cv4)
            self.one2one_cv4_kpts = copy.deepcopy(self.cv4_kpts)
            self.one2one_cv4_sigma = copy.deepcopy(self.cv4_sigma)

    def forward(
        self,
        x: list[torch.Tensor] | tuple[torch.Tensor, ...],
    ) -> dict[str, torch.Tensor] | torch.Tensor:
        """执行 YOLO26 pose head 前向。"""

        if not isinstance(x, list | tuple) or len(x) != self.nl:
            raise InvalidRequestError(
                "YOLO26 Pose26 头收到的特征层数量不合法",
                details={"expected_feature_count": self.nl},
            )
        raw_outputs = self._build_head_outputs_pose26(
            x,
            box_head=self.cv2,
            class_head=self.cv3,
            pose_head=self.cv4,
            kpts_head=self.cv4_kpts,
            kpts_sigma_head=self.cv4_sigma,
        )
        if self.end2end:
            detached_inputs = [feature.detach() for feature in x]
            raw_outputs = {
                "one2many": raw_outputs,
                "one2one": self._build_head_outputs_pose26(
                    detached_inputs,
                    box_head=self.one2one_cv2,
                    class_head=self.one2one_cv3,
                    pose_head=self.one2one_cv4,
                    kpts_head=self.one2one_cv4_kpts,
                    kpts_sigma_head=self.one2one_cv4_sigma,
                ),
            }
        if self.training:
            return raw_outputs
        inference_outputs = raw_outputs["one2one"] if self.end2end else raw_outputs
        prediction = build_yolo26_detection_prediction(
            raw_outputs=inference_outputs,
            strides=self.strides,
            dfl_decoder=self.dfl,
        )
        kpts = decode_pose_keypoints(
            raw_outputs=inference_outputs,
            strides=self.strides,
            keypoint_shape=self.kpt_shape,
            offset_multiplier=1.0,
            anchor_offset=0.0,
        )
        prediction = torch.cat((prediction, kpts), dim=1)
        normalized_prediction = prediction.transpose(1, 2).contiguous()
        if self.end2end:
            processed_prediction = postprocess_yolo26_extra_export_tensor(
                torch_module=torch,
                prediction=normalized_prediction,
                num_classes=self.nc,
                extra_channels=self.nk,
                max_detections=self.max_det,
            )
            return (
                processed_prediction
                if self.export
                else (processed_prediction, raw_outputs)
            )
        return normalized_prediction if self.export else (normalized_prediction, raw_outputs)

    def _build_head_outputs_pose26(
        self,
        x,
        *,
        box_head,
        class_head,
        pose_head,
        kpts_head,
        kpts_sigma_head,
    ):
        """构建 YOLO26 pose head 的多分支输出。"""

        batch_size = int(x[0].shape[0])
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
        result = {
            "boxes": box_outputs,
            "scores": class_outputs,
            "feats": tuple(x),
        }
        if pose_head is not None:
            features = [pose_head[i](x[i]) for i in range(self.nl)]
            result["kpts"] = torch.cat(
                [
                    kpts_head[i](features[i]).view(batch_size, self.nk, -1)
                    for i in range(self.nl)
                ],
                dim=2,
            )
            if self.training:
                result["kpts_sigma"] = torch.cat(
                    [
                        kpts_sigma_head[i](features[i]).view(
                            batch_size,
                            self.nk_sigma,
                            -1,
                        )
                        for i in range(self.nl)
                    ],
                    dim=2,
                )
        return result
