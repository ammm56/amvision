"""YOLOE custom node 的 project-native runtime。"""

from __future__ import annotations

import contextlib
import io
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np
from PIL import Image
import torch
from torch import nn
import torch.nn.functional as F

from backend.nodes.text_encoder_runtime_support import (
    get_or_create_mobileclip_blt_text_encoder,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.runtime.detection_runtime_support import (
    batched_nms_indices,
    enable_pytorch_cuda_inference_fast_path,
    preprocess_image,
    resolve_execution_device_name,
)
from custom_nodes.yoloe_open_vocab_nodes.backend.nodes._common import merge_text_prompt_items


@dataclass(frozen=True)
class ProjectNativeYoloePrediction:
    """描述一次 project-native YOLOE 节点推理结果。"""

    detections: tuple[dict[str, object], ...]
    regions: tuple[dict[str, object], ...]
    summary: dict[str, object]


@dataclass(frozen=True)
class PromptFreeCheckpointArtifacts:
    """描述 prompt-free checkpoint 解析后的关键信息。"""

    checkpoint_path: Path
    model_name: str
    model_scale: str
    model_config: dict[str, object]
    class_names: dict[int, str]
    input_size: tuple[int, int]
    state_dict: dict[str, torch.Tensor]


class YoloeConcat(nn.Module):
    """按通道维拼接多路特征。"""

    def __init__(self, dimension: int = 1) -> None:
        super().__init__()
        self.dimension = int(dimension)

    def forward(self, x: list[torch.Tensor] | tuple[torch.Tensor, ...]) -> torch.Tensor:
        if not isinstance(x, list | tuple) or len(x) < 2:
            raise InvalidRequestError("YOLOE Concat 至少需要两个输入张量")
        return torch.cat(tuple(x), dim=self.dimension)


def _autopad(kernel_size: int, padding: int | None = None, dilation: int = 1) -> int:
    """按 same 输出规则推导卷积 padding。"""

    if dilation > 1:
        kernel_size = dilation * (kernel_size - 1) + 1
    if padding is None:
        return kernel_size // 2
    return int(padding)


def _make_divisible(value: float, divisor: int) -> int:
    """把通道数上调到指定除数的整数倍。"""

    return int(np.ceil(value / divisor) * divisor)


class YoloeConv(nn.Module):
    """YOLOE project-native 标准卷积块。"""

    default_act = nn.SiLU(inplace=True)

    def __init__(
        self,
        c1: int,
        c2: int,
        k: int = 1,
        s: int = 1,
        p: int | None = None,
        g: int = 1,
        d: int = 1,
        act: bool | nn.Module = True,
    ) -> None:
        super().__init__()
        self.conv = nn.Conv2d(
            c1,
            c2,
            k,
            s,
            _autopad(k, p, d),
            groups=g,
            dilation=d,
            bias=False,
        )
        self.bn = nn.BatchNorm2d(c2, eps=1e-3, momentum=0.03)
        self.act = self.default_act if act is True else act if isinstance(act, nn.Module) else nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.act(self.bn(self.conv(x)))


class YoloeBottleneck(nn.Module):
    """YOLOE bottleneck 模块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        shortcut: bool = True,
        g: int = 1,
        k: tuple[int, int] = (3, 3),
        e: float = 0.5,
    ) -> None:
        super().__init__()
        hidden_channels = int(c2 * e)
        self.cv1 = YoloeConv(c1, hidden_channels, k[0], 1)
        self.cv2 = YoloeConv(hidden_channels, c2, k[1], 1, g=g)
        self.add = shortcut and c1 == c2

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = self.cv2(self.cv1(x))
        return x + y if self.add else y


class YoloeC2f(nn.Module):
    """YOLOE v8 主线使用的 C2f 模块。"""

    def __init__(
        self,
        c1: int,
        c2: int,
        n: int = 1,
        shortcut: bool = False,
        g: int = 1,
        e: float = 0.5,
    ) -> None:
        super().__init__()
        self.hidden_channels = int(c2 * e)
        self.cv1 = YoloeConv(c1, 2 * self.hidden_channels, 1, 1)
        self.cv2 = YoloeConv((2 + n) * self.hidden_channels, c2, 1, 1)
        self.m = nn.ModuleList(
            YoloeBottleneck(
                self.hidden_channels,
                self.hidden_channels,
                shortcut=shortcut,
                g=g,
                e=1.0,
            )
            for _ in range(n)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = list(self.cv1(x).chunk(2, dim=1))
        y.extend(module(y[-1]) for module in self.m)
        return self.cv2(torch.cat(y, dim=1))


class YoloeSPPF(nn.Module):
    """YOLOE SPPF 模块。"""

    def __init__(self, c1: int, c2: int, k: int = 5, n: int = 3, shortcut: bool = False) -> None:
        super().__init__()
        hidden_channels = c1 // 2
        self.cv1 = YoloeConv(c1, hidden_channels, 1, 1, act=False)
        self.cv2 = YoloeConv(hidden_channels * (n + 1), c2, 1, 1)
        self.pool = nn.MaxPool2d(kernel_size=k, stride=1, padding=k // 2)
        self.pool_count = int(n)
        self.add = bool(shortcut) and c1 == c2

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = [self.cv1(x)]
        y.extend(self.pool(y[-1]) for _ in range(self.pool_count))
        output = self.cv2(torch.cat(y, dim=1))
        return output + x if self.add else output


class YoloeDistributionFocalLossDecoder(nn.Module):
    """把回归分布解码为边界框距离。"""

    def __init__(self, c1: int = 16) -> None:
        super().__init__()
        self.conv = nn.Conv2d(c1, 1, 1, bias=False).requires_grad_(False)
        projection = torch.arange(c1, dtype=torch.float32)
        self.conv.weight.data[:] = nn.Parameter(projection.view(1, c1, 1, 1))
        self.c1 = int(c1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch_size, _channels, anchors = x.shape
        return self.conv(x.view(batch_size, 4, self.c1, anchors).transpose(2, 1).softmax(1)).view(batch_size, 4, anchors)


class YoloeProto(nn.Module):
    """YOLOE segmentation proto 头。"""

    def __init__(self, c1: int, c_: int = 256, c2: int = 32) -> None:
        super().__init__()
        self.cv1 = YoloeConv(c1, c_, k=3)
        self.upsample = nn.ConvTranspose2d(c_, c_, 2, 2, 0, bias=True)
        self.cv2 = YoloeConv(c_, c_, k=3)
        self.cv3 = YoloeConv(c_, c2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.cv3(self.cv2(self.upsample(self.cv1(x))))


class YoloeSpatialAwareVisualPromptEmbedding(nn.Module):
    """YOLOE SAVPE 模块。当前仅为权重兼容与后续 visual-prompt 复用保留。"""

    def __init__(self, ch: tuple[int, ...], c3: int, embed: int) -> None:
        super().__init__()
        self.cv1 = nn.ModuleList(
            nn.Sequential(
                YoloeConv(input_channels, c3, 3),
                YoloeConv(c3, c3, 3),
                nn.Upsample(scale_factor=index * 2) if index in {1, 2} else nn.Identity(),
            )
            for index, input_channels in enumerate(ch)
        )
        self.cv2 = nn.ModuleList(
            nn.Sequential(
                YoloeConv(input_channels, c3, 1),
                nn.Upsample(scale_factor=index * 2) if index in {1, 2} else nn.Identity(),
            )
            for index, input_channels in enumerate(ch)
        )
        self.c = 16
        self.cv3 = nn.Conv2d(3 * c3, embed, 1)
        self.cv4 = nn.Conv2d(3 * c3, self.c, 3, padding=1)
        self.cv5 = nn.Conv2d(1, self.c, 3, padding=1)
        self.cv6 = nn.Sequential(YoloeConv(2 * self.c, self.c, 3), nn.Conv2d(self.c, self.c, 3, padding=1))

    def forward(self, x: list[torch.Tensor], vp: torch.Tensor) -> torch.Tensor:
        y = [self.cv2[index](feature) for index, feature in enumerate(x)]
        y = self.cv4(torch.cat(y, dim=1))

        refined = [self.cv1[index](feature) for index, feature in enumerate(x)]
        refined = self.cv3(torch.cat(refined, dim=1))

        batch_size, channels, height, width = refined.shape
        prompt_count = int(vp.shape[1])
        refined = refined.view(batch_size, channels, -1)

        y = y.reshape(batch_size, 1, self.c, height, width).expand(-1, prompt_count, -1, -1, -1).reshape(
            batch_size * prompt_count,
            self.c,
            height,
            width,
        )
        vp = vp.reshape(batch_size, prompt_count, 1, height, width).reshape(batch_size * prompt_count, 1, height, width)
        y = self.cv6(torch.cat((y, self.cv5(vp)), dim=1))

        y = y.reshape(batch_size, prompt_count, self.c, -1)
        vp = vp.reshape(batch_size, prompt_count, 1, -1)
        score = y * vp + torch.logical_not(vp) * torch.finfo(y.dtype).min
        score = F.softmax(score, dim=-1).to(y.dtype)
        aggregated = score.transpose(-2, -3) @ refined.reshape(batch_size, self.c, channels // self.c, -1).transpose(-1, -2)
        return F.normalize(aggregated.transpose(-2, -3).reshape(batch_size, prompt_count, -1), dim=-1, p=2)


class YoloeBatchNormContrastiveHead(nn.Module):
    """YOLOE 文本/图像对比头。"""

    def __init__(self, embed_dims: int) -> None:
        super().__init__()
        self.norm = nn.BatchNorm2d(embed_dims, eps=1e-3, momentum=0.03)
        self.bias = nn.Parameter(torch.tensor([-10.0]))
        self.logit_scale = nn.Parameter(-1.0 * torch.ones([]))

    def fuse(self) -> None:
        del self.norm
        del self.bias
        del self.logit_scale
        self.forward = self.forward_fuse  # type: ignore[assignment]

    @staticmethod
    def forward_fuse(x: torch.Tensor, w: torch.Tensor) -> torch.Tensor:
        return x

    def forward(self, x: torch.Tensor, w: torch.Tensor) -> torch.Tensor:
        normalized_features = self.norm(x)
        normalized_text = F.normalize(w, dim=-1, p=2)
        scores = torch.einsum("bchw,bkc->bkhw", normalized_features, normalized_text)
        return scores * self.logit_scale.exp() + self.bias


class YoloeSwiGluFeedForward(nn.Module):
    """YOLOE reprta 使用的 SwiGLU FFN。"""

    def __init__(self, guide_channels: int, embed_channels: int, expansion: int = 4) -> None:
        super().__init__()
        self.w12 = nn.Linear(guide_channels, expansion * embed_channels)
        self.w3 = nn.Linear(expansion * embed_channels // 2, embed_channels)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x12 = self.w12(x)
        x1, x2 = x12.chunk(2, dim=-1)
        hidden = F.silu(x1) * x2
        return self.w3(hidden)


class YoloeResidualTextAdapter(nn.Module):
    """YOLOE reprta 残差适配器。"""

    def __init__(self, module: nn.Module) -> None:
        super().__init__()
        self.m = module
        nn.init.zeros_(self.m.w3.bias)
        nn.init.zeros_(self.m.w3.weight)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.m(x)


class YoloePromptFreeRegionProposalHead(nn.Module):
    """YOLOE prompt-free 轻量级候选框与分类头。"""

    def __init__(
        self,
        cls_channels: int,
        loc_channels: int,
        num_classes: int,
        *,
        enabled: bool,
    ) -> None:
        super().__init__()
        self.enabled = bool(enabled)
        if self.enabled:
            self.vocab = nn.Linear(cls_channels, num_classes)
        else:
            self.vocab = nn.Conv2d(cls_channels, num_classes, 1)
        self.pf = nn.Conv2d(cls_channels, 1, 1)
        self.loc = nn.Conv2d(loc_channels, loc_channels, 1)

    def forward(self, cls_feat: torch.Tensor, loc_feat: torch.Tensor, conf: float) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        if self.enabled:
            proposal_scores = self.pf(cls_feat)[0, 0].flatten(0)
            keep_mask = proposal_scores.sigmoid() > float(conf)
            flattened_cls_feat = cls_feat.flatten(2).transpose(-1, -2)
            if float(conf) > 0:
                cls_scores = self.vocab(flattened_cls_feat[:, keep_mask])
            else:
                cls_scores = self.vocab(flattened_cls_feat * keep_mask.unsqueeze(-1).to(dtype=flattened_cls_feat.dtype))
            return self.loc(loc_feat), cls_scores.transpose(-1, -2), keep_mask

        cls_scores = self.vocab(cls_feat).flatten(2)
        anchor_count = int(cls_scores.shape[2])
        keep_mask = torch.ones(anchor_count, device=cls_scores.device, dtype=torch.bool)
        return self.loc(loc_feat), cls_scores, keep_mask


class YoloePromptFreeSegmentationHead(nn.Module):
    """只面向 prompt-free 推理的 YOLOE segmentation 头。"""

    def __init__(
        self,
        nc: int,
        nm: int,
        npr: int,
        embed: int,
        with_bn: bool,
        ch: tuple[int, ...],
        *,
        reg_max: int = 16,
        strides: tuple[int, ...] = (8, 16, 32),
    ) -> None:
        super().__init__()
        self.nc = int(nc)
        self.nl = len(ch)
        self.nm = int(nm)
        self.npr = int(npr)
        self.embed = int(embed)
        self.with_bn = bool(with_bn)
        self.reg_max = int(reg_max)
        self.strides = tuple(int(item) for item in strides)
        self.conf = 0.001

        box_hidden_channels = max((16, ch[0] // 4, self.reg_max * 4))
        class_hidden_channels = max(ch[0], min(self.nc, 100))
        self.cv2 = nn.ModuleList(
            nn.Sequential(
                YoloeConv(input_channels, box_hidden_channels, 3),
                YoloeConv(box_hidden_channels, box_hidden_channels, 3),
            )
            for input_channels in ch
        )
        self.cv3 = nn.ModuleList(
            nn.Sequential(
                YoloeConv(input_channels, class_hidden_channels, 3),
                YoloeConv(class_hidden_channels, class_hidden_channels, 3),
            )
            for input_channels in ch
        )
        self.dfl = YoloeDistributionFocalLossDecoder(self.reg_max) if self.reg_max > 1 else nn.Identity()
        self.proto = YoloeProto(ch[0], self.npr, self.nm)

        hidden_channels = max(ch[0] // 4, self.nm)
        self.cv5 = nn.ModuleList(
            nn.Sequential(
                YoloeConv(input_channels, hidden_channels, 3),
                YoloeConv(hidden_channels, hidden_channels, 3),
                nn.Conv2d(hidden_channels, self.nm, 1),
            )
            for input_channels in ch
        )
        self.savpe = YoloeSpatialAwareVisualPromptEmbedding(ch, class_hidden_channels, self.embed)
        self.reprta = nn.Identity()
        self.lrpc = nn.ModuleList(
            (
                YoloePromptFreeRegionProposalHead(class_hidden_channels, box_hidden_channels, self.nc, enabled=True),
                YoloePromptFreeRegionProposalHead(class_hidden_channels, box_hidden_channels, self.nc, enabled=True),
                YoloePromptFreeRegionProposalHead(class_hidden_channels, box_hidden_channels, self.nc, enabled=False),
            )
        )

    def forward(self, x: list[torch.Tensor] | tuple[torch.Tensor, ...]) -> tuple[torch.Tensor, torch.Tensor]:
        if not isinstance(x, list | tuple) or len(x) != self.nl:
            raise InvalidRequestError(
                "YOLOE prompt-free 头收到的特征层数量不合法",
                details={"expected_feature_count": self.nl},
            )
        batch_size = int(x[0].shape[0])
        boxes: list[torch.Tensor] = []
        scores: list[torch.Tensor] = []
        keep_masks: list[torch.Tensor] = []
        for index in range(self.nl):
            cls_feat = self.cv3[index](x[index])
            loc_feat = self.cv2[index](x[index])
            box_output, score_output, keep_mask = self.lrpc[index](cls_feat, loc_feat, self.conf)
            boxes.append(box_output.view(batch_size, self.reg_max * 4, -1))
            scores.append(score_output)
            keep_masks.append(keep_mask)
        mask_coefficients = torch.cat(
            [self.cv5[index](x[index]).view(batch_size, self.nm, -1) for index in range(self.nl)],
            dim=2,
        )
        proposal_mask = torch.cat(keep_masks, dim=0)
        predictions = {
            "boxes": torch.cat(boxes, dim=2),
            "scores": torch.cat(scores, dim=2),
            "feats": tuple(x),
            "index": proposal_mask,
            "mask_coefficients": mask_coefficients[..., proposal_mask],
        }
        decoded = self._build_inference_prediction(predictions)
        decoded = torch.cat((decoded, predictions["mask_coefficients"]), dim=1)
        return decoded.transpose(1, 2).contiguous(), self.proto(x[0])

    def _build_inference_prediction(self, predictions: dict[str, torch.Tensor]) -> torch.Tensor:
        anchor_points, stride_tensor = _make_anchors(
            feature_maps=predictions["feats"],
            strides=self.strides,
        )
        distances = self.dfl(predictions["boxes"])
        decoded_boxes = _dist2bbox_xyxy(
            distances=distances,
            anchor_points=anchor_points.unsqueeze(0),
            stride_tensor=stride_tensor.unsqueeze(0),
        )
        decoded_boxes = decoded_boxes[..., predictions["index"]]
        class_scores = predictions["scores"].sigmoid()
        return torch.cat((decoded_boxes, class_scores), dim=1)


class YoloePromptFreeSegmentationModel(nn.Module):
    """按 checkpoint 配置构建的 project-native YOLOE prompt-free segmentation 模型。"""

    def __init__(
        self,
        *,
        model_name: str,
        model_scale: str,
        num_classes: int,
        model_config: dict[str, object],
        input_channels: int = 3,
    ) -> None:
        super().__init__()
        self.model_name = model_name
        self.model_scale = model_scale
        self.num_classes = int(num_classes)
        self.model_config = dict(model_config)
        self.input_channels = int(input_channels)
        self.model, self.save = _parse_prompt_free_model(
            model_name=model_name,
            model_scale=model_scale,
            num_classes=num_classes,
            model_config=model_config,
            input_channels=input_channels,
        )
        self.names: dict[int, str] = {}
        self.stride = torch.tensor(tuple(int(item) for item in model_config.get("strides", (8, 16, 32))), dtype=torch.float32)
        self.task = "segment"
        self.text_model = None

    def forward(self, x: torch.Tensor) -> Any:
        outputs: list[Any] = []
        current: Any = x
        for layer in self.model:
            from_index = getattr(layer, "from_index", -1)
            if isinstance(from_index, tuple):
                layer_input = [current if index == -1 else outputs[index] for index in from_index]
            else:
                layer_input = current if from_index == -1 else outputs[from_index]
            current = layer(layer_input)
            outputs.append(current)
        return current


class YoloeTextPromptSegmentationHead(nn.Module):
    """面向 text-prompt 的 YOLOE segmentation 头。"""

    def __init__(
        self,
        nc: int,
        nm: int,
        npr: int,
        embed: int,
        with_bn: bool,
        ch: tuple[int, ...],
        *,
        reg_max: int = 16,
        strides: tuple[int, ...] = (8, 16, 32),
    ) -> None:
        super().__init__()
        self.nc = int(nc)
        self.nl = len(ch)
        self.nm = int(nm)
        self.npr = int(npr)
        self.embed = int(embed)
        self.with_bn = bool(with_bn)
        self.reg_max = int(reg_max)
        self.strides = tuple(int(item) for item in strides)

        box_hidden_channels = max((16, ch[0] // 4, self.reg_max * 4))
        class_hidden_channels = max(ch[0], min(self.nc, 100))
        self.cv2 = nn.ModuleList(
            nn.Sequential(
                YoloeConv(input_channels, box_hidden_channels, 3),
                YoloeConv(box_hidden_channels, box_hidden_channels, 3),
                nn.Conv2d(box_hidden_channels, 4 * self.reg_max, 1),
            )
            for input_channels in ch
        )
        self.cv3 = nn.ModuleList(
            nn.Sequential(
                YoloeConv(input_channels, class_hidden_channels, 3),
                YoloeConv(class_hidden_channels, class_hidden_channels, 3),
                nn.Conv2d(class_hidden_channels, self.embed, 1),
            )
            for input_channels in ch
        )
        self.cv4 = nn.ModuleList(YoloeBatchNormContrastiveHead(self.embed) for _ in ch)
        self.proto = YoloeProto(ch[0], self.npr, self.nm)
        hidden_channels = max(ch[0] // 4, self.nm)
        self.cv5 = nn.ModuleList(
            nn.Sequential(
                YoloeConv(input_channels, hidden_channels, 3),
                YoloeConv(hidden_channels, hidden_channels, 3),
                nn.Conv2d(hidden_channels, self.nm, 1),
            )
            for input_channels in ch
        )
        self.reprta = YoloeResidualTextAdapter(YoloeSwiGluFeedForward(self.embed, self.embed))
        self.savpe = YoloeSpatialAwareVisualPromptEmbedding(ch, class_hidden_channels, self.embed)
        self.dfl = YoloeDistributionFocalLossDecoder(self.reg_max) if self.reg_max > 1 else nn.Identity()

    def get_tpe(self, tpe: torch.Tensor | None) -> torch.Tensor | None:
        return None if tpe is None else F.normalize(self.reprta(tpe), dim=-1, p=2)

    def get_vpe(self, x: list[torch.Tensor], vpe: torch.Tensor) -> torch.Tensor:
        if vpe.shape[1] == 0:
            return torch.zeros(x[0].shape[0], 0, self.embed, device=x[0].device)
        if vpe.ndim == 4:
            vpe = self.savpe(x, vpe)
        if vpe.ndim != 3:
            raise InvalidRequestError("YOLOE visual prompt embedding 维度不合法")
        return vpe

    def forward(self, x: list[torch.Tensor] | tuple[torch.Tensor, ...], class_embeddings: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        if not isinstance(x, list | tuple) or len(x) != self.nl:
            raise InvalidRequestError(
                "YOLOE text-prompt 头收到的特征层数量不合法",
                details={"expected_feature_count": self.nl},
            )
        if class_embeddings.ndim != 3:
            raise InvalidRequestError("YOLOE text-prompt 类别 embedding 维度不合法")
        self.nc = int(class_embeddings.shape[1])
        batch_size = int(x[0].shape[0])
        box_outputs = torch.cat(
            [self.cv2[index](feature).view(batch_size, 4 * self.reg_max, -1) for index, feature in enumerate(x)],
            dim=2,
        )
        score_outputs = torch.cat(
            [
                self.cv4[index](self.cv3[index](feature), class_embeddings).reshape(batch_size, self.nc, -1)
                for index, feature in enumerate(x)
            ],
            dim=2,
        )
        mask_coefficients = torch.cat(
            [self.cv5[index](feature).view(batch_size, self.nm, -1) for index, feature in enumerate(x)],
            dim=2,
        )
        prediction = self._build_inference_prediction(
            {
                "boxes": box_outputs,
                "scores": score_outputs,
                "feats": tuple(x),
            }
        )
        prediction = torch.cat((prediction, mask_coefficients), dim=1)
        return prediction.transpose(1, 2).contiguous(), self.proto(x[0])

    def _build_inference_prediction(self, predictions: dict[str, torch.Tensor]) -> torch.Tensor:
        anchor_points, stride_tensor = _make_anchors(
            feature_maps=predictions["feats"],
            strides=self.strides,
        )
        distances = self.dfl(predictions["boxes"])
        decoded_boxes = _dist2bbox_xyxy(
            distances=distances,
            anchor_points=anchor_points.unsqueeze(0),
            stride_tensor=stride_tensor.unsqueeze(0),
        )
        class_scores = predictions["scores"].sigmoid()
        return torch.cat((decoded_boxes, class_scores), dim=1)


class YoloeTextPromptSegmentationModel(nn.Module):
    """按 checkpoint 配置构建的 project-native YOLOE text-prompt segmentation 模型。"""

    def __init__(
        self,
        *,
        model_name: str,
        model_scale: str,
        num_classes: int,
        model_config: dict[str, object],
        input_channels: int = 3,
    ) -> None:
        super().__init__()
        self.model_name = model_name
        self.model_scale = model_scale
        self.num_classes = int(num_classes)
        self.model_config = dict(model_config)
        self.input_channels = int(input_channels)
        self.model, self.save = _parse_text_prompt_model(
            model_name=model_name,
            model_scale=model_scale,
            num_classes=num_classes,
            model_config=model_config,
            input_channels=input_channels,
        )
        self.names: dict[int, str] = {}
        self.stride = torch.tensor(tuple(int(item) for item in model_config.get("strides", (8, 16, 32))), dtype=torch.float32)
        self.task = "segment"
        self.text_model = "mobileclip:blt"

    def forward(self, x: torch.Tensor, class_embeddings: torch.Tensor) -> Any:
        outputs: list[Any] = []
        current: Any = x
        for layer in self.model:
            from_index = getattr(layer, "from_index", -1)
            if isinstance(from_index, tuple):
                layer_input = [current if index == -1 else outputs[index] for index in from_index]
            else:
                layer_input = current if from_index == -1 else outputs[from_index]
            if isinstance(layer, YoloeTextPromptSegmentationHead):
                current = layer(layer_input, class_embeddings)
            else:
                current = layer(layer_input)
            outputs.append(current)
        return current


def build_yoloe_prompt_free_segmentation_model(
    *,
    model_name: str,
    model_scale: str,
    num_classes: int,
    model_config: dict[str, object],
    input_channels: int = 3,
) -> YoloePromptFreeSegmentationModel:
    """按 checkpoint 配置构建 prompt-free segmentation 模型。"""

    return YoloePromptFreeSegmentationModel(
        model_name=model_name,
        model_scale=model_scale,
        num_classes=num_classes,
        model_config=model_config,
        input_channels=input_channels,
    )


def build_yoloe_text_prompt_segmentation_model(
    *,
    model_name: str,
    model_scale: str,
    num_classes: int,
    model_config: dict[str, object],
    input_channels: int = 3,
) -> YoloeTextPromptSegmentationModel:
    """按 checkpoint 配置构建 text-prompt segmentation 模型。"""

    return YoloeTextPromptSegmentationModel(
        model_name=model_name,
        model_scale=model_scale,
        num_classes=num_classes,
        model_config=model_config,
        input_channels=input_channels,
    )


def _parse_prompt_free_model(
    *,
    model_name: str,
    model_scale: str,
    num_classes: int,
    model_config: dict[str, object],
    input_channels: int,
) -> tuple[nn.Sequential, tuple[int, ...]]:
    scales = model_config.get("scales")
    if not isinstance(scales, dict):
        raise ServiceConfigurationError(f"{model_name} 配置缺少 scales")
    scale_key = _resolve_yaml_scale_key(model_scale)
    raw_scale_profile = scales.get(scale_key)
    if not isinstance(raw_scale_profile, list | tuple) or len(raw_scale_profile) != 3:
        raise InvalidRequestError(
            f"当前 {model_name} 不支持指定 model_scale",
            details={"model_scale": model_scale},
        )
    depth_multiple = float(raw_scale_profile[0])
    width_multiple = float(raw_scale_profile[1])
    max_channels = int(raw_scale_profile[2])

    backbone = model_config.get("backbone")
    head = model_config.get("head")
    if not isinstance(backbone, list) or not isinstance(head, list):
        raise ServiceConfigurationError(f"{model_name} 配置缺少 backbone/head")

    channels: list[int] = [input_channels]
    layers: list[nn.Module] = []
    save: list[int] = []
    module_defs = tuple(backbone) + tuple(head)
    module_map = {
        "Conv": YoloeConv,
        "C2f": YoloeC2f,
        "SPPF": YoloeSPPF,
        "Concat": YoloeConcat,
        "nn.Upsample": nn.Upsample,
        "YOLOESegment": YoloePromptFreeSegmentationHead,
    }

    for layer_index, raw_layer_def in enumerate(module_defs):
        if not isinstance(raw_layer_def, list | tuple) or len(raw_layer_def) != 4:
            raise ServiceConfigurationError(
                f"{model_name} 配置层定义不合法",
                details={"layer_index": layer_index},
            )
        raw_from, raw_repeat, raw_module_name, raw_args = raw_layer_def
        module_name = str(raw_module_name)
        module_type = module_map.get(module_name)
        if module_type is None:
            raise ServiceConfigurationError(
                f"{model_name} 当前不支持配置里的模块类型",
                details={"layer_index": layer_index, "module_name": module_name},
            )
        if not isinstance(raw_args, list | tuple):
            raise ServiceConfigurationError(
                f"{model_name} 配置层参数不合法",
                details={"layer_index": layer_index},
            )
        from_index = _normalize_from_index(raw_from)
        repeat_count = _resolve_repeat_count(raw_repeat, depth_multiple)
        module_args = [
            _resolve_model_config_argument(item, num_classes=num_classes)
            for item in raw_args
        ]
        output_channels: int

        if module_type in {YoloeConv, YoloeC2f, YoloeSPPF}:
            source_channels = channels[_resolve_single_from_index(from_index)]
            output_channels = _make_divisible(min(float(module_args[0]), float(max_channels)) * width_multiple, 8)
            if module_type is YoloeConv:
                module = module_type(source_channels, output_channels, *module_args[1:])
            elif module_type is YoloeSPPF:
                module = module_type(source_channels, output_channels, *module_args[1:])
            else:
                module = module_type(source_channels, output_channels, repeat_count, *module_args[1:])
        elif module_type is YoloeConcat:
            concat_sources = _resolve_multi_from_indexes(from_index)
            output_channels = sum(channels[item] for item in concat_sources)
            module = module_type(*module_args)
        elif module_type is nn.Upsample:
            output_channels = channels[_resolve_single_from_index(from_index)]
            size = None if module_args[0] in {None, "None"} else module_args[0]
            module = module_type(size=size, scale_factor=module_args[1], mode=module_args[2])
        else:
            detect_sources = _resolve_multi_from_indexes(from_index)
            detect_channels = tuple(channels[item] for item in detect_sources)
            output_channels = sum(detect_channels)
            npr = _make_divisible(min(float(module_args[2]), float(max_channels)) * width_multiple, 8)
            module = module_type(
                nc=int(module_args[0]),
                nm=int(module_args[1]),
                npr=int(npr),
                embed=int(module_args[3]),
                with_bn=bool(module_args[4]),
                ch=detect_channels,
                reg_max=int(model_config.get("reg_max", 16)),
                strides=tuple(int(item) for item in model_config.get("strides", (8, 16, 32))),
            )

        setattr(module, "layer_index", layer_index)
        setattr(module, "from_index", from_index)
        setattr(module, "layer_name", module_name)
        layers.append(module)
        if layer_index == 0:
            channels = []
        channels.append(output_channels)

        referenced_indexes = (
            _resolve_multi_from_indexes(from_index)
            if isinstance(from_index, tuple)
            else (_resolve_single_from_index(from_index),)
        )
        for referenced_index in referenced_indexes:
            if referenced_index != -1:
                save.append(referenced_index)

    return nn.Sequential(*layers), tuple(sorted(set(save)))


def _parse_text_prompt_model(
    *,
    model_name: str,
    model_scale: str,
    num_classes: int,
    model_config: dict[str, object],
    input_channels: int,
) -> tuple[nn.Sequential, tuple[int, ...]]:
    scales = model_config.get("scales")
    if not isinstance(scales, dict):
        raise ServiceConfigurationError(f"{model_name} 配置缺少 scales")
    scale_key = _resolve_yaml_scale_key(model_scale)
    raw_scale_profile = scales.get(scale_key)
    if not isinstance(raw_scale_profile, list | tuple) or len(raw_scale_profile) != 3:
        raise InvalidRequestError(
            f"当前 {model_name} 不支持指定 model_scale",
            details={"model_scale": model_scale},
        )
    depth_multiple = float(raw_scale_profile[0])
    width_multiple = float(raw_scale_profile[1])
    max_channels = int(raw_scale_profile[2])

    backbone = model_config.get("backbone")
    head = model_config.get("head")
    if not isinstance(backbone, list) or not isinstance(head, list):
        raise ServiceConfigurationError(f"{model_name} 配置缺少 backbone/head")

    channels: list[int] = [input_channels]
    layers: list[nn.Module] = []
    save: list[int] = []
    module_defs = tuple(backbone) + tuple(head)
    module_map = {
        "Conv": YoloeConv,
        "C2f": YoloeC2f,
        "SPPF": YoloeSPPF,
        "Concat": YoloeConcat,
        "nn.Upsample": nn.Upsample,
        "YOLOESegment": YoloeTextPromptSegmentationHead,
    }

    for layer_index, raw_layer_def in enumerate(module_defs):
        if not isinstance(raw_layer_def, list | tuple) or len(raw_layer_def) != 4:
            raise ServiceConfigurationError(
                f"{model_name} 配置层定义不合法",
                details={"layer_index": layer_index},
            )
        raw_from, raw_repeat, raw_module_name, raw_args = raw_layer_def
        module_name = str(raw_module_name)
        module_type = module_map.get(module_name)
        if module_type is None:
            raise ServiceConfigurationError(
                f"{model_name} 当前不支持配置里的模块类型",
                details={"layer_index": layer_index, "module_name": module_name},
            )
        if not isinstance(raw_args, list | tuple):
            raise ServiceConfigurationError(
                f"{model_name} 配置层参数不合法",
                details={"layer_index": layer_index},
            )
        from_index = _normalize_from_index(raw_from)
        repeat_count = _resolve_repeat_count(raw_repeat, depth_multiple)
        module_args = [
            _resolve_model_config_argument(item, num_classes=num_classes)
            for item in raw_args
        ]
        output_channels: int

        if module_type in {YoloeConv, YoloeC2f, YoloeSPPF}:
            source_channels = channels[_resolve_single_from_index(from_index)]
            output_channels = _make_divisible(min(float(module_args[0]), float(max_channels)) * width_multiple, 8)
            if module_type is YoloeConv:
                module = module_type(source_channels, output_channels, *module_args[1:])
            elif module_type is YoloeSPPF:
                module = module_type(source_channels, output_channels, *module_args[1:])
            else:
                module = module_type(source_channels, output_channels, repeat_count, *module_args[1:])
        elif module_type is YoloeConcat:
            concat_sources = _resolve_multi_from_indexes(from_index)
            output_channels = sum(channels[item] for item in concat_sources)
            module = module_type(*module_args)
        elif module_type is nn.Upsample:
            output_channels = channels[_resolve_single_from_index(from_index)]
            size = None if module_args[0] in {None, "None"} else module_args[0]
            module = module_type(size=size, scale_factor=module_args[1], mode=module_args[2])
        else:
            detect_sources = _resolve_multi_from_indexes(from_index)
            detect_channels = tuple(channels[item] for item in detect_sources)
            output_channels = sum(detect_channels)
            npr = _make_divisible(min(float(module_args[2]), float(max_channels)) * width_multiple, 8)
            module = module_type(
                nc=int(module_args[0]),
                nm=int(module_args[1]),
                npr=int(npr),
                embed=int(module_args[3]),
                with_bn=bool(module_args[4]),
                ch=detect_channels,
                reg_max=int(model_config.get("reg_max", 16)),
                strides=tuple(int(item) for item in model_config.get("strides", (8, 16, 32))),
            )

        setattr(module, "layer_index", layer_index)
        setattr(module, "from_index", from_index)
        setattr(module, "layer_name", module_name)
        layers.append(module)
        if layer_index == 0:
            channels = []
        channels.append(output_channels)

        referenced_indexes = (
            _resolve_multi_from_indexes(from_index)
            if isinstance(from_index, tuple)
            else (_resolve_single_from_index(from_index),)
        )
        for referenced_index in referenced_indexes:
            if referenced_index != -1:
                save.append(referenced_index)

    return nn.Sequential(*layers), tuple(sorted(set(save)))


def _resolve_model_config_argument(value: object, *, num_classes: int) -> object:
    if value == "nc":
        return int(num_classes)
    if value == "None":
        return None
    return value


def _resolve_repeat_count(raw_repeat: object, depth_multiple: float) -> int:
    repeat = int(raw_repeat)
    if repeat <= 1:
        return max(repeat, 1)
    return max(int(round(repeat * depth_multiple)), 1)


def _normalize_from_index(raw_from: object) -> int | tuple[int, ...]:
    if isinstance(raw_from, int):
        return raw_from
    if isinstance(raw_from, list | tuple):
        normalized = tuple(int(item) for item in raw_from)
        if not normalized:
            raise InvalidRequestError("YOLOE 配置里的 from 不能为空列表")
        return normalized
    raise InvalidRequestError("YOLOE 配置里的 from 字段不合法", details={"raw_from": raw_from})


def _resolve_single_from_index(from_index: int | tuple[int, ...]) -> int:
    if isinstance(from_index, tuple):
        if len(from_index) != 1:
            raise InvalidRequestError(
                "当前层只接受单输入 from 配置",
                details={"from_index": list(from_index)},
            )
        return from_index[0]
    return from_index


def _resolve_multi_from_indexes(from_index: int | tuple[int, ...]) -> tuple[int, ...]:
    return from_index if isinstance(from_index, tuple) else (from_index,)


def _resolve_yaml_scale_key(model_scale: str) -> str:
    normalized_scale = str(model_scale or "").strip().lower()
    if normalized_scale == "nano":
        return "n"
    if normalized_scale == "tiny":
        raise InvalidRequestError("当前 YOLOE 预训练权重不支持 tiny scale")
    if normalized_scale == "xx":
        raise InvalidRequestError("当前 YOLOE 预训练权重不支持 xx scale")
    return normalized_scale or "s"


def _make_anchors(
    *,
    feature_maps: tuple[torch.Tensor, ...] | list[torch.Tensor],
    strides: tuple[int, ...],
) -> tuple[torch.Tensor, torch.Tensor]:
    anchor_points: list[torch.Tensor] = []
    stride_values: list[torch.Tensor] = []
    for feature_map, stride in zip(feature_maps, strides, strict=True):
        _batch_size, _channels, height, width = feature_map.shape
        grid_y, grid_x = torch.meshgrid(
            torch.arange(height, device=feature_map.device, dtype=feature_map.dtype),
            torch.arange(width, device=feature_map.device, dtype=feature_map.dtype),
            indexing="ij",
        )
        points = torch.stack((grid_x, grid_y), dim=-1).reshape(-1, 2) + 0.5
        anchor_points.append(points)
        stride_values.append(
            torch.full(
                (height * width, 1),
                float(stride),
                device=feature_map.device,
                dtype=feature_map.dtype,
            )
        )
    return torch.cat(anchor_points, dim=0), torch.cat(stride_values, dim=0)


def _dist2bbox_xyxy(
    *,
    distances: torch.Tensor,
    anchor_points: torch.Tensor,
    stride_tensor: torch.Tensor,
) -> torch.Tensor:
    left_top, right_bottom = distances.chunk(2, dim=1)
    x1y1 = anchor_points.transpose(1, 2) - left_top
    x2y2 = anchor_points.transpose(1, 2) + right_bottom
    return torch.cat((x1y1, x2y2), dim=1) * stride_tensor.transpose(1, 2)


class _CheckpointCompatModule(nn.Module):
    """只用于读取 checkpoint 的兼容占位模块。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__()
        self.args = args
        self.kwargs = kwargs

    def __getattr__(self, name: str) -> object:
        try:
            return super().__getattr__(name)
        except AttributeError:
            if name.startswith("__"):
                raise
            return lambda *args, **kwargs: None


class _CheckpointCompatConv(_CheckpointCompatModule):
    pass


class _CheckpointCompatConcat(_CheckpointCompatModule):
    pass


class _CheckpointCompatC2f(_CheckpointCompatModule):
    pass


class _CheckpointCompatBottleneck(_CheckpointCompatModule):
    pass


class _CheckpointCompatSPPF(_CheckpointCompatModule):
    pass


class _CheckpointCompatDfl(_CheckpointCompatModule):
    pass


class _CheckpointCompatBatchNormContrastiveHead(_CheckpointCompatModule):
    pass


class _CheckpointCompatProto(_CheckpointCompatModule):
    pass


class _CheckpointCompatResidual(_CheckpointCompatModule):
    pass


class _CheckpointCompatSwiGluFfn(_CheckpointCompatModule):
    pass


class _CheckpointCompatSavpe(_CheckpointCompatModule):
    pass


class _CheckpointCompatLrpcHead(_CheckpointCompatModule):
    pass


class _CheckpointCompatYoloeSegmentHead(_CheckpointCompatModule):
    pass


class _CheckpointCompatYoloeSegmentationModel(_CheckpointCompatModule):
    pass


@contextlib.contextmanager
def _temporary_checkpoint_class_aliases():
    alias_modules = {
        "ultralytics": types.ModuleType("ultralytics"),
        "ultralytics.nn": types.ModuleType("ultralytics.nn"),
        "ultralytics.nn.tasks": types.ModuleType("ultralytics.nn.tasks"),
        "ultralytics.nn.modules": types.ModuleType("ultralytics.nn.modules"),
        "ultralytics.nn.modules.conv": types.ModuleType("ultralytics.nn.modules.conv"),
        "ultralytics.nn.modules.block": types.ModuleType("ultralytics.nn.modules.block"),
        "ultralytics.nn.modules.head": types.ModuleType("ultralytics.nn.modules.head"),
    }
    alias_modules["ultralytics.nn.tasks"].YOLOESegModel = _CheckpointCompatYoloeSegmentationModel
    alias_modules["ultralytics.nn.modules.conv"].Conv = _CheckpointCompatConv
    alias_modules["ultralytics.nn.modules.conv"].Concat = _CheckpointCompatConcat
    alias_modules["ultralytics.nn.modules.block"].C2f = _CheckpointCompatC2f
    alias_modules["ultralytics.nn.modules.block"].Bottleneck = _CheckpointCompatBottleneck
    alias_modules["ultralytics.nn.modules.block"].SPPF = _CheckpointCompatSPPF
    alias_modules["ultralytics.nn.modules.block"].DFL = _CheckpointCompatDfl
    alias_modules["ultralytics.nn.modules.block"].BNContrastiveHead = _CheckpointCompatBatchNormContrastiveHead
    alias_modules["ultralytics.nn.modules.block"].Proto = _CheckpointCompatProto
    alias_modules["ultralytics.nn.modules.block"].Residual = _CheckpointCompatResidual
    alias_modules["ultralytics.nn.modules.block"].SwiGLUFFN = _CheckpointCompatSwiGluFfn
    alias_modules["ultralytics.nn.modules.head"].YOLOESegment = _CheckpointCompatYoloeSegmentHead
    alias_modules["ultralytics.nn.modules.head"].SAVPE = _CheckpointCompatSavpe
    alias_modules["ultralytics.nn.modules.head"].LRPCHead = _CheckpointCompatLrpcHead
    alias_modules["ultralytics.nn.modules.head"].Residual = _CheckpointCompatResidual
    alias_modules["ultralytics.nn.modules.head"].SwiGLUFFN = _CheckpointCompatSwiGluFfn

    previous_modules = {name: sys.modules.get(name) for name in alias_modules}
    sys.modules.update(alias_modules)
    try:
        yield
    finally:
        for name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def load_prompt_free_checkpoint_artifacts(*, checkpoint_path: Path) -> PromptFreeCheckpointArtifacts:
    """从 prompt-free checkpoint 提取 project-native 运行时所需数据。"""

    with _temporary_checkpoint_class_aliases():
        checkpoint_payload = torch.load(str(checkpoint_path), map_location="cpu", weights_only=False)
    if not isinstance(checkpoint_payload, dict):
        raise InvalidRequestError(
            "YOLOE prompt-free checkpoint 载入结果不是合法字典",
            details={"checkpoint_path": str(checkpoint_path)},
        )

    checkpoint_model = checkpoint_payload.get("ema") or checkpoint_payload.get("model")
    if not isinstance(checkpoint_model, nn.Module):
        raise InvalidRequestError(
            "YOLOE prompt-free checkpoint 缺少可用模型对象",
            details={"checkpoint_path": str(checkpoint_path)},
        )
    model_config = getattr(checkpoint_model, "yaml", None)
    if not isinstance(model_config, dict):
        raise InvalidRequestError(
            "YOLOE prompt-free checkpoint 缺少模型配置",
            details={"checkpoint_path": str(checkpoint_path)},
        )
    raw_names = getattr(checkpoint_model, "names", None)
    if not isinstance(raw_names, dict) or not raw_names:
        raise InvalidRequestError(
            "YOLOE prompt-free checkpoint 缺少类别名映射",
            details={"checkpoint_path": str(checkpoint_path)},
        )
    class_names = {int(key): str(value) for key, value in raw_names.items()}
    model_scale = str(model_config.get("scale") or "s").strip().lower()
    train_args = checkpoint_payload.get("train_args")
    if not isinstance(train_args, dict):
        train_args = {}
    input_size = _resolve_checkpoint_input_size(train_args.get("imgsz"))
    return PromptFreeCheckpointArtifacts(
        checkpoint_path=checkpoint_path,
        model_name=str(model_config.get("yaml_file") or checkpoint_path.stem),
        model_scale=model_scale,
        model_config=dict(model_config),
        class_names=class_names,
        input_size=input_size,
        state_dict=dict(checkpoint_model.state_dict()),
    )


def _resolve_checkpoint_input_size(raw_imgsz: object) -> tuple[int, int]:
    if isinstance(raw_imgsz, int | float):
        normalized = max(int(raw_imgsz), 32)
        return normalized, normalized
    if isinstance(raw_imgsz, list | tuple) and len(raw_imgsz) >= 2:
        return max(int(raw_imgsz[0]), 32), max(int(raw_imgsz[1]), 32)
    return 640, 640


class YoloePromptFreeRuntimeSession:
    """可重复执行的 project-native YOLOE prompt-free 推理会话。"""

    def __init__(
        self,
        *,
        variant: Any,
        device_name: str,
        precision: str,
        imports: Any,
        model: YoloePromptFreeSegmentationModel,
        input_size: tuple[int, int],
        class_names: dict[int, str],
    ) -> None:
        self.variant = variant
        self.device_name = device_name
        self.precision = precision
        self.imports = imports
        self.model = model
        self.input_size = input_size
        self.class_names = class_names

    @classmethod
    def load(
        cls,
        *,
        variant: Any,
        device_name: str,
        precision: str,
    ) -> "YoloePromptFreeRuntimeSession":
        import cv2

        imports = types.SimpleNamespace(cv2=cv2, np=np, torch=torch)
        resolved_device_name = resolve_execution_device_name(
            torch_module=torch,
            requested_device_name=device_name,
        )
        if precision == "fp16" and not resolved_device_name.startswith("cuda"):
            raise InvalidRequestError(
                "YOLOE prompt-free 仅在 CUDA 设备上支持 fp16",
                details={"device": resolved_device_name, "precision": precision},
            )
        enable_pytorch_cuda_inference_fast_path(
            torch_module=torch,
            device_name=resolved_device_name,
        )
        artifacts = load_prompt_free_checkpoint_artifacts(checkpoint_path=variant.checkpoint_path)
        model = build_yoloe_prompt_free_segmentation_model(
            model_name=variant.model_name,
            model_scale=artifacts.model_scale,
            num_classes=len(artifacts.class_names),
            model_config=artifacts.model_config,
            input_channels=int(artifacts.model_config.get("ch", 3)),
        )
        incompatible = model.load_state_dict(artifacts.state_dict, strict=False)
        unexpected_keys = tuple(incompatible.unexpected_keys)
        missing_keys = tuple(incompatible.missing_keys)
        if unexpected_keys or missing_keys:
            raise InvalidRequestError(
                "YOLOE prompt-free checkpoint 与 project-native 模型结构不兼容",
                details={
                    "checkpoint_path": str(variant.checkpoint_path),
                    "unexpected_keys": list(unexpected_keys),
                    "missing_keys": list(missing_keys),
                },
            )
        model.names = dict(artifacts.class_names)
        model.stride = torch.tensor((8.0, 16.0, 32.0), dtype=torch.float32)
        model.to(resolved_device_name)
        if precision == "fp16":
            model.half()
        model.eval()
        return cls(
            variant=variant,
            device_name=resolved_device_name,
            precision=precision,
            imports=imports,
            model=model,
            input_size=artifacts.input_size,
            class_names=artifacts.class_names,
        )

    @torch.inference_mode()
    def predict(
        self,
        *,
        image_bytes: bytes,
        confidence_threshold: float,
        iou_threshold: float,
        max_detections: int,
    ) -> ProjectNativeYoloePrediction:
        image = _decode_runtime_image(self.imports.cv2, self.imports.np, image_bytes)
        input_array, resize_ratio = preprocess_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
            input_size=self.input_size,
        )
        input_tensor = self.imports.torch.from_numpy(input_array).unsqueeze(0).to(self.device_name)
        input_tensor = input_tensor.float()
        if self.precision == "fp16":
            input_tensor = input_tensor.half()
        prediction_tensor, proto_tensor = self.model(input_tensor)
        prediction_array = prediction_tensor.detach().float().cpu().numpy()
        proto_array = proto_tensor.detach().float().cpu().numpy()
        detections, regions = _postprocess_prompt_free_outputs(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            prediction_array=prediction_array,
            proto_array=proto_array,
            class_names=self.class_names,
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
            max_detections=max_detections,
            resize_ratio=resize_ratio,
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            input_size=self.input_size,
        )
        summary = {
            "model_series": self.variant.model_series,
            "model_scale": self.variant.model_scale,
            "variant_name": self.variant.variant_name,
            "checkpoint_path": str(self.variant.checkpoint_path),
            "task_type": self.variant.task_type,
            "prompt_count": 0,
            "detection_count": len(detections),
            "region_count": len(regions),
            "device": self.device_name,
            "precision": self.precision,
            "confidence_threshold": float(confidence_threshold),
            "iou_threshold": float(iou_threshold),
            "max_detections": int(max_detections),
            "prompt_free": True,
            "inference_mode": "prompt-free",
            "vocabulary_size": len(self.class_names),
            "top_classes": [str(item["class_name"]) for item in detections[:5]],
            "input_size": [int(self.input_size[0]), int(self.input_size[1])],
            "project_native": True,
        }
        return ProjectNativeYoloePrediction(
            detections=tuple(detections),
            regions=tuple(regions),
            summary=summary,
        )


class YoloeTextPromptRuntimeSession:
    """可重复执行的 project-native YOLOE text-prompt 推理会话。"""

    NEGATIVE_PROMPT_WEIGHT = 0.5

    def __init__(
        self,
        *,
        variant: Any,
        device_name: str,
        precision: str,
        imports: Any,
        model: YoloeTextPromptSegmentationModel,
        input_size: tuple[int, int],
    ) -> None:
        self.variant = variant
        self.device_name = device_name
        self.precision = precision
        self.imports = imports
        self.model = model
        self.input_size = input_size
        self.text_encoder = get_or_create_mobileclip_blt_text_encoder(device=device_name)

    @classmethod
    def load(
        cls,
        *,
        variant: Any,
        device_name: str,
        precision: str,
    ) -> "YoloeTextPromptRuntimeSession":
        import cv2

        imports = types.SimpleNamespace(cv2=cv2, np=np, torch=torch)
        resolved_device_name = resolve_execution_device_name(
            torch_module=torch,
            requested_device_name=device_name,
        )
        if precision == "fp16" and not resolved_device_name.startswith("cuda"):
            raise InvalidRequestError(
                "YOLOE text-prompt 仅在 CUDA 设备上支持 fp16",
                details={"device": resolved_device_name, "precision": precision},
            )
        enable_pytorch_cuda_inference_fast_path(
            torch_module=torch,
            device_name=resolved_device_name,
        )
        artifacts = load_prompt_free_checkpoint_artifacts(checkpoint_path=variant.checkpoint_path)
        model = build_yoloe_text_prompt_segmentation_model(
            model_name=variant.model_name,
            model_scale=artifacts.model_scale,
            num_classes=len(artifacts.class_names),
            model_config=artifacts.model_config,
            input_channels=int(artifacts.model_config.get("ch", 3)),
        )
        incompatible = model.load_state_dict(artifacts.state_dict, strict=False)
        unexpected_keys = tuple(
            key for key in incompatible.unexpected_keys if not key.startswith("model.22.lrpc.")
        )
        missing_keys = tuple(
            key for key in incompatible.missing_keys if not key.startswith("model.22.lrpc.")
        )
        if unexpected_keys or missing_keys:
            raise InvalidRequestError(
                "YOLOE text-prompt checkpoint 与 project-native 模型结构不兼容",
                details={
                    "checkpoint_path": str(variant.checkpoint_path),
                    "unexpected_keys": list(unexpected_keys),
                    "missing_keys": list(missing_keys),
                },
            )
        model.names = dict(artifacts.class_names)
        model.stride = torch.tensor((8.0, 16.0, 32.0), dtype=torch.float32)
        model.to(resolved_device_name)
        if precision == "fp16":
            model.half()
        model.eval()
        return cls(
            variant=variant,
            device_name=resolved_device_name,
            precision=precision,
            imports=imports,
            model=model,
            input_size=artifacts.input_size,
        )

    @torch.inference_mode()
    def predict(
        self,
        *,
        image_bytes: bytes,
        prompts: tuple[Any, ...],
        confidence_threshold: float,
        iou_threshold: float,
        max_detections: int,
    ) -> ProjectNativeYoloePrediction:
        if not prompts:
            raise InvalidRequestError("YOLOE text-prompt 节点要求 prompts 不能为空")
        image = _decode_runtime_image(self.imports.cv2, self.imports.np, image_bytes)
        input_array, resize_ratio = preprocess_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
            input_size=self.input_size,
        )
        input_tensor = self.imports.torch.from_numpy(input_array).unsqueeze(0).to(self.device_name)
        input_tensor = input_tensor.float()
        if self.precision == "fp16":
            input_tensor = input_tensor.half()

        prompt_groups = merge_text_prompt_items(prompts)
        prompt_texts: list[str] = []
        prompt_text_offsets: list[tuple[int, int, int]] = []
        prompt_display_names: dict[int, str] = {}
        prompt_id_map: dict[int, str] = {}
        source_text_map: dict[int, str] = {}
        positive_text_map: dict[int, tuple[str, ...]] = {}
        negative_text_map: dict[int, tuple[str, ...]] = {}
        for index, group in enumerate(prompt_groups):
            prompt_display_names[index] = str(group.display_name)
            prompt_id_map[index] = str(group.prompt_id)
            positive_text_map[index] = tuple(group.positive_texts)
            negative_text_map[index] = tuple(group.negative_texts)
            source_text_map[index] = _build_group_source_prompt_text(group)
            positive_start = len(prompt_texts)
            prompt_texts.extend(group.positive_texts)
            negative_start = len(prompt_texts)
            prompt_texts.extend(group.negative_texts)
            prompt_text_offsets.append(
                (
                    positive_start,
                    len(group.positive_texts),
                    len(group.negative_texts),
                )
            )

        if not prompt_texts:
            raise InvalidRequestError("YOLOE text-prompt 节点要求至少包含一条 positive 文本提示")
        tokens = self.text_encoder.tokenize(prompt_texts)
        text_features = self.text_encoder.encode_text(tokens).to(dtype=input_tensor.dtype)
        grouped_text_features = _build_grouped_text_features(
            text_features=text_features,
            prompt_text_offsets=tuple(prompt_text_offsets),
            negative_prompt_weight=self.NEGATIVE_PROMPT_WEIGHT,
        )
        class_embeddings = self.model.model[-1].get_tpe(grouped_text_features.unsqueeze(0))
        if class_embeddings is None:
            raise InvalidRequestError("YOLOE text-prompt 无法生成类别 embedding")

        prediction_tensor, proto_tensor = self.model(input_tensor, class_embeddings)
        prediction_array = prediction_tensor.detach().float().cpu().numpy()
        proto_array = proto_tensor.detach().float().cpu().numpy()
        detections, regions = _postprocess_prompt_free_outputs(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            prediction_array=prediction_array,
            proto_array=proto_array,
            class_names=prompt_display_names,
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
            max_detections=max_detections,
            resize_ratio=resize_ratio,
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            input_size=self.input_size,
        )
        for item in detections:
            class_id = int(item["class_id"])
            item["prompt_id"] = prompt_id_map.get(class_id)
            item["source_prompt_text"] = source_text_map.get(class_id)
            item["source_prompt_positive_texts"] = list(positive_text_map.get(class_id, ()))
            item["source_prompt_negative_texts"] = list(negative_text_map.get(class_id, ()))
        for item in regions:
            class_id = int(item["class_id"])
            item["prompt_id"] = prompt_id_map.get(class_id)
            item["source_prompt_text"] = source_text_map.get(class_id)
            item["source_prompt_positive_texts"] = list(positive_text_map.get(class_id, ()))
            item["source_prompt_negative_texts"] = list(negative_text_map.get(class_id, ()))

        summary = {
            "model_series": self.variant.model_series,
            "model_scale": self.variant.model_scale,
            "variant_name": self.variant.variant_name,
            "checkpoint_path": str(self.variant.checkpoint_path),
            "task_type": self.variant.task_type,
            "prompt_count": len(prompt_groups),
            "prompt_item_count": len(prompts),
            "prompt_group_count": len(prompt_groups),
            "positive_prompt_count": sum(len(group.positive_texts) for group in prompt_groups),
            "negative_prompt_count": sum(len(group.negative_texts) for group in prompt_groups),
            "detection_count": len(detections),
            "region_count": len(regions),
            "device": self.device_name,
            "precision": self.precision,
            "confidence_threshold": float(confidence_threshold),
            "iou_threshold": float(iou_threshold),
            "max_detections": int(max_detections),
            "prompt_free": False,
            "inference_mode": "text-prompt",
            "text_encoder": "mobileclip/blt",
            "negative_prompt_weight": self.NEGATIVE_PROMPT_WEIGHT,
            "prompt_groups": [
                {
                    "prompt_id": group.prompt_id,
                    "display_name": group.display_name,
                    "positive_texts": list(group.positive_texts),
                    "negative_texts": list(group.negative_texts),
                    "languages": list(group.languages),
                }
                for group in prompt_groups
            ],
            "project_native": True,
        }
        return ProjectNativeYoloePrediction(
            detections=tuple(detections),
            regions=tuple(regions),
            summary=summary,
        )


def _build_grouped_text_features(
    *,
    text_features: torch.Tensor,
    prompt_text_offsets: tuple[tuple[int, int, int], ...],
    negative_prompt_weight: float,
) -> torch.Tensor:
    """按 prompt 组聚合文本特征，并把负文本作为抑制项并入类别原型。"""

    grouped_features: list[torch.Tensor] = []
    for positive_start, positive_count, negative_count in prompt_text_offsets:
        positive_end = positive_start + positive_count
        positive_features = text_features[positive_start:positive_end]
        if int(positive_features.shape[0]) <= 0:
            raise InvalidRequestError("YOLOE text-prompt 组内缺少 positive 文本特征")
        positive_feature = F.normalize(positive_features.mean(dim=0, keepdim=False), dim=0, p=2)
        if negative_count > 0:
            negative_start = positive_end
            negative_end = negative_start + negative_count
            negative_features = text_features[negative_start:negative_end]
            negative_feature = F.normalize(negative_features.mean(dim=0, keepdim=False), dim=0, p=2)
            positive_feature = F.normalize(
                positive_feature - float(negative_prompt_weight) * negative_feature,
                dim=0,
                p=2,
            )
        grouped_features.append(positive_feature)
    return torch.stack(grouped_features, dim=0)


def _build_group_source_prompt_text(group: Any) -> str:
    """为检测结果和 region 结果构造可追溯的文本组合摘要。"""

    positive_segment = " | ".join(str(item) for item in group.positive_texts)
    if not group.negative_texts:
        return positive_segment
    negative_segment = " | ".join(f"!{item}" for item in group.negative_texts)
    return f"{positive_segment} || {negative_segment}"


class YoloeVisualPromptRuntimeSession:
    """可重复执行的 project-native YOLOE visual-prompt 推理会话。"""

    def __init__(
        self,
        *,
        variant: Any,
        device_name: str,
        precision: str,
        imports: Any,
        model: YoloeTextPromptSegmentationModel,
        input_size: tuple[int, int],
    ) -> None:
        self.variant = variant
        self.device_name = device_name
        self.precision = precision
        self.imports = imports
        self.model = model
        self.input_size = input_size

    @classmethod
    def load(
        cls,
        *,
        variant: Any,
        device_name: str,
        precision: str,
    ) -> "YoloeVisualPromptRuntimeSession":
        import cv2

        imports = types.SimpleNamespace(cv2=cv2, np=np, torch=torch)
        resolved_device_name = resolve_execution_device_name(
            torch_module=torch,
            requested_device_name=device_name,
        )
        if precision == "fp16" and not resolved_device_name.startswith("cuda"):
            raise InvalidRequestError(
                "YOLOE visual-prompt 仅在 CUDA 设备上支持 fp16",
                details={"device": resolved_device_name, "precision": precision},
            )
        enable_pytorch_cuda_inference_fast_path(
            torch_module=torch,
            device_name=resolved_device_name,
        )
        artifacts = load_prompt_free_checkpoint_artifacts(checkpoint_path=variant.checkpoint_path)
        model = build_yoloe_text_prompt_segmentation_model(
            model_name=variant.model_name,
            model_scale=artifacts.model_scale,
            num_classes=len(artifacts.class_names),
            model_config=artifacts.model_config,
            input_channels=int(artifacts.model_config.get("ch", 3)),
        )
        incompatible = model.load_state_dict(artifacts.state_dict, strict=False)
        unexpected_keys = tuple(
            key for key in incompatible.unexpected_keys if not key.startswith("model.22.lrpc.")
        )
        missing_keys = tuple(
            key for key in incompatible.missing_keys if not key.startswith("model.22.lrpc.")
        )
        if unexpected_keys or missing_keys:
            raise InvalidRequestError(
                "YOLOE visual-prompt checkpoint 与 project-native 模型结构不兼容",
                details={
                    "checkpoint_path": str(variant.checkpoint_path),
                    "unexpected_keys": list(unexpected_keys),
                    "missing_keys": list(missing_keys),
                },
            )
        model.names = dict(artifacts.class_names)
        model.stride = torch.tensor((8.0, 16.0, 32.0), dtype=torch.float32)
        model.to(resolved_device_name)
        if precision == "fp16":
            model.half()
        model.eval()
        return cls(
            variant=variant,
            device_name=resolved_device_name,
            precision=precision,
            imports=imports,
            model=model,
            input_size=artifacts.input_size,
        )

    @torch.inference_mode()
    def predict(
        self,
        *,
        image_bytes: bytes,
        prompt_image_bytes: bytes,
        prompts: tuple[Any, ...],
        confidence_threshold: float,
        iou_threshold: float,
        max_detections: int,
    ) -> ProjectNativeYoloePrediction:
        if not prompts:
            raise InvalidRequestError("YOLOE visual-prompt 节点要求 prompts 不能为空")
        image = _decode_runtime_image(self.imports.cv2, self.imports.np, image_bytes)
        prompt_image = _decode_runtime_image(self.imports.cv2, self.imports.np, prompt_image_bytes)
        input_array, resize_ratio = preprocess_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=image,
            input_size=self.input_size,
        )
        input_tensor = self.imports.torch.from_numpy(input_array).unsqueeze(0).to(self.device_name)
        input_tensor = input_tensor.float()
        if self.precision == "fp16":
            input_tensor = input_tensor.half()

        prompt_array, prompt_resize_ratio = preprocess_image(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            image=prompt_image,
            input_size=self.input_size,
        )
        prompt_input_tensor = self.imports.torch.from_numpy(prompt_array).unsqueeze(0).to(self.device_name)
        prompt_input_tensor = prompt_input_tensor.float()
        if self.precision == "fp16":
            prompt_input_tensor = prompt_input_tensor.half()

        visual_prompt_tensor = _build_visual_prompt_tensor(
            torch_module=self.imports.torch,
            np_module=self.imports.np,
            prompts=prompts,
            input_size=self.input_size,
            resize_ratio=prompt_resize_ratio,
            prompt_image_width=int(prompt_image.shape[1]),
            prompt_image_height=int(prompt_image.shape[0]),
            device_name=self.device_name,
            dtype=prompt_input_tensor.dtype,
        )
        class_embeddings = _extract_visual_prompt_embeddings(
            model=self.model,
            prompt_input_tensor=prompt_input_tensor,
            visual_prompt_tensor=visual_prompt_tensor,
        )
        prediction_tensor, proto_tensor = _forward_with_class_embeddings(
            model=self.model,
            input_tensor=input_tensor,
            class_embeddings=class_embeddings,
        )
        prediction_array = prediction_tensor.detach().float().cpu().numpy()
        proto_array = proto_tensor.detach().float().cpu().numpy()
        prompt_display_names = {index: str(item.display_name) for index, item in enumerate(prompts)}
        prompt_id_map = {index: str(item.prompt_id) for index, item in enumerate(prompts)}
        detections, regions = _postprocess_prompt_free_outputs(
            cv2_module=self.imports.cv2,
            np_module=self.imports.np,
            prediction_array=prediction_array,
            proto_array=proto_array,
            class_names=prompt_display_names,
            confidence_threshold=confidence_threshold,
            iou_threshold=iou_threshold,
            max_detections=max_detections,
            resize_ratio=resize_ratio,
            image_width=int(image.shape[1]),
            image_height=int(image.shape[0]),
            input_size=self.input_size,
        )
        for item in detections:
            class_id = int(item["class_id"])
            item["prompt_id"] = prompt_id_map.get(class_id)
        for item in regions:
            class_id = int(item["class_id"])
            item["prompt_id"] = prompt_id_map.get(class_id)
        visual_prompt_kinds = tuple(
            sorted(
                {
                    str(kind)
                    for item in prompts
                    for kind in (
                        tuple(getattr(item, "prompt_kinds", ())) or (str(getattr(item, "prompt_kind", "mixed")),)
                    )
                }
            )
        )
        prompt_item_count = sum(max(1, int(getattr(item, "raw_item_count", 1))) for item in prompts)
        prompt_kind_counts: dict[str, int] = {}
        for item in prompts:
            normalized_prompt_kinds = tuple(getattr(item, "prompt_kinds", ())) or (
                str(getattr(item, "prompt_kind", "mixed")),
            )
            for prompt_kind in normalized_prompt_kinds:
                prompt_kind_counts[str(prompt_kind)] = int(prompt_kind_counts.get(str(prompt_kind), 0)) + 1

        summary = {
            "model_series": self.variant.model_series,
            "model_scale": self.variant.model_scale,
            "variant_name": self.variant.variant_name,
            "checkpoint_path": str(self.variant.checkpoint_path),
            "task_type": self.variant.task_type,
            "prompt_count": len(prompts),
            "prompt_item_count": int(prompt_item_count),
            "prompt_group_count": len(prompts),
            "detection_count": len(detections),
            "region_count": len(regions),
            "device": self.device_name,
            "precision": self.precision,
            "confidence_threshold": float(confidence_threshold),
            "iou_threshold": float(iou_threshold),
            "max_detections": int(max_detections),
            "prompt_free": False,
            "inference_mode": "visual-prompt",
            "visual_prompt_kinds": list(visual_prompt_kinds),
            "visual_prompt_kind": visual_prompt_kinds[0] if len(visual_prompt_kinds) == 1 else "mixed",
            "prompt_kind_counts": prompt_kind_counts,
            "prompt_groups": [
                {
                    "prompt_id": str(getattr(item, "prompt_id", "")),
                    "display_name": str(getattr(item, "display_name", "") or getattr(item, "prompt_id", "")),
                    "prompt_kind": str(getattr(item, "prompt_kind", "mixed")),
                    "prompt_kinds": list(tuple(getattr(item, "prompt_kinds", ())) or (str(getattr(item, "prompt_kind", "mixed")),)),
                    "raw_item_count": max(1, int(getattr(item, "raw_item_count", 1))),
                    **(
                        {"bbox_xyxy": [float(value) for value in getattr(item, "bbox_xyxy", ())]}
                        if getattr(item, "bbox_xyxy", None) is not None
                        else {}
                    ),
                    **(
                        {"point_xy": [float(value) for value in getattr(item, "point_xy", ())]}
                        if getattr(item, "point_xy", None) is not None
                        else {}
                    ),
                    **(
                        {"point_label": str(getattr(item, "point_label"))}
                        if getattr(item, "point_label", None) is not None
                        else {}
                    ),
                    **(
                        {"polygon_xy": [[float(value) for value in point] for point in getattr(item, "polygon_xy", ())]}
                        if getattr(item, "polygon_xy", None) is not None
                        else {}
                    ),
                    **({"has_prompt_mask": True} if getattr(item, "prompt_mask", None) is not None else {}),
                }
                for item in prompts
            ],
            "project_native": True,
        }
        return ProjectNativeYoloePrediction(
            detections=tuple(detections),
            regions=tuple(regions),
            summary=summary,
        )


def _forward_with_class_embeddings(
    *,
    model: YoloeTextPromptSegmentationModel,
    input_tensor: torch.Tensor,
    class_embeddings: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """执行一次带类别 embedding 的 YOLOE segmentation 前向。"""

    prediction = model(input_tensor, class_embeddings)
    if not isinstance(prediction, tuple) or len(prediction) != 2:
        raise InvalidRequestError("YOLOE segmentation 头输出格式不合法")
    prediction_tensor, proto_tensor = prediction
    if not torch.is_tensor(prediction_tensor) or not torch.is_tensor(proto_tensor):
        raise InvalidRequestError("YOLOE segmentation 头输出张量类型不合法")
    return prediction_tensor, proto_tensor


def _extract_visual_prompt_embeddings(
    *,
    model: YoloeTextPromptSegmentationModel,
    prompt_input_tensor: torch.Tensor,
    visual_prompt_tensor: torch.Tensor,
) -> torch.Tensor:
    """从 prompt image 与视觉提示 mask 中提取 visual prompt embedding。"""

    outputs: list[Any] = []
    current: Any = prompt_input_tensor
    for layer in model.model:
        from_index = getattr(layer, "from_index", -1)
        if isinstance(from_index, tuple):
            layer_input = [current if index == -1 else outputs[index] for index in from_index]
        else:
            layer_input = current if from_index == -1 else outputs[from_index]
        if isinstance(layer, YoloeTextPromptSegmentationHead):
            return layer.get_vpe(layer_input, visual_prompt_tensor)
        current = layer(layer_input)
        outputs.append(current)
    raise InvalidRequestError("YOLOE visual-prompt 无法从模型中提取 visual embedding")


def _build_visual_prompt_tensor(
    *,
    torch_module: Any,
    np_module: Any,
    prompts: tuple[Any, ...],
    input_size: tuple[int, int],
    resize_ratio: float,
    prompt_image_width: int,
    prompt_image_height: int,
    device_name: str,
    dtype: torch.dtype,
) -> torch.Tensor:
    """把多种视觉提示统一转成 SAVPE 可消费的视觉提示张量。"""

    input_height, input_width = (int(input_size[0]), int(input_size[1]))
    visual_height = max(1, input_height // 8)
    visual_width = max(1, input_width // 8)
    full_resolution_tensor = torch_module.zeros(
        (1, len(prompts), input_height, input_width),
        device=device_name,
        dtype=dtype,
    )
    for index, item in enumerate(prompts):
        prompt_mask = _build_visual_prompt_mask(
            np_module=np_module,
            item=item,
            prompt_image_width=prompt_image_width,
            prompt_image_height=prompt_image_height,
        )
        if prompt_mask is None or int(np_module.count_nonzero(prompt_mask)) <= 0:
            continue
        prompt_tensor = torch_module.from_numpy(
            np_module.asarray(prompt_mask, dtype=np_module.float32),
        ).to(device=device_name, dtype=dtype)
        resized_width = max(1, min(input_width, int(round(prompt_image_width * float(resize_ratio)))))
        resized_height = max(1, min(input_height, int(round(prompt_image_height * float(resize_ratio)))))
        prompt_tensor = F.interpolate(
            prompt_tensor.unsqueeze(0).unsqueeze(0),
            size=(resized_height, resized_width),
            mode="nearest",
        )[0, 0]
        full_resolution_tensor[0, index, :resized_height, :resized_width] = prompt_tensor
    visual_tensor = F.max_pool2d(full_resolution_tensor, kernel_size=8, stride=8)
    if int(visual_tensor.shape[-2]) != visual_height or int(visual_tensor.shape[-1]) != visual_width:
        visual_tensor = F.interpolate(
            visual_tensor,
            size=(visual_height, visual_width),
            mode="nearest",
        )
    return visual_tensor


def _build_visual_prompt_mask(
    *,
    np_module: Any,
    item: Any,
    prompt_image_width: int,
    prompt_image_height: int,
) -> Any:
    """把单条视觉提示转换成参考图尺寸的二值 mask。"""

    prompt_mask = np_module.zeros((int(prompt_image_height), int(prompt_image_width)), dtype=np_module.uint8)
    if getattr(item, "prompt_mask", None) is not None:
        normalized_prompt_mask = np_module.asarray(item.prompt_mask, dtype=np_module.uint8)
        if normalized_prompt_mask.ndim != 2:
            return prompt_mask
        if (
            int(normalized_prompt_mask.shape[0]) != int(prompt_image_height)
            or int(normalized_prompt_mask.shape[1]) != int(prompt_image_width)
        ):
            raise InvalidRequestError(
                "YOLOE visual prompt mask 尺寸与 prompt_image 不一致",
                details={
                    "prompt_kind": getattr(item, "prompt_kind", None),
                    "prompt_mask_shape": [
                        int(normalized_prompt_mask.shape[0]),
                        int(normalized_prompt_mask.shape[1]),
                    ],
                    "prompt_image_size": [int(prompt_image_width), int(prompt_image_height)],
                },
            )
        return (normalized_prompt_mask > 0).astype(np_module.uint8)
    if getattr(item, "prompt_kind", "") == "box" and getattr(item, "bbox_xyxy", None) is not None:
        x1_value, y1_value, x2_value, y2_value = item.bbox_xyxy
        x1_index = max(0, min(int(prompt_image_width), int(np.floor(float(x1_value)))))
        y1_index = max(0, min(int(prompt_image_height), int(np.floor(float(y1_value)))))
        x2_index = max(x1_index + 1, min(int(prompt_image_width), int(np.ceil(float(x2_value)))))
        y2_index = max(y1_index + 1, min(int(prompt_image_height), int(np.ceil(float(y2_value)))))
        if x2_index <= x1_index or y2_index <= y1_index:
            return prompt_mask
        prompt_mask[y1_index:y2_index, x1_index:x2_index] = 1
        return prompt_mask
    if getattr(item, "prompt_kind", "") == "point" and getattr(item, "point_xy", None) is not None:
        point_x_value, point_y_value = item.point_xy
        point_x_index = max(0, min(int(prompt_image_width) - 1, int(round(float(point_x_value)))))
        point_y_index = max(0, min(int(prompt_image_height) - 1, int(round(float(point_y_value)))))
        radius = max(1, int(round(min(prompt_image_width, prompt_image_height) / 64.0)))
        x1_index = max(0, point_x_index - radius)
        y1_index = max(0, point_y_index - radius)
        x2_index = min(int(prompt_image_width), point_x_index + radius + 1)
        y2_index = min(int(prompt_image_height), point_y_index + radius + 1)
        prompt_mask[y1_index:y2_index, x1_index:x2_index] = 1
        return prompt_mask
    return prompt_mask


def _decode_runtime_image(cv2_module: Any, np_module: Any, image_bytes: bytes) -> Any:
    image_buffer = np_module.frombuffer(image_bytes, dtype=np_module.uint8)
    image = cv2_module.imdecode(image_buffer, cv2_module.IMREAD_COLOR)
    if image is None:
        raise InvalidRequestError("YOLOE prompt-free 节点收到的图片不是有效图像")
    return image


def _postprocess_prompt_free_outputs(
    *,
    cv2_module: Any,
    np_module: Any,
    prediction_array: Any,
    proto_array: Any,
    class_names: dict[int, str],
    confidence_threshold: float,
    iou_threshold: float,
    max_detections: int,
    resize_ratio: float,
    image_width: int,
    image_height: int,
    input_size: tuple[int, int],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    normalized_prediction = np_module.asarray(prediction_array, dtype=np_module.float32)
    normalized_proto = np_module.asarray(proto_array, dtype=np_module.float32)
    if normalized_prediction.ndim == 2:
        normalized_prediction = np_module.expand_dims(normalized_prediction, axis=0)
    if normalized_proto.ndim == 3:
        normalized_proto = np_module.expand_dims(normalized_proto, axis=0)
    if normalized_prediction.ndim != 3 or normalized_prediction.shape[0] != 1:
        raise InvalidRequestError(
            "YOLOE prompt-free 推理输出维度不合法",
            details={"prediction_shape": list(normalized_prediction.shape)},
        )
    if normalized_proto.ndim != 4 or normalized_proto.shape[0] != 1:
        raise InvalidRequestError(
            "YOLOE prompt-free proto 输出维度不合法",
            details={"proto_shape": list(normalized_proto.shape)},
        )
    num_classes = len(class_names)
    if int(normalized_prediction.shape[2]) <= 4 + num_classes:
        raise InvalidRequestError(
            "YOLOE prompt-free 推理输出通道数不足",
            details={
                "channel_count": int(normalized_prediction.shape[2]),
                "required_min_channels": 5 + num_classes,
            },
        )

    image_prediction = normalized_prediction[0]
    boxes = image_prediction[:, :4]
    class_scores = image_prediction[:, 4 : 4 + num_classes]
    mask_coefficients = image_prediction[:, 4 + num_classes :]
    if int(boxes.shape[0]) <= 0:
        return [], []

    best_scores = np_module.max(class_scores, axis=1)
    best_class_ids = np_module.argmax(class_scores, axis=1).astype(np_module.int32, copy=False)
    keep_mask = best_scores >= float(confidence_threshold)
    boxes = boxes[keep_mask]
    best_scores = best_scores[keep_mask]
    best_class_ids = best_class_ids[keep_mask]
    mask_coefficients = mask_coefficients[keep_mask]
    if int(boxes.shape[0]) <= 0:
        return [], []

    keep_indices = batched_nms_indices(
        boxes=boxes,
        scores=best_scores,
        class_ids=best_class_ids,
        nms_threshold=float(iou_threshold),
        np_module=np_module,
    )
    if int(keep_indices.size) <= 0:
        return [], []

    keep_indices = keep_indices[: int(max_detections)]
    boxes = boxes[keep_indices]
    best_scores = best_scores[keep_indices]
    best_class_ids = best_class_ids[keep_indices]
    mask_coefficients = mask_coefficients[keep_indices]

    resized_height = min(int(round(image_height * resize_ratio)), int(input_size[0]))
    resized_width = min(int(round(image_width * resize_ratio)), int(input_size[1]))
    proto = normalized_proto[0]
    masks = _decode_segmentation_masks(
        cv2_module=cv2_module,
        np_module=np_module,
        proto=proto,
        mask_coefficients=mask_coefficients,
        input_size=input_size,
        resized_width=resized_width,
        resized_height=resized_height,
        image_width=image_width,
        image_height=image_height,
    )

    detections: list[dict[str, object]] = []
    regions: list[dict[str, object]] = []
    for index, (bbox, score, class_id, binary_mask) in enumerate(
        zip(boxes, best_scores, best_class_ids, masks, strict=True),
        start=1,
    ):
        scaled_bbox = bbox / max(resize_ratio, 1e-8)
        x1 = float(max(0.0, min(float(scaled_bbox[0]), float(image_width))))
        y1 = float(max(0.0, min(float(scaled_bbox[1]), float(image_height))))
        x2 = float(max(0.0, min(float(scaled_bbox[2]), float(image_width))))
        y2 = float(max(0.0, min(float(scaled_bbox[3]), float(image_height))))
        class_index = int(class_id)
        class_name = class_names.get(class_index, str(class_index))
        bbox_xyxy = [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)]
        detections.append(
            {
                "bbox_xyxy": bbox_xyxy,
                "score": round(float(score), 6),
                "class_id": class_index,
                "class_name": class_name,
            }
        )
        polygon_xy = _extract_primary_polygon(cv2_module=cv2_module, binary_mask=binary_mask, fallback_bbox_xyxy=bbox_xyxy)
        mask_png_bytes, mask_width, mask_height, mask_area = _encode_binary_mask_png(binary_mask)
        region_item = {
            "region_id": f"region-{index}",
            "bbox_xyxy": bbox_xyxy,
            "score": round(float(score), 6),
            "class_id": class_index,
            "class_name": class_name,
            "polygon_xy": polygon_xy,
            "area": int(mask_area),
        }
        if mask_png_bytes is not None and mask_width is not None and mask_height is not None:
            region_item["mask_png_bytes"] = mask_png_bytes
            region_item["mask_width"] = mask_width
            region_item["mask_height"] = mask_height
        regions.append(region_item)
    return detections, regions


def _decode_segmentation_masks(
    *,
    cv2_module: Any,
    np_module: Any,
    proto: Any,
    mask_coefficients: Any,
    input_size: tuple[int, int],
    resized_width: int,
    resized_height: int,
    image_width: int,
    image_height: int,
    mask_threshold: float = 0.5,
) -> list[Any]:
    proto_features = proto.reshape(int(proto.shape[0]), -1)
    mask_logits = mask_coefficients @ proto_features
    mask_logits = mask_logits.reshape(int(mask_coefficients.shape[0]), int(proto.shape[1]), int(proto.shape[2]))
    masks: list[Any] = []
    for mask_logit in mask_logits:
        clipped_mask_logit = np_module.clip(mask_logit, -50.0, 50.0)
        probability_mask = 1.0 / (1.0 + np_module.exp(-clipped_mask_logit))
        resized_mask = cv2_module.resize(
            probability_mask,
            (int(input_size[1]), int(input_size[0])),
            interpolation=cv2_module.INTER_LINEAR,
        )
        cropped_mask = resized_mask[:resized_height, :resized_width]
        restored_mask = cv2_module.resize(
            cropped_mask,
            (int(image_width), int(image_height)),
            interpolation=cv2_module.INTER_LINEAR,
        )
        binary_mask = (restored_mask >= float(mask_threshold)).astype(np_module.uint8)
        masks.append(binary_mask)
    return masks


def _extract_primary_polygon(*, cv2_module: Any, binary_mask: Any, fallback_bbox_xyxy: list[float]) -> list[list[float]]:
    contours, _hierarchy = cv2_module.findContours(
        binary_mask,
        cv2_module.RETR_EXTERNAL,
        cv2_module.CHAIN_APPROX_SIMPLE,
    )
    best_polygon: list[list[float]] | None = None
    best_area = -1.0
    for contour in contours:
        if contour is None or len(contour) < 3:
            continue
        flattened = contour.reshape(-1, 2)
        area = float(cv2_module.contourArea(flattened))
        if area <= best_area:
            continue
        best_area = area
        best_polygon = [[round(float(point[0]), 3), round(float(point[1]), 3)] for point in flattened]
    if best_polygon:
        return best_polygon
    x1_value, y1_value, x2_value, y2_value = fallback_bbox_xyxy
    return [
        [float(x1_value), float(y1_value)],
        [float(x2_value), float(y1_value)],
        [float(x2_value), float(y2_value)],
        [float(x1_value), float(y2_value)],
    ]


def _encode_binary_mask_png(binary_mask: Any) -> tuple[bytes | None, int | None, int | None, int]:
    normalized_mask = np.asarray(binary_mask, dtype=np.uint8)
    if normalized_mask.ndim != 2:
        return None, None, None, 0
    encoded_mask = normalized_mask * 255
    mask_height, mask_width = encoded_mask.shape
    mask_area = int(np.count_nonzero(normalized_mask))
    encoded_image = Image.fromarray(encoded_mask, mode="L")
    buffer = io.BytesIO()
    encoded_image.save(buffer, format="PNG")
    return buffer.getvalue(), int(mask_width), int(mask_height), mask_area


_PROMPT_FREE_RUNTIME_CACHE: dict[tuple[str, str, str], YoloePromptFreeRuntimeSession] = {}
_PROMPT_FREE_RUNTIME_CACHE_LOCK = Lock()
_TEXT_PROMPT_RUNTIME_CACHE: dict[tuple[str, str, str], YoloeTextPromptRuntimeSession] = {}
_TEXT_PROMPT_RUNTIME_CACHE_LOCK = Lock()
_VISUAL_PROMPT_RUNTIME_CACHE: dict[tuple[str, str, str], YoloeVisualPromptRuntimeSession] = {}
_VISUAL_PROMPT_RUNTIME_CACHE_LOCK = Lock()


def get_or_create_prompt_free_runtime_session(
    *,
    variant: Any,
    device_name: str,
    precision: str,
) -> YoloePromptFreeRuntimeSession:
    """返回可复用的 YOLOE prompt-free project-native 会话。"""

    cache_key = (
        str(variant.checkpoint_path),
        str(device_name).strip().lower(),
        str(precision).strip().lower(),
    )
    with _PROMPT_FREE_RUNTIME_CACHE_LOCK:
        cached_session = _PROMPT_FREE_RUNTIME_CACHE.get(cache_key)
        if cached_session is not None:
            return cached_session
        runtime_session = YoloePromptFreeRuntimeSession.load(
            variant=variant,
            device_name=device_name,
            precision=precision,
        )
        _PROMPT_FREE_RUNTIME_CACHE[cache_key] = runtime_session
        return runtime_session


def get_or_create_text_prompt_runtime_session(
    *,
    variant: Any,
    device_name: str,
    precision: str,
) -> YoloeTextPromptRuntimeSession:
    """返回可复用的 YOLOE text-prompt project-native 会话。"""

    cache_key = (
        str(variant.checkpoint_path),
        str(device_name).strip().lower(),
        str(precision).strip().lower(),
    )
    with _TEXT_PROMPT_RUNTIME_CACHE_LOCK:
        cached_session = _TEXT_PROMPT_RUNTIME_CACHE.get(cache_key)
        if cached_session is not None:
            return cached_session
        runtime_session = YoloeTextPromptRuntimeSession.load(
            variant=variant,
            device_name=device_name,
            precision=precision,
        )
        _TEXT_PROMPT_RUNTIME_CACHE[cache_key] = runtime_session
        return runtime_session


def get_or_create_visual_prompt_runtime_session(
    *,
    variant: Any,
    device_name: str,
    precision: str,
) -> YoloeVisualPromptRuntimeSession:
    """返回可复用的 YOLOE visual-prompt project-native 会话。"""

    cache_key = (
        str(variant.checkpoint_path),
        str(device_name).strip().lower(),
        str(precision).strip().lower(),
    )
    with _VISUAL_PROMPT_RUNTIME_CACHE_LOCK:
        cached_session = _VISUAL_PROMPT_RUNTIME_CACHE.get(cache_key)
        if cached_session is not None:
            return cached_session
        runtime_session = YoloeVisualPromptRuntimeSession.load(
            variant=variant,
            device_name=device_name,
            precision=precision,
        )
        _VISUAL_PROMPT_RUNTIME_CACHE[cache_key] = runtime_session
        return runtime_session


__all__ = [
    "ProjectNativeYoloePrediction",
    "YoloePromptFreeRuntimeSession",
    "YoloeTextPromptRuntimeSession",
    "YoloeVisualPromptRuntimeSession",
    "build_yoloe_prompt_free_segmentation_model",
    "build_yoloe_text_prompt_segmentation_model",
    "get_or_create_prompt_free_runtime_session",
    "get_or_create_text_prompt_runtime_session",
    "get_or_create_visual_prompt_runtime_session",
    "load_prompt_free_checkpoint_artifacts",
]
