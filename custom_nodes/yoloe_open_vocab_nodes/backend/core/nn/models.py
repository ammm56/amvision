"""YOLOE project-native segmentation 模型结构与构建入口。"""

from __future__ import annotations

from typing import Any

import torch
from torch import nn
import torch.nn.functional as F

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from custom_nodes.yoloe_open_vocab_nodes.backend.core.nn.modules import (
    _YOLOE_CONV_USE_BATCH_NORM,
    _make_divisible,
    YoloeBatchNormContrastiveHead,
    YoloeC2PSA,
    YoloeC2f,
    YoloeC3k2,
    YoloeConcat,
    YoloeConv,
    YoloeDistributionFocalLossDecoder,
    YoloeDWConv,
    YoloeProto,
    YoloeProto26,
    YoloeResidualTextAdapter,
    YoloeSPPF,
    YoloeSpatialAwareVisualPromptEmbedding,
    YoloeSwiGluFeedForward,
)


class YoloePromptFreeRegionProposalHead(nn.Module):
    """YOLOE prompt-free 轻量级候选框与分类头。"""

    def __init__(
        self,
        cls_channels: int,
        loc_channels: int,
        num_classes: int,
        *,
        enabled: bool,
        loc_output_channels: int,
        proposal_filter_channels: int = 1,
    ) -> None:
        super().__init__()
        self.enabled = bool(enabled)
        if self.enabled:
            self.vocab = nn.Linear(cls_channels, num_classes)
        else:
            self.vocab = nn.Conv2d(cls_channels, num_classes, 1)
        self.pf = nn.Conv2d(cls_channels, int(proposal_filter_channels), 1)
        self.loc = nn.Conv2d(loc_channels, int(loc_output_channels), 1)

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
        legacy_class_head: bool = True,
        class_hidden_source_count: int | None = None,
        end2end: bool = False,
        proto26: bool = False,
        proposal_filter_channels: int = 1,
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
        self.legacy_class_head = bool(legacy_class_head)
        self.end2end = bool(end2end)
        self.proto26 = bool(proto26)
        self.conf = 0.001

        box_hidden_channels = max((16, ch[0] // 4, self.reg_max * 4))
        class_hidden_count = self.nc if class_hidden_source_count is None else int(class_hidden_source_count)
        class_hidden_channels = max(ch[0], min(class_hidden_count, 100))
        self.cv2 = None
        self.cv3 = None
        if self.end2end:
            self.one2one_cv2 = self._build_box_feature_head(ch, box_hidden_channels)
            self.one2one_cv3 = self._build_prompt_free_class_head(ch, class_hidden_channels)
        else:
            self.cv2 = self._build_box_feature_head(ch, box_hidden_channels)
            self.cv3 = self._build_prompt_free_class_head(ch, class_hidden_channels)
        self.dfl = YoloeDistributionFocalLossDecoder(self.reg_max) if self.reg_max > 1 else nn.Identity()
        self.proto = (
            YoloeProto26(ch, self.npr, self.nm, class_hidden_count)
            if self.proto26
            else YoloeProto(ch[0], self.npr, self.nm)
        )

        hidden_channels = max(ch[0] // 4, self.nm)
        self.cv5 = self._build_mask_coefficient_head(ch, hidden_channels)
        if self.end2end:
            self.one2one_cv5 = self._build_mask_coefficient_head(ch, hidden_channels)
        self.savpe = YoloeSpatialAwareVisualPromptEmbedding(ch, class_hidden_channels, self.embed)
        self.reprta = (
            YoloeResidualTextAdapter(YoloeSwiGluFeedForward(self.embed, self.embed))
            if self.end2end
            else nn.Identity()
        )
        loc_output_channels = 4 * self.reg_max
        self.lrpc = nn.ModuleList(
            (
                YoloePromptFreeRegionProposalHead(
                    class_hidden_channels,
                    box_hidden_channels,
                    self.nc,
                    enabled=True,
                    loc_output_channels=loc_output_channels,
                    proposal_filter_channels=proposal_filter_channels,
                ),
                YoloePromptFreeRegionProposalHead(
                    class_hidden_channels,
                    box_hidden_channels,
                    self.nc,
                    enabled=True,
                    loc_output_channels=loc_output_channels,
                    proposal_filter_channels=proposal_filter_channels,
                ),
                YoloePromptFreeRegionProposalHead(
                    class_hidden_channels,
                    box_hidden_channels,
                    self.nc,
                    enabled=False,
                    loc_output_channels=loc_output_channels,
                    proposal_filter_channels=proposal_filter_channels,
                ),
            )
        )

    def _build_box_feature_head(self, feature_channels: tuple[int, ...], box_hidden_channels: int) -> nn.ModuleList:
        """构建 LRPC loc 分支前的 box feature head。"""

        return nn.ModuleList(
            nn.Sequential(
                YoloeConv(input_channels, box_hidden_channels, 3),
                YoloeConv(box_hidden_channels, box_hidden_channels, 3),
            )
            for input_channels in feature_channels
        )

    def _build_mask_coefficient_head(self, feature_channels: tuple[int, ...], hidden_channels: int) -> nn.ModuleList:
        """构建 segmentation mask coefficient head。"""

        return nn.ModuleList(
            nn.Sequential(
                YoloeConv(input_channels, hidden_channels, 3),
                YoloeConv(hidden_channels, hidden_channels, 3),
                nn.Conv2d(hidden_channels, self.nm, 1),
            )
            for input_channels in feature_channels
        )

    def _build_prompt_free_class_head(
        self,
        feature_channels: tuple[int, ...],
        class_hidden_channels: int,
    ) -> nn.ModuleList:
        """按 YOLOE 代际构建 prompt-free 分类特征 head。"""

        if self.legacy_class_head:
            return nn.ModuleList(
                nn.Sequential(
                    YoloeConv(input_channels, class_hidden_channels, 3),
                    YoloeConv(class_hidden_channels, class_hidden_channels, 3),
                )
                for input_channels in feature_channels
            )
        return nn.ModuleList(
            nn.Sequential(
                nn.Sequential(
                    YoloeDWConv(input_channels, input_channels, 3),
                    YoloeConv(input_channels, class_hidden_channels, 1),
                ),
                nn.Sequential(
                    YoloeDWConv(class_hidden_channels, class_hidden_channels, 3),
                    YoloeConv(class_hidden_channels, class_hidden_channels, 1),
                ),
            )
            for input_channels in feature_channels
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
        box_head = self.one2one_cv2 if self.end2end else self.cv2
        class_head = self.one2one_cv3 if self.end2end else self.cv3
        mask_head = self.one2one_cv5 if self.end2end else self.cv5
        if box_head is None or class_head is None:
            raise ServiceConfigurationError("YOLOE prompt-free head 缺少可用的 box/class 分支")
        for index in range(self.nl):
            cls_feat = class_head[index](x[index])
            loc_feat = box_head[index](x[index])
            box_output, score_output, keep_mask = self.lrpc[index](cls_feat, loc_feat, self.conf)
            boxes.append(box_output.view(batch_size, self.reg_max * 4, -1))
            scores.append(score_output)
            keep_masks.append(keep_mask)
        mask_coefficients = torch.cat(
            [mask_head[index](x[index]).view(batch_size, self.nm, -1) for index in range(self.nl)],
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
        proto = self.proto(x) if self.proto26 else self.proto(x[0])
        return decoded.transpose(1, 2).contiguous(), proto

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
        use_batch_norm = not bool(model_config.get("end2end", False))
        conv_context_token = _YOLOE_CONV_USE_BATCH_NORM.set(use_batch_norm)
        try:
            self.model, self.save = _parse_prompt_free_model(
                model_name=model_name,
                model_scale=model_scale,
                num_classes=num_classes,
                model_config=model_config,
                input_channels=input_channels,
            )
        finally:
            _YOLOE_CONV_USE_BATCH_NORM.reset(conv_context_token)
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
        legacy_class_head: bool = True,
        class_hidden_source_count: int | None = None,
        proto26: bool = False,
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
        self.legacy_class_head = bool(legacy_class_head)
        self.proto26 = bool(proto26)

        box_hidden_channels = max((16, ch[0] // 4, self.reg_max * 4))
        class_hidden_count = self.nc if class_hidden_source_count is None else int(class_hidden_source_count)
        class_hidden_channels = max(ch[0], min(class_hidden_count, 100))
        self.cv2 = nn.ModuleList(
            nn.Sequential(
                YoloeConv(input_channels, box_hidden_channels, 3),
                YoloeConv(box_hidden_channels, box_hidden_channels, 3),
                nn.Conv2d(box_hidden_channels, 4 * self.reg_max, 1),
            )
            for input_channels in ch
        )
        self.cv3 = self._build_text_class_head(ch, class_hidden_channels)
        self.cv4 = nn.ModuleList(YoloeBatchNormContrastiveHead(self.embed) for _ in ch)
        self.proto = (
            YoloeProto26(ch, self.npr, self.nm, class_hidden_count)
            if self.proto26
            else YoloeProto(ch[0], self.npr, self.nm)
        )
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

    def _build_text_class_head(
        self,
        feature_channels: tuple[int, ...],
        class_hidden_channels: int,
    ) -> nn.ModuleList:
        """按 YOLOE 代际构建 text/visual 分类特征 head。"""

        if self.legacy_class_head:
            return nn.ModuleList(
                nn.Sequential(
                    YoloeConv(input_channels, class_hidden_channels, 3),
                    YoloeConv(class_hidden_channels, class_hidden_channels, 3),
                    nn.Conv2d(class_hidden_channels, self.embed, 1),
                )
                for input_channels in feature_channels
            )
        return nn.ModuleList(
            nn.Sequential(
                nn.Sequential(
                    YoloeDWConv(input_channels, input_channels, 3),
                    YoloeConv(input_channels, class_hidden_channels, 1),
                ),
                nn.Sequential(
                    YoloeDWConv(class_hidden_channels, class_hidden_channels, 3),
                    YoloeConv(class_hidden_channels, class_hidden_channels, 1),
                ),
                nn.Conv2d(class_hidden_channels, self.embed, 1),
            )
            for input_channels in feature_channels
        )

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
        proto = self.proto(x) if self.proto26 else self.proto(x[0])
        return prediction.transpose(1, 2).contiguous(), proto

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
        "C3k2": YoloeC3k2,
        "C2PSA": YoloeC2PSA,
        "SPPF": YoloeSPPF,
        "Concat": YoloeConcat,
        "nn.Upsample": nn.Upsample,
        "YOLOESegment": YoloePromptFreeSegmentationHead,
        "YOLOESegment26": YoloePromptFreeSegmentationHead,
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

        if module_type in {YoloeConv, YoloeC2f, YoloeC3k2, YoloeC2PSA, YoloeSPPF}:
            source_channels = channels[_resolve_single_from_index(from_index)]
            output_channels = _make_divisible(min(float(module_args[0]), float(max_channels)) * width_multiple, 8)
            if module_type is YoloeConv:
                module = module_type(source_channels, output_channels, *module_args[1:])
            elif module_type is YoloeSPPF:
                module = module_type(source_channels, output_channels, *module_args[1:])
            else:
                built_module_args = [source_channels, output_channels, repeat_count, *module_args[1:]]
                if module_type is YoloeC3k2 and _resolve_yaml_scale_key(model_scale) in {"m", "l", "x"}:
                    built_module_args[3] = True
                module = module_type(*built_module_args)
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
            architecture_class_count = int(model_config.get("nc", module_args[0]))
            proposal_filter_channels = (
                int(module_args[3])
                if module_name == "YOLOESegment26" and bool(model_config.get("end2end", False)) and scale_key == "n"
                else 1
            )
            module = module_type(
                nc=int(module_args[0]),
                nm=int(module_args[1]),
                npr=int(npr),
                embed=int(module_args[3]),
                with_bn=bool(module_args[4]),
                ch=detect_channels,
                reg_max=int(model_config.get("reg_max", 16)),
                strides=tuple(int(item) for item in model_config.get("strides", (8, 16, 32))),
                legacy_class_head=_uses_legacy_yoloe_class_head(
                    model_name=model_name,
                    model_config=model_config,
                ),
                class_hidden_source_count=architecture_class_count,
                end2end=bool(model_config.get("end2end", False)),
                proto26=module_name == "YOLOESegment26",
                proposal_filter_channels=proposal_filter_channels,
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
        "C3k2": YoloeC3k2,
        "C2PSA": YoloeC2PSA,
        "SPPF": YoloeSPPF,
        "Concat": YoloeConcat,
        "nn.Upsample": nn.Upsample,
        "YOLOESegment": YoloeTextPromptSegmentationHead,
        "YOLOESegment26": YoloeTextPromptSegmentationHead,
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

        if module_type in {YoloeConv, YoloeC2f, YoloeC3k2, YoloeC2PSA, YoloeSPPF}:
            source_channels = channels[_resolve_single_from_index(from_index)]
            output_channels = _make_divisible(min(float(module_args[0]), float(max_channels)) * width_multiple, 8)
            if module_type is YoloeConv:
                module = module_type(source_channels, output_channels, *module_args[1:])
            elif module_type is YoloeSPPF:
                module = module_type(source_channels, output_channels, *module_args[1:])
            else:
                built_module_args = [source_channels, output_channels, repeat_count, *module_args[1:]]
                if module_type is YoloeC3k2 and _resolve_yaml_scale_key(model_scale) in {"m", "l", "x"}:
                    built_module_args[3] = True
                module = module_type(*built_module_args)
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
            architecture_class_count = int(model_config.get("nc", module_args[0]))
            module = module_type(
                nc=int(module_args[0]),
                nm=int(module_args[1]),
                npr=int(npr),
                embed=int(module_args[3]),
                with_bn=bool(module_args[4]),
                ch=detect_channels,
                reg_max=int(model_config.get("reg_max", 16)),
                strides=tuple(int(item) for item in model_config.get("strides", (8, 16, 32))),
                legacy_class_head=_uses_legacy_yoloe_class_head(
                    model_name=model_name,
                    model_config=model_config,
                ),
                class_hidden_source_count=architecture_class_count,
                proto26=module_name == "YOLOESegment26",
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


def _uses_legacy_yoloe_class_head(*, model_name: str, model_config: dict[str, object]) -> bool:
    """判断 YOLOE checkpoint 对应的分类 head 结构。"""

    model_label = f"{model_name} {model_config.get('yaml_file', '')}".lower()
    return "v8" in model_label or "yolov8" in model_label


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


__all__ = [
    "YoloePromptFreeSegmentationHead",
    "YoloePromptFreeSegmentationModel",
    "YoloeTextPromptSegmentationHead",
    "YoloeTextPromptSegmentationModel",
    "build_yoloe_prompt_free_segmentation_model",
    "build_yoloe_text_prompt_segmentation_model",
]
