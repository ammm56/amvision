"""SAM3 单图 interactive project-native 运行时。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import torch
from torch import nn

from backend.service.application.runtime.detection_runtime_support import (
    enable_pytorch_cuda_inference_fast_path,
    resolve_execution_device_name,
)

from .checkpoint_loader import build_sam3_interactive_state_dict, load_sam3_checkpoint_branches
from .image_preprocess import PreparedSam3Image, preprocess_sam3_image
from .mask_postprocess import (
    DEFAULT_MASK_THRESHOLD,
    DEFAULT_POLYGON_SIMPLIFY_RATIO,
    DEFAULT_STABILITY_OFFSET,
    Sam3RegionItem,
    postprocess_sam3_interactive_masks,
)
from .prompt_encoding import PreparedSam3InteractivePrompts, build_sam3_interactive_prompt_tensors
from .prompt_mask_modules import PromptEncoder, SAM2MaskDecoder, SAM2TwoWayTransformer
from .vision_backbone import PositionEmbeddingSine, SAM3VisualBackbone, Sam3DualViTDetNeck, ViT


@dataclass(frozen=True)
class Sam3InteractivePrediction:
    """描述一次 SAM3 interactive 推理结果。"""

    regions: tuple[Sam3RegionItem, ...]
    summary: dict[str, object]


def _resolve_runtime_torch_dtype(*, device_name: str, precision: str) -> torch.dtype:
    """把节点参数 precision 解析成实际运行 dtype。"""

    normalized_precision = str(precision or "fp32").strip().lower()
    if not device_name.startswith("cuda"):
        return torch.float32
    if normalized_precision == "fp16":
        return torch.float16
    if normalized_precision == "bf16":
        return torch.bfloat16
    return torch.float32


class Sam3InteractiveImageModel(nn.Module):
    """只覆盖单图 interactive 分割所需最小接口的 SAM3 模型。"""

    mask_threshold: float = 0.0

    def __init__(self) -> None:
        super().__init__()
        self.image_size = 1008
        self.backbone_stride = 14
        self.hidden_dim = 256
        self.mem_dim = 64
        self.num_feature_levels = 3
        self.directly_add_no_mem_embed = True
        self.use_high_res_features_in_sam = True

        self.image_encoder = SAM3VisualBackbone(
            vision_backbone=Sam3DualViTDetNeck(
                position_encoding=PositionEmbeddingSine(
                    num_pos_feats=256,
                    normalize=True,
                    scale=None,
                    temperature=10000,
                ),
                d_model=256,
                scale_factors=(4.0, 2.0, 1.0, 0.5),
                trunk=ViT(
                    img_size=1008,
                    pretrain_img_size=336,
                    patch_size=14,
                    embed_dim=1024,
                    depth=32,
                    num_heads=16,
                    mlp_ratio=4.625,
                    norm_layer="LayerNorm",
                    drop_path_rate=0.1,
                    qkv_bias=True,
                    use_abs_pos=True,
                    tile_abs_pos=True,
                    global_att_blocks=(7, 15, 23, 31),
                    use_rope=True,
                    use_interp_rope=True,
                    window_size=24,
                    pretrain_use_cls_token=True,
                    retain_cls_token=False,
                    ln_pre=True,
                    ln_post=False,
                    return_interm_layers=False,
                    bias_patch_embed=False,
                    use_act_checkpoint=False,
                ),
                add_sam2_neck=True,
            ),
            scalp=1,
        )

        self.sam_prompt_embed_dim = self.hidden_dim
        self.sam_image_embedding_size = self.image_size // self.backbone_stride
        self.sam_prompt_encoder = PromptEncoder(
            embed_dim=self.sam_prompt_embed_dim,
            image_embedding_size=(self.sam_image_embedding_size, self.sam_image_embedding_size),
            input_image_size=(self.image_size, self.image_size),
            mask_in_chans=16,
        )
        self.sam_mask_decoder = SAM2MaskDecoder(
            num_multimask_outputs=3,
            transformer=SAM2TwoWayTransformer(
                depth=2,
                embedding_dim=self.sam_prompt_embed_dim,
                mlp_dim=2048,
                num_heads=8,
            ),
            transformer_dim=self.sam_prompt_embed_dim,
            iou_head_depth=3,
            iou_head_hidden_dim=256,
            use_high_res_features=True,
            iou_prediction_use_sigmoid=True,
            pred_obj_scores=True,
            pred_obj_scores_mlp=True,
            use_multimask_token_for_obj_ptr=True,
            dynamic_multimask_via_stability=True,
            dynamic_multimask_stability_delta=0.05,
            dynamic_multimask_stability_thresh=0.98,
        )

        self.no_mem_embed = nn.Parameter(torch.zeros(1, 1, self.hidden_dim))
        self.no_mem_pos_enc = nn.Parameter(torch.zeros(1, 1, self.hidden_dim))
        self.maskmem_tpos_enc = nn.Parameter(torch.zeros(7, 1, 1, self.mem_dim))
        self.no_obj_ptr = nn.Parameter(torch.zeros(1, self.hidden_dim))
        self.no_obj_embed_spatial = nn.Parameter(torch.zeros(1, self.mem_dim))

    def forward_image(self, image_tensor: torch.Tensor) -> dict[str, object]:
        """抽取单图视觉特征。"""

        backbone_out = self.image_encoder.forward_image(image_tensor)
        backbone_out["backbone_fpn"][0] = self.sam_mask_decoder.conv_s0(backbone_out["backbone_fpn"][0])
        backbone_out["backbone_fpn"][1] = self.sam_mask_decoder.conv_s1(backbone_out["backbone_fpn"][1])
        return backbone_out

    def _prepare_backbone_features(
        self,
        backbone_out: dict[str, object],
        *,
        batch: int = 1,
    ) -> tuple[dict[str, object], list[torch.Tensor], list[torch.Tensor], list[tuple[int, int]]]:
        """按 SAM2 predictor 的约定整理视觉特征。"""

        if batch > 1:
            backbone_out = {
                **backbone_out,
                "backbone_fpn": [feat.expand(batch, -1, -1, -1) for feat in backbone_out["backbone_fpn"]],
                "vision_pos_enc": [pos.expand(batch, -1, -1, -1) for pos in backbone_out["vision_pos_enc"]],
            }
        feature_maps = backbone_out["backbone_fpn"][-self.num_feature_levels :]
        vision_pos_embeds = backbone_out["vision_pos_enc"][-self.num_feature_levels :]
        feat_sizes = [(tensor.shape[-2], tensor.shape[-1]) for tensor in vision_pos_embeds]
        vision_feats = [tensor.flatten(2).permute(2, 0, 1) for tensor in feature_maps]
        vision_pos_embeds = [tensor.flatten(2).permute(2, 0, 1) for tensor in vision_pos_embeds]
        return backbone_out, vision_feats, vision_pos_embeds, feat_sizes

    def extract_interactive_features(self, prepared_image: PreparedSam3Image) -> dict[str, object]:
        """把输入图片转换成 interactive prompt 推理需要的特征。"""

        backbone_out = self.forward_image(prepared_image.image_tensor)
        _, vision_feats, _vision_pos_embeds, feat_sizes = self._prepare_backbone_features(backbone_out)
        if self.directly_add_no_mem_embed:
            vision_feats[-1] = vision_feats[-1] + self.no_mem_embed.to(vision_feats[-1].dtype)
        feature_maps = [
            feat.permute(1, 2, 0).view(1, -1, *feat_size)
            for feat, feat_size in zip(vision_feats, feat_sizes)
        ]
        return {
            "image_embed": feature_maps[-1],
            "high_res_feats": feature_maps[:-1],
        }

    def predict_mask_logits(
        self,
        *,
        features: dict[str, object],
        prompts: PreparedSam3InteractivePrompts,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """运行 prompt encoder + mask decoder，输出低分辨率 mask logits 与得分。"""

        point_inputs = None
        if prompts.point_coords is not None and prompts.point_labels is not None:
            point_inputs = (prompts.point_coords, prompts.point_labels)
        sparse_embeddings, dense_embeddings = self.sam_prompt_encoder(
            points=point_inputs,
            boxes=None,
            masks=prompts.prompt_masks,
        )
        image_embed = features["image_embed"]
        high_res_feats = features["high_res_feats"]
        batch_size = (
            prompts.point_coords.shape[0]
            if prompts.point_coords is not None
            else prompts.prompt_masks.shape[0]
            if prompts.prompt_masks is not None
            else 1
        )
        batched_mode = batch_size > 1
        mask_logits, iou_scores, sam_tokens_out, object_score_logits = self.sam_mask_decoder(
            image_embeddings=image_embed,
            image_pe=self.sam_prompt_encoder.get_dense_pe(),
            sparse_prompt_embeddings=sparse_embeddings,
            dense_prompt_embeddings=dense_embeddings,
            multimask_output=False,
            repeat_image=batched_mode,
            high_res_features=high_res_feats,
        )
        del sam_tokens_out
        final_scores = iou_scores.squeeze(1)
        if object_score_logits.ndim == 2:
            final_scores = final_scores * object_score_logits.sigmoid().squeeze(1)
        return mask_logits, iou_scores, final_scores

    def set_imgsz(self, imgsz: list[int] = [1008, 1008]) -> None:
        """更新输入尺寸。"""

        self.image_encoder.set_imgsz(imgsz)


def build_sam3_interactive_image_model(
    *,
    checkpoint_path: Path,
    requested_device_name: str,
    precision: str,
) -> tuple[Sam3InteractiveImageModel, str, torch.dtype]:
    """构建并加载 project-native SAM3 interactive 单图模型。"""

    resolved_device_name = resolve_execution_device_name(
        torch_module=torch,
        requested_device_name=requested_device_name,
    )
    enable_pytorch_cuda_inference_fast_path(torch_module=torch, device_name=resolved_device_name)
    runtime_torch_dtype = _resolve_runtime_torch_dtype(device_name=resolved_device_name, precision=precision)

    model = Sam3InteractiveImageModel()
    interactive_state_dict = build_sam3_interactive_state_dict(load_sam3_checkpoint_branches(checkpoint_path))
    model.load_state_dict(interactive_state_dict, strict=False)
    model.eval()
    model.to(device=torch.device(resolved_device_name), dtype=runtime_torch_dtype)
    return model, resolved_device_name, runtime_torch_dtype


class Sam3InteractiveRuntimeSession:
    """封装单图 interactive 推理的可复用会话。"""

    def __init__(
        self,
        *,
        checkpoint_path: Path,
        model_scale: str,
        variant_name: str,
        requested_device_name: str,
        precision: str,
    ) -> None:
        self.model_scale = model_scale
        self.variant_name = variant_name
        self.checkpoint_path = checkpoint_path
        self.precision = precision
        self.model, self.device_name, self.runtime_torch_dtype = build_sam3_interactive_image_model(
            checkpoint_path=checkpoint_path,
            requested_device_name=requested_device_name,
            precision=precision,
        )

    @torch.inference_mode()
    def predict(
        self,
        *,
        image_bytes: bytes,
        prompt_items: tuple[object, ...],
    ) -> Sam3InteractivePrediction:
        prepared_image = preprocess_sam3_image(
            image_bytes,
            precision="fp16" if self.runtime_torch_dtype == torch.float16 else "bf16" if self.runtime_torch_dtype == torch.bfloat16 else "fp32",
        )
        prepared_image = PreparedSam3Image(
            image_tensor=prepared_image.image_tensor.to(device=self.model.no_mem_embed.device, dtype=self.runtime_torch_dtype),
            original_width=prepared_image.original_width,
            original_height=prepared_image.original_height,
            target_width=prepared_image.target_width,
            target_height=prepared_image.target_height,
            scale_x=prepared_image.scale_x,
            scale_y=prepared_image.scale_y,
        )
        features = self.model.extract_interactive_features(prepared_image)
        mask_prompt_height, mask_prompt_width = self.model.sam_prompt_encoder.mask_input_size
        mask_logits_list: list[torch.Tensor] = []
        final_scores_list: list[torch.Tensor] = []
        for prompt_item in prompt_items:
            prompts = build_sam3_interactive_prompt_tensors(
                (prompt_item,),
                source_width=prepared_image.original_width,
                source_height=prepared_image.original_height,
                target_width=prepared_image.target_width,
                target_height=prepared_image.target_height,
                mask_prompt_width=mask_prompt_width,
                mask_prompt_height=mask_prompt_height,
                device=self.model.no_mem_embed.device,
            )
            item_mask_logits, _item_iou_scores, item_final_scores = self.model.predict_mask_logits(
                features=features,
                prompts=prompts,
            )
            mask_logits_list.append(item_mask_logits)
            final_scores_list.append(item_final_scores.reshape(-1))
        mask_logits = torch.cat(mask_logits_list, dim=0)
        final_scores = torch.cat(final_scores_list, dim=0)
        region_items = postprocess_sam3_interactive_masks(
            mask_logits,
            source_width=prepared_image.original_width,
            source_height=prepared_image.original_height,
            prompt_items=prompt_items,
            scores=final_scores,
        )
        prompt_kinds = sorted({str(item.prompt_kind) for item in prompt_items})
        summary = {
            "project_native": True,
            "model_scale": self.model_scale,
            "variant_name": self.variant_name,
            "checkpoint_path": str(self.checkpoint_path),
            "device": self.device_name,
            "precision": "fp16" if self.runtime_torch_dtype == torch.float16 else "bf16" if self.runtime_torch_dtype == torch.bfloat16 else "fp32",
            "prompt_count": len(prompt_items),
            "prompt_kinds": prompt_kinds,
            "region_count": len(region_items),
            "inference_mode": "interactive-segment",
            "postprocess_profile": "sam3-default-v2",
            "mask_threshold": DEFAULT_MASK_THRESHOLD,
            "stability_offset": DEFAULT_STABILITY_OFFSET,
            "polygon_simplify_ratio": DEFAULT_POLYGON_SIMPLIFY_RATIO,
        }
        return Sam3InteractivePrediction(regions=tuple(region_items), summary=summary)


__all__ = [
    "Sam3InteractiveImageModel",
    "Sam3InteractivePrediction",
    "Sam3InteractiveRuntimeSession",
    "build_sam3_interactive_image_model",
]
