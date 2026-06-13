"""YOLO26 pose head。"""

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
from backend.service.application.models.yolo_core_common.tasks.pose import Pose


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


class Pose26(Pose):
    """YOLO26 关键点头。含 RealNVP 流模型和独立 kpts/sigma 分支。"""

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
        """初始化 YOLO26 关键点头。"""

        super().__init__(
            nc,
            kpt_shape,
            ch,
            reg_max=reg_max,
            strides=strides,
            end2end=end2end,
            legacy_class_head=legacy_class_head,
        )
        self.flow_model = RealNVP()
        c4 = max(ch[0] // 4, self.nk + kpt_shape[0] * 2)
        self.cv4 = nn.ModuleList(nn.Sequential(Conv(x, c4, 3), Conv(c4, c4, 3)) for x in ch)
        self.cv4_kpts = nn.ModuleList(nn.Conv2d(c4, self.nk, 1) for _ in ch)
        self.nk_sigma = kpt_shape[0] * 2
        self.cv4_sigma = nn.ModuleList(nn.Conv2d(c4, self.nk_sigma, 1) for _ in ch)
        if end2end:
            self.one2one_cv4 = copy.deepcopy(self.cv4)
            self.one2one_cv4_kpts = copy.deepcopy(self.cv4_kpts)
            self.one2one_cv4_sigma = copy.deepcopy(self.cv4_sigma)

    def forward(
        self,
        x: list[torch.Tensor] | tuple[torch.Tensor, ...],
    ) -> dict[str, torch.Tensor] | torch.Tensor:
        """执行 YOLO26 关键点头前向。训练时返回 raw dict，eval 时返回组合预测张量。"""

        if not isinstance(x, list | tuple) or len(x) != self.nl:
            raise InvalidRequestError(
                "Pose26 头收到的特征层数量不合法",
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
            one2one_outputs = self._build_head_outputs_pose26(
                detached_inputs,
                box_head=self.one2one_cv2,
                class_head=self.one2one_cv3,
                pose_head=self.one2one_cv4,
                kpts_head=self.one2one_cv4_kpts,
                kpts_sigma_head=self.one2one_cv4_sigma,
            )
            raw_outputs = {"one2many": raw_outputs, "one2one": one2one_outputs}
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
        kpts = self._decode_keypoints_pose26(inference_outputs)
        prediction = torch.cat((prediction, kpts), dim=1)
        return prediction.transpose(1, 2).contiguous()

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
        """构建 YOLO26 关键点头的多分支输出。"""

        batch_size = int(x[0].shape[0])
        if self.reg_max > 1:
            box_channels = 4 * self.reg_max
        else:
            box_channels = 4
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
        result = {
            "boxes": box_outputs,
            "scores": class_outputs,
            "feats": [x[i] for i in range(self.nl)],
        }
        if pose_head is not None:
            keypoint_batch_size = int(x[0].shape[0])
            features = [pose_head[i](x[i]) for i in range(self.nl)]
            keypoint_outputs = [
                kpts_head[i](features[i]).view(keypoint_batch_size, self.nk, -1)
                for i in range(self.nl)
            ]
            result["kpts"] = torch.cat(keypoint_outputs, dim=2)
            if self.training:
                keypoint_sigma_outputs = [
                    kpts_sigma_head[i](features[i]).view(
                        keypoint_batch_size,
                        self.nk_sigma,
                        -1,
                    )
                    for i in range(self.nl)
                ]
                result["kpts_sigma"] = torch.cat(
                    keypoint_sigma_outputs,
                    dim=2,
                )
        return result

    def _decode_keypoints_pose26(self, raw_outputs: dict[str, torch.Tensor]) -> torch.Tensor:
        """解码 YOLO26 关键点坐标（锚点 + 偏移 * 步幅）。"""

        anchor_points, stride_tensor = make_anchors(
            feature_maps=raw_outputs["feats"],
            strides=self.strides,
        )
        kpts = raw_outputs["kpts"]
        batch_size = int(kpts.shape[0])
        ndim = self.kpt_shape[1]
        decoded = kpts.view(batch_size, self.kpt_shape[0], ndim, -1).clone()
        anchor_x = anchor_points[:, 0].view(1, 1, -1)
        anchor_y = anchor_points[:, 1].view(1, 1, -1)
        stride = stride_tensor.view(1, 1, -1)
        decoded[:, :, 0, :] = (decoded[:, :, 0, :] + anchor_x) * stride
        decoded[:, :, 1, :] = (decoded[:, :, 1, :] + anchor_y) * stride
        if ndim == 3:
            decoded[:, :, 2, :] = decoded[:, :, 2, :].sigmoid()
        return decoded.view(batch_size, self.nk, -1)
