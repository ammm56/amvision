"""RF-DETR segmentation 项目内实现。"""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.rfdetr_model import (
    MultiScaleProjector,
    RfdetrDecoder,
    RfdetrDecoderLayer,
    RfdetrDetectionHead,
    RfdetrViTBackbone,
    _RF_SCALE,
    _compute_valid_ratios,
    gen_sineembed,
    load_rfdetr_pretrained,
)


class RfdetrSegmentationDepthwiseBlock(nn.Module):
    """轻量深度卷积块。"""

    def __init__(self, channels: int) -> None:
        super().__init__()
        self.depthwise = nn.Conv2d(
            channels,
            channels,
            kernel_size=3,
            stride=1,
            padding=1,
            groups=channels,
        )
        self.norm = nn.LayerNorm(channels, eps=1e-6)
        self.pointwise = nn.Linear(channels, channels)
        self.activation = nn.GELU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        residual = x
        x = self.depthwise(x)
        x = x.permute(0, 2, 3, 1)
        x = self.norm(x)
        x = self.activation(self.pointwise(x))
        x = x.permute(0, 3, 1, 2)
        return x + residual


class RfdetrSegmentationMlpBlock(nn.Module):
    """query 特征交互块。"""

    def __init__(self, channels: int) -> None:
        super().__init__()
        self.norm = nn.LayerNorm(channels, eps=1e-6)
        self.fc1 = nn.Linear(channels, channels * 4)
        self.fc2 = nn.Linear(channels * 4, channels)
        self.activation = nn.GELU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        residual = x
        x = self.norm(x)
        x = self.activation(self.fc1(x))
        x = self.fc2(x)
        return x + residual


class RfdetrSegmentationHead(nn.Module):
    """RF-DETR segmentation 头。

    参考上游的 spatial/query 交互思路，在本项目内做更直接的实现：
    - 最高分辨率 projector 特征作为 spatial_features
    - 每层 decoder query 生成一次 mask logits
    """

    def __init__(
        self,
        *,
        hidden_dim: int,
        mask_channels: int | None = None,
        num_blocks: int = 4,
        downsample_ratio: int = 4,
    ) -> None:
        super().__init__()
        self.hidden_dim = hidden_dim
        self.mask_channels = mask_channels or hidden_dim
        self.downsample_ratio = downsample_ratio
        self.blocks = nn.ModuleList(
            [RfdetrSegmentationDepthwiseBlock(hidden_dim) for _ in range(num_blocks)]
        )
        self.spatial_projection = nn.Conv2d(hidden_dim, self.mask_channels, kernel_size=1)
        self.query_block = RfdetrSegmentationMlpBlock(hidden_dim)
        self.query_projection = nn.Linear(hidden_dim, self.mask_channels)
        self.bias = nn.Parameter(torch.zeros(1), requires_grad=True)

    def forward(
        self,
        *,
        spatial_features: torch.Tensor,
        query_features: list[torch.Tensor],
        image_size: tuple[int, int],
    ) -> list[torch.Tensor]:
        """按 decoder 层输出生成 mask logits。"""

        target_height = max(1, image_size[0] // self.downsample_ratio)
        target_width = max(1, image_size[1] // self.downsample_ratio)
        spatial_features = F.interpolate(
            spatial_features,
            size=(target_height, target_width),
            mode="bilinear",
            align_corners=False,
        )

        mask_logits: list[torch.Tensor] = []
        current_spatial = spatial_features
        for index, query_feature in enumerate(query_features):
            block = self.blocks[min(index, len(self.blocks) - 1)]
            current_spatial = block(current_spatial)
            spatial_projected = self.spatial_projection(current_spatial)
            query_projected = self.query_projection(self.query_block(query_feature))
            mask_logits.append(
                torch.einsum("bchw,bnc->bnhw", spatial_projected, query_projected)
                + self.bias
            )
        return mask_logits


class RfdetrSegmentationPostProcess(nn.Module):
    """把 RF-DETR segmentation 原始输出整理为平台需要的结果。"""

    def __init__(self, num_select: int = 300) -> None:
        super().__init__()
        self.num_select = num_select

    def forward(
        self,
        outputs: dict[str, torch.Tensor],
        target_sizes: torch.Tensor,
    ) -> dict[str, Any]:
        pred_logits = outputs["pred_logits"]
        pred_boxes = outputs["pred_boxes"]
        pred_masks = outputs["pred_masks"]
        batch_size, query_count, class_count = pred_logits.shape
        probabilities = pred_logits.sigmoid()
        num_select = min(self.num_select, query_count * class_count)
        top_scores, top_indices = torch.topk(
            probabilities.view(batch_size, -1),
            num_select,
            dim=1,
        )
        top_query_indices = top_indices // class_count
        top_labels = top_indices % class_count
        batch_indices = (
            torch.arange(batch_size, device=pred_logits.device)
            .unsqueeze(1)
            .expand(-1, num_select)
        )
        top_boxes = pred_boxes[batch_indices, top_query_indices]
        top_masks = pred_masks[batch_indices, top_query_indices]

        image_heights, image_widths = target_sizes.unbind(1)
        scale_factors = torch.stack(
            [image_widths, image_heights, image_widths, image_heights],
            dim=1,
        ).unsqueeze(1)
        scaled_boxes = top_boxes * scale_factors
        cx, cy, width, height = (
            scaled_boxes[..., 0],
            scaled_boxes[..., 1],
            scaled_boxes[..., 2],
            scaled_boxes[..., 3],
        )
        boxes_xyxy = torch.stack(
            [
                cx - width / 2,
                cy - height / 2,
                cx + width / 2,
                cy + height / 2,
            ],
            dim=-1,
        )

        resized_masks: list[torch.Tensor] = []
        for batch_index in range(batch_size):
            target_height = max(1, int(image_heights[batch_index].item()))
            target_width = max(1, int(image_widths[batch_index].item()))
            resized_masks.append(
                F.interpolate(
                    top_masks[batch_index].unsqueeze(1),
                    size=(target_height, target_width),
                    mode="bilinear",
                    align_corners=False,
                ).squeeze(1)
            )

        return {
            "scores": top_scores,
            "labels": top_labels,
            "boxes_xyxy": boxes_xyxy,
            "masks": torch.stack(resized_masks, dim=0),
        }


class RfdetrSegmentationModel(nn.Module):
    """RF-DETR segmentation 完整模型。"""

    def __init__(
        self,
        *,
        backbone: nn.Module,
        projector: MultiScaleProjector,
        hidden_dim: int = 256,
        num_queries: int = 300,
        num_decoder_layers: int = 3,
        sa_nhead: int = 8,
        ca_nhead: int = 8,
        num_classes: int = 91,
        num_select: int = 300,
        group_detr: int = 1,
    ) -> None:
        super().__init__()
        self.backbone = backbone
        self.projector = projector
        self.hidden_dim = hidden_dim
        self.num_queries = num_queries
        self.group_detr = group_detr
        self.query_embed = nn.Embedding(num_queries * group_detr, hidden_dim * 2)
        self.refpoint_embed = nn.Embedding(num_queries * group_detr, 4)
        decoder_layer = RfdetrDecoderLayer(
            d_model=hidden_dim,
            sa_nhead=sa_nhead,
            ca_nhead=ca_nhead,
            group_detr=group_detr,
            n_levels=len(projector.projections),
        )
        self.decoder = RfdetrDecoder(
            decoder_layer,
            num_decoder_layers,
            nn.LayerNorm(hidden_dim),
            return_intermediate=True,
            d_model=hidden_dim,
            bbox_reparam=True,
        )
        self.detection_head = RfdetrDetectionHead(hidden_dim, num_classes)
        self.segmentation_head = RfdetrSegmentationHead(hidden_dim=hidden_dim)
        self.postprocess = RfdetrSegmentationPostProcess(num_select=num_select)

    def forward(self, images: torch.Tensor) -> dict[str, Any]:
        """执行一次 RF-DETR segmentation 前向。"""

        features, masks = self.backbone(images)
        projected_features = self.projector(features)
        batch_size = images.shape[0]
        flattened_sources: list[torch.Tensor] = []
        flattened_masks: list[torch.Tensor] = []
        position_parts: list[torch.Tensor] = []
        spatial_shapes: list[tuple[int, int]] = []
        for projected_feature, mask in zip(projected_features, masks, strict=True):
            _, _, height, width = projected_feature.shape
            flattened_sources.append(projected_feature.flatten(2).permute(0, 2, 1))
            flattened_masks.append(mask.flatten(1))
            grid_y, grid_x = torch.meshgrid(
                torch.arange(height, dtype=torch.float32, device=projected_feature.device),
                torch.arange(width, dtype=torch.float32, device=projected_feature.device),
                indexing="ij",
            )
            position_parts.append(
                gen_sineembed(
                    torch.stack([grid_x, grid_y], dim=-1)
                    .reshape(1, height * width, 2)
                    .repeat(batch_size, 1, 1),
                    dim=self.hidden_dim // 2,
                )
            )
            spatial_shapes.append((height, width))

        memory = torch.cat(flattened_sources, dim=1)
        position_encoding = torch.cat(position_parts, dim=1)
        spatial_shapes_tensor = torch.tensor(spatial_shapes, device=images.device)
        level_start_index = torch.cat(
            (
                spatial_shapes_tensor.new_zeros((1,)),
                spatial_shapes_tensor.prod(1).cumsum(0)[:-1],
            )
        )
        valid_ratios = _compute_valid_ratios(masks)
        group_count = self.group_detr if self.training else 1
        query_embedding = self.query_embed.weight[: self.num_queries * group_count]
        reference_embedding = self.refpoint_embed.weight[: self.num_queries * group_count]
        query_embedding = query_embedding.unsqueeze(0).repeat(batch_size, 1, 1)
        reference_points = reference_embedding.unsqueeze(0).repeat(batch_size, 1, 1).sigmoid()
        target = query_embedding[:, :, : self.hidden_dim]
        _, intermediate, reference_points_list = self.decoder(
            target,
            memory,
            position_encoding,
            reference_points,
            spatial_shapes_tensor,
            level_start_index,
            valid_ratios,
            self.detection_head.bbox_embed,
        )
        reference_unsigmoid = (
            reference_points_list[-1]
            if len(reference_points_list) >= len(intermediate)
            else reference_points
        )
        pred_logits_list: list[torch.Tensor] = []
        pred_boxes_list: list[torch.Tensor] = []
        for hidden_state in intermediate:
            pred_logits, pred_boxes = self.detection_head(hidden_state, reference_unsigmoid)
            pred_logits_list.append(pred_logits)
            pred_boxes_list.append(pred_boxes)

        pred_masks_list = self.segmentation_head(
            spatial_features=projected_features[0],
            query_features=list(intermediate),
            image_size=(int(images.shape[2]), int(images.shape[3])),
        )
        if len(pred_masks_list) != len(intermediate):
            raise ServiceConfigurationError(
                "RF-DETR segmentation 头输出层数与 decoder 层数不一致",
                details={
                    "mask_layers": len(pred_masks_list),
                    "decoder_layers": len(intermediate),
                },
            )

        aux_outputs: list[dict[str, torch.Tensor]] = []
        for index in range(max(0, len(intermediate) - 1)):
            aux_outputs.append(
                {
                    "pred_logits": pred_logits_list[index],
                    "pred_boxes": pred_boxes_list[index],
                    "pred_masks": pred_masks_list[index],
                }
            )
        return {
            "pred_logits": pred_logits_list[-1],
            "pred_boxes": pred_boxes_list[-1],
            "pred_masks": pred_masks_list[-1],
            "hs": intermediate,
            "aux_outputs": aux_outputs,
        }


def build_rfdetr_segmentation_model(
    *,
    model_scale: str = "nano",
    num_classes: int = 91,
    pretrained_path: str | None = None,
) -> RfdetrSegmentationModel:
    """构建一套 RF-DETR segmentation 模型。"""

    config = _RF_SCALE.get(model_scale)
    if config is None:
        raise ServiceConfigurationError(
            f"RF-DETR segmentation 不支持 model_scale={model_scale}"
        )
    backbone = RfdetrViTBackbone(
        img_size=config["is"],
        patch_size=config["ps"],
        embed_dim=config["ve"],
        depth=config["vd"],
        num_heads=config["vh"],
        out_feature_indexes=[2, 5, 8, 11],
    )
    projector = MultiScaleProjector(
        in_channels=[config["ve"]] * 4,
        out_channels=config["hd"],
        scale_factors=[2.0, 1.0, 0.5, 0.25],
    )
    model = RfdetrSegmentationModel(
        backbone=backbone,
        projector=projector,
        hidden_dim=config["hd"],
        num_queries=config["nq"],
        num_decoder_layers=config["ndl"],
        sa_nhead=config["san"],
        ca_nhead=config["can"],
        num_classes=num_classes,
        group_detr=config["gd"],
    )
    if pretrained_path:
        load_rfdetr_pretrained(model, pretrained_path)
    return model


def mask_logits_to_xyxy(masks: torch.Tensor) -> torch.Tensor:
    """根据 mask logits 估算 bbox。"""

    binary_masks = masks > 0.0
    batch_boxes: list[torch.Tensor] = []
    for per_image_masks in binary_masks:
        if per_image_masks.numel() == 0:
            batch_boxes.append(
                torch.zeros((0, 4), dtype=torch.float32, device=masks.device)
            )
            continue
        per_mask_boxes: list[torch.Tensor] = []
        for mask in per_image_masks:
            coords = torch.nonzero(mask, as_tuple=False)
            if coords.numel() == 0:
                per_mask_boxes.append(
                    torch.zeros((4,), dtype=torch.float32, device=masks.device)
                )
                continue
            y_min = coords[:, 0].min().float()
            x_min = coords[:, 1].min().float()
            y_max = coords[:, 0].max().float()
            x_max = coords[:, 1].max().float()
            per_mask_boxes.append(torch.stack([x_min, y_min, x_max, y_max]))
        batch_boxes.append(torch.stack(per_mask_boxes, dim=0))
    return torch.stack(batch_boxes, dim=0)


def masks_xyxy_to_cxcywh(boxes_xyxy: torch.Tensor, image_size: tuple[int, int]) -> torch.Tensor:
    """把像素坐标 bbox 转成归一化 cxcywh。"""

    image_height, image_width = image_size
    x1, y1, x2, y2 = boxes_xyxy.unbind(-1)
    cx = ((x1 + x2) / 2.0) / max(1.0, float(image_width))
    cy = ((y1 + y2) / 2.0) / max(1.0, float(image_height))
    width = (x2 - x1).clamp(min=0.0) / max(1.0, float(image_width))
    height = (y2 - y1).clamp(min=0.0) / max(1.0, float(image_height))
    return torch.stack([cx, cy, width, height], dim=-1)


__all__ = [
    "RfdetrSegmentationHead",
    "RfdetrSegmentationModel",
    "RfdetrSegmentationPostProcess",
    "build_rfdetr_segmentation_model",
    "mask_logits_to_xyxy",
    "masks_xyxy_to_cxcywh",
]
