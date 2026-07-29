"""SAM3 单图 semantic-segment project-native 运行时。"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import torch
from torch import nn
import torch.nn.functional as F

from backend.nodes.text_encoder_runtime_support import load_clip_simple_tokenizer
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.support.detection import (
    enable_pytorch_cuda_inference_fast_path,
    resolve_execution_device_name,
)

from ..checkpoint.loader import (
    Sam3CheckpointBranches,
    build_sam3_semantic_state_dict,
    load_sam3_checkpoint_branches,
)
from ..postprocess.masks import (
    DEFAULT_MASK_THRESHOLD,
    DEFAULT_POLYGON_SIMPLIFY_RATIO,
    DEFAULT_STABILITY_OFFSET,
    Sam3RegionItem,
    postprocess_sam3_interactive_masks,
)
from ..preprocess.image import PreparedSam3Image, preprocess_sam3_image
from ..nn.vision_backbone import (
    PositionEmbeddingSine,
    SAM3VisualBackbone,
    Sam3DualViTDetNeck,
    ViT,
)


@dataclass(frozen=True)
class Sam3SemanticPrediction:
    """描述一次 SAM3 semantic 推理结果。"""

    regions: tuple[Sam3RegionItem, ...]
    summary: dict[str, object]


class Sam3TextResidualAttentionBlock(nn.Module):
    """SAM3 语言骨干使用的残差注意力块。"""

    def __init__(self, *, d_model: int, n_head: int, mlp_ratio: float = 4.0) -> None:
        super().__init__()
        self.attn = nn.MultiheadAttention(d_model, n_head, batch_first=True)
        self.ln_1 = nn.LayerNorm(d_model)
        self.ln_2 = nn.LayerNorm(d_model)
        mlp_width = int(d_model * mlp_ratio)
        self.mlp = nn.Sequential(
            OrderedDict(
                (
                    ("c_fc", nn.Linear(d_model, mlp_width)),
                    ("gelu", nn.GELU()),
                    ("c_proj", nn.Linear(mlp_width, d_model)),
                )
            )
        )

    def forward(
        self, hidden_states: torch.Tensor, attn_mask: torch.Tensor | None = None
    ) -> torch.Tensor:
        """执行一层文本 transformer block。"""

        normalized_hidden_states = self.ln_1(hidden_states)
        attended_hidden_states = self.attn(
            normalized_hidden_states,
            normalized_hidden_states,
            normalized_hidden_states,
            attn_mask=attn_mask,
            need_weights=False,
        )[0]
        hidden_states = hidden_states + attended_hidden_states
        hidden_states = hidden_states + self.mlp(self.ln_2(hidden_states))
        return hidden_states


class Sam3TextTransformer(nn.Module):
    """SAM3 checkpoint 内置语言骨干。"""

    def __init__(
        self,
        *,
        context_length: int = 32,
        vocab_size: int = 49408,
        width: int = 1024,
        heads: int = 16,
        layers: int = 24,
    ) -> None:
        super().__init__()
        self.context_length = context_length
        self.token_embedding = nn.Embedding(vocab_size, width)
        self.positional_embedding = nn.Parameter(torch.empty(context_length, width))
        self.transformer = nn.Module()
        self.transformer.resblocks = nn.ModuleList(
            [
                Sam3TextResidualAttentionBlock(
                    d_model=width,
                    n_head=heads,
                )
                for _ in range(layers)
            ]
        )
        self.ln_final = nn.LayerNorm(width)
        self.text_projection = nn.Parameter(torch.empty(width, 512))
        self.register_buffer(
            "_causal_mask", self._build_causal_mask(), persistent=False
        )

    def _build_causal_mask(self) -> torch.Tensor:
        """构造因果 mask。"""

        mask = torch.empty(self.context_length, self.context_length)
        mask.fill_(float("-inf"))
        mask.triu_(1)
        return mask

    def forward(self, token_tensor: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """返回 pooled text 与 token-level memory。"""

        sequence_length = token_tensor.shape[1]
        hidden_states = self.token_embedding(token_tensor)
        hidden_states = hidden_states + self.positional_embedding[:sequence_length]
        attn_mask = self._causal_mask[:sequence_length, :sequence_length]
        for block in self.transformer.resblocks:
            hidden_states = block(hidden_states, attn_mask=attn_mask)
        hidden_states = self.ln_final(hidden_states)
        pooled_hidden_states = hidden_states[
            torch.arange(hidden_states.shape[0], device=hidden_states.device),
            token_tensor.argmax(dim=-1),
        ]
        pooled_hidden_states = pooled_hidden_states @ self.text_projection
        return pooled_hidden_states, hidden_states


class Sam3SemanticTextEncoder(nn.Module):
    """SAM3 semantic 分割使用的本地文本编码器。"""

    def __init__(self, *, d_model: int = 256) -> None:
        super().__init__()
        self.context_length = 32
        self.tokenizer = load_clip_simple_tokenizer()
        self.encoder = Sam3TextTransformer(
            context_length=self.context_length,
            width=1024,
            heads=16,
            layers=24,
        )
        self.resizer = nn.Linear(1024, d_model)

    def forward(self, texts: list[str]) -> tuple[torch.Tensor, torch.Tensor]:
        """编码文本并返回 attention mask 与 resized memory。"""

        tokenized = self.tokenizer(texts, context_length=self.context_length).to(
            self.resizer.weight.device
        )
        text_attention_mask = tokenized == 0
        _pooled_hidden_states, token_level_hidden_states = self.encoder(tokenized)
        token_level_hidden_states = (
            self.resizer(token_level_hidden_states).transpose(0, 1).contiguous()
        )
        return text_attention_mask, token_level_hidden_states


class Sam3SemanticEncoderLayer(nn.Module):
    """SAM3 detector encoder 的最小 project-native 实现。"""

    def __init__(
        self, *, d_model: int = 256, dim_feedforward: int = 2048, dropout: float = 0.1
    ) -> None:
        super().__init__()
        self.self_attn = nn.MultiheadAttention(
            d_model, 8, dropout=dropout, batch_first=True
        )
        self.cross_attn_image = nn.MultiheadAttention(
            d_model, 8, dropout=dropout, batch_first=True
        )
        self.linear1 = nn.Linear(d_model, dim_feedforward)
        self.linear2 = nn.Linear(dim_feedforward, d_model)
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.norm3 = nn.LayerNorm(d_model)
        self.dropout = nn.Dropout(dropout)
        self.dropout1 = nn.Dropout(dropout)
        self.dropout2 = nn.Dropout(dropout)
        self.dropout3 = nn.Dropout(dropout)
        self.activation = nn.ReLU()

    def forward(
        self,
        *,
        image_tokens: torch.Tensor,
        prompt_tokens: torch.Tensor,
        image_pos: torch.Tensor,
        prompt_padding_mask: torch.Tensor | None,
    ) -> torch.Tensor:
        """执行一层 image-text fusion。"""

        normalized_image_tokens = self.norm1(image_tokens)
        attended_image_tokens = self.self_attn(
            normalized_image_tokens + image_pos,
            normalized_image_tokens + image_pos,
            normalized_image_tokens,
            need_weights=False,
        )[0]
        image_tokens = image_tokens + self.dropout1(attended_image_tokens)

        normalized_cross_tokens = self.norm2(image_tokens)
        cross_attended_image_tokens = self.cross_attn_image(
            normalized_cross_tokens,
            prompt_tokens,
            prompt_tokens,
            key_padding_mask=prompt_padding_mask,
            need_weights=False,
        )[0]
        image_tokens = image_tokens + self.dropout2(cross_attended_image_tokens)

        normalized_feedforward_tokens = self.norm3(image_tokens)
        feedforward_tokens = self.linear2(
            self.dropout(self.activation(self.linear1(normalized_feedforward_tokens)))
        )
        image_tokens = image_tokens + self.dropout3(feedforward_tokens)
        return image_tokens


class Sam3SemanticEncoderFusion(nn.Module):
    """把文本提示融合进图像 token 的最小编码器。"""

    def __init__(self, *, d_model: int = 256, num_layers: int = 6) -> None:
        super().__init__()
        self.layers = nn.ModuleList(
            [Sam3SemanticEncoderLayer(d_model=d_model) for _ in range(num_layers)]
        )

    def forward(
        self,
        *,
        image_feature_maps: list[torch.Tensor],
        image_pos_embeds: list[torch.Tensor],
        prompt_tokens: torch.Tensor,
        prompt_padding_mask: torch.Tensor,
    ) -> torch.Tensor:
        """输出 prompt-conditioned image memory。"""

        feature_map = image_feature_maps[-1]
        pos_embed = image_pos_embeds[-1]
        batch_size, channel_count, height, width = feature_map.shape

        image_tokens = feature_map.flatten(2).transpose(1, 2).contiguous()
        image_pos = pos_embed.flatten(2).transpose(1, 2).contiguous()
        prompt_tokens_batch_first = prompt_tokens.transpose(0, 1).contiguous()
        for layer in self.layers:
            image_tokens = layer(
                image_tokens=image_tokens,
                prompt_tokens=prompt_tokens_batch_first,
                image_pos=image_pos,
                prompt_padding_mask=prompt_padding_mask,
            )
        assert image_tokens.shape == (batch_size, height * width, channel_count)
        return image_tokens.transpose(0, 1).contiguous()


class Sam3SemanticPixelDecoder(nn.Module):
    """SAM3 segmentation head 使用的 pixel decoder。"""

    def __init__(
        self, *, hidden_dim: int = 256, num_upsampling_stages: int = 3
    ) -> None:
        super().__init__()
        self.hidden_dim = hidden_dim
        conv_layers: list[nn.Module] = []
        norms: list[nn.Module] = []
        for _ in range(num_upsampling_stages):
            conv_layers.append(nn.Conv2d(hidden_dim, hidden_dim, 3, 1, 1))
            norms.append(nn.GroupNorm(8, hidden_dim))
        self.conv_layers = nn.ModuleList(conv_layers)
        self.norms = nn.ModuleList(norms)
        self.out_dim = hidden_dim

    def forward(self, backbone_feats: list[torch.Tensor]) -> torch.Tensor:
        """从多尺度 backbone feature 逐级上采样。"""

        previous_feature = backbone_feats[-1]
        for layer_index, current_feature in enumerate(backbone_feats[:-1][::-1]):
            previous_feature = current_feature + F.interpolate(
                previous_feature,
                size=current_feature.shape[-2:],
                mode="nearest",
            )
            previous_feature = self.conv_layers[layer_index](previous_feature)
            previous_feature = F.relu(self.norms[layer_index](previous_feature))
        return previous_feature


class Sam3SemanticSegmentationHead(nn.Module):
    """SAM3 semantic segmentation head 的最小实现。"""

    def __init__(self, *, hidden_dim: int = 256) -> None:
        super().__init__()
        self.pixel_decoder = Sam3SemanticPixelDecoder(
            hidden_dim=hidden_dim, num_upsampling_stages=3
        )
        self.cross_attend_prompt = nn.MultiheadAttention(
            embed_dim=hidden_dim, num_heads=8, dropout=0.0
        )
        self.cross_attn_norm = nn.LayerNorm(hidden_dim)
        self.semantic_seg_head = nn.Conv2d(self.pixel_decoder.out_dim, 1, kernel_size=1)

    def forward(
        self,
        *,
        backbone_feats: list[torch.Tensor],
        encoder_hidden_states: torch.Tensor,
        prompt_tokens: torch.Tensor,
        prompt_padding_mask: torch.Tensor,
    ) -> torch.Tensor:
        """输出每条文本提示对应的一张 semantic mask logits。"""

        normalized_encoder_hidden_states = self.cross_attn_norm(encoder_hidden_states)
        attended_encoder_hidden_states = self.cross_attend_prompt(
            query=normalized_encoder_hidden_states,
            key=prompt_tokens.to(normalized_encoder_hidden_states.dtype),
            value=prompt_tokens.to(normalized_encoder_hidden_states.dtype),
            key_padding_mask=prompt_padding_mask,
            need_weights=False,
        )[0]
        encoder_hidden_states = attended_encoder_hidden_states + encoder_hidden_states

        conditioned_backbone_feats = [feature.clone() for feature in backbone_feats]
        spatial_height, spatial_width = conditioned_backbone_feats[-1].shape[-2:]
        encoder_visual_embed = encoder_hidden_states.permute(1, 2, 0).reshape(
            -1,
            conditioned_backbone_feats[-1].shape[1],
            spatial_height,
            spatial_width,
        )
        conditioned_backbone_feats[-1] = encoder_visual_embed
        pixel_embed = self.pixel_decoder(conditioned_backbone_feats)
        return self.semantic_seg_head(pixel_embed)


class Sam3SemanticImageModel(nn.Module):
    """只覆盖单图 semantic 分割所需最小接口的 SAM3 模型。"""

    def __init__(self) -> None:
        super().__init__()
        self.image_size = 1008
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
        self.language_backbone = Sam3SemanticTextEncoder(d_model=256)
        self.encoder = Sam3SemanticEncoderFusion(d_model=256, num_layers=6)
        self.segmentation_head = Sam3SemanticSegmentationHead(hidden_dim=256)

    def forward_image(self, image_tensor: torch.Tensor) -> dict[str, object]:
        """抽取 SAM3 semantic 需要的视觉特征。"""

        return self.image_encoder.forward_image(image_tensor)

    def encode_text(self, texts: list[str]) -> tuple[torch.Tensor, torch.Tensor]:
        """编码文本提示。"""

        return self.language_backbone(texts)

    def predict_semantic_logits(
        self,
        *,
        backbone_out: dict[str, object],
        prompt_tokens: torch.Tensor,
        prompt_padding_mask: torch.Tensor,
    ) -> torch.Tensor:
        """输出 prompt-conditioned semantic mask logits。"""

        prompt_count = int(prompt_tokens.shape[1])
        backbone_feats = [
            feature.expand(prompt_count, -1, -1, -1).contiguous()
            for feature in backbone_out["backbone_fpn"]
        ]
        image_pos_embeds = [
            position.expand(prompt_count, -1, -1, -1).contiguous()
            for position in backbone_out["vision_pos_enc"]
        ]
        encoder_hidden_states = self.encoder(
            image_feature_maps=backbone_feats,
            image_pos_embeds=image_pos_embeds,
            prompt_tokens=prompt_tokens,
            prompt_padding_mask=prompt_padding_mask,
        )
        return self.segmentation_head(
            backbone_feats=backbone_feats,
            encoder_hidden_states=encoder_hidden_states,
            prompt_tokens=prompt_tokens,
            prompt_padding_mask=prompt_padding_mask,
        )

    def set_imgsz(self, imgsz: list[int] = [1008, 1008]) -> None:
        """更新输入尺寸。"""

        self.image_encoder.set_imgsz(imgsz)


def _resolve_runtime_torch_dtype(*, device_name: str, precision: str) -> torch.dtype:
    """把节点参数 precision 解析成实际运行 dtype。"""

    normalized_precision = str(precision or "auto").strip().lower()
    if not device_name.startswith("cuda"):
        if normalized_precision not in {"auto", "fp32"}:
            raise InvalidRequestError(
                "SAM3 CPU runtime 只支持 fp32",
                details={"device": device_name, "precision": normalized_precision},
            )
        return torch.float32
    if normalized_precision == "auto":
        return torch.float16
    if normalized_precision == "fp16":
        return torch.float16
    if normalized_precision == "bf16":
        is_bf16_supported = getattr(torch.cuda, "is_bf16_supported", None)
        if not callable(is_bf16_supported) or not bool(is_bf16_supported()):
            raise InvalidRequestError(
                "当前 CUDA device 不支持 bf16",
                details={"device": device_name, "precision": normalized_precision},
            )
        return torch.bfloat16
    return torch.float32


def _resolve_requested_device_name(requested_device_name: str) -> str:
    """把 auto 解析成当前 PyTorch runtime 的最佳可用设备。"""

    if requested_device_name == "auto":
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    return requested_device_name


def _load_compatible_state_dict(
    model: nn.Module,
    source_state_dict: dict[str, torch.Tensor],
    *,
    checkpoint_path: Path,
) -> dict[str, object]:
    """只加载名称和 shape 完全匹配的参数，并拒绝未初始化模型参数。"""

    model_state_dict = model.state_dict()
    shape_mismatches = {
        key: {
            "expected": list(model_state_dict[key].shape),
            "actual": list(value.shape),
        }
        for key, value in source_state_dict.items()
        if key in model_state_dict
        and tuple(model_state_dict[key].shape) != tuple(value.shape)
    }
    if shape_mismatches:
        raise InvalidRequestError(
            "SAM3 checkpoint 与 semantic architecture 的 tensor shape 不兼容",
            details={
                "checkpoint_path": str(checkpoint_path),
                "shape_mismatches": shape_mismatches,
            },
        )
    compatible_state_dict = {
        key: value
        for key, value in source_state_dict.items()
        if key in model_state_dict
        and tuple(model_state_dict[key].shape) == tuple(value.shape)
    }
    incompatible_keys = model.load_state_dict(compatible_state_dict, strict=False)
    missing_parameter_keys = sorted(
        key
        for key in incompatible_keys.missing_keys
        if key in dict(model.named_parameters())
    )
    if missing_parameter_keys:
        raise InvalidRequestError(
            "SAM3 checkpoint 缺少 semantic architecture 必需参数",
            details={
                "checkpoint_path": str(checkpoint_path),
                "missing_parameter_keys": missing_parameter_keys,
            },
        )
    return {
        "loaded_key_count": len(compatible_state_dict),
        "source_key_count": len(source_state_dict),
        "ignored_source_key_count": len(source_state_dict) - len(compatible_state_dict),
    }


def build_sam3_semantic_image_model(
    *,
    checkpoint_path: Path,
    requested_device_name: str,
    precision: str,
    checkpoint_branches: Sam3CheckpointBranches | None = None,
) -> tuple[Sam3SemanticImageModel, str, torch.dtype]:
    """构建并加载 project-native SAM3 semantic 单图模型。"""

    resolved_device_name = resolve_execution_device_name(
        torch_module=torch,
        requested_device_name=_resolve_requested_device_name(requested_device_name),
    )
    enable_pytorch_cuda_inference_fast_path(
        torch_module=torch, device_name=resolved_device_name
    )
    runtime_torch_dtype = _resolve_runtime_torch_dtype(
        device_name=resolved_device_name, precision=precision
    )

    model = Sam3SemanticImageModel()
    semantic_state_dict = build_sam3_semantic_state_dict(
        checkpoint_branches or load_sam3_checkpoint_branches(checkpoint_path)
    )
    compatibility_summary = _load_compatible_state_dict(
        model,
        semantic_state_dict,
        checkpoint_path=checkpoint_path,
    )
    model.checkpoint_compatibility_summary = compatibility_summary
    model.eval()
    model.to(device=torch.device(resolved_device_name), dtype=runtime_torch_dtype)
    return model, resolved_device_name, runtime_torch_dtype


class Sam3SemanticRuntimeSession:
    """封装单图 semantic 推理的可复用会话。"""

    NEGATIVE_PROMPT_WEIGHT = 0.5

    def __init__(
        self,
        *,
        checkpoint_path: Path,
        model_asset_id: str,
        architecture_id: str,
        requested_device_name: str,
        precision: str,
        checkpoint_branches: Sam3CheckpointBranches | None = None,
        checkpoint_sha256: str | None = None,
    ) -> None:
        self.model_asset_id = model_asset_id
        self.architecture_id = architecture_id
        self.checkpoint_path = checkpoint_path
        self.precision = precision
        self.checkpoint_sha256 = str(checkpoint_sha256 or "").strip()
        self.session_generation = uuid4().hex
        self.model, self.device_name, self.runtime_torch_dtype = (
            build_sam3_semantic_image_model(
                checkpoint_path=checkpoint_path,
                requested_device_name=requested_device_name,
                precision=precision,
                checkpoint_branches=checkpoint_branches,
            )
        )
        self._feature_cache_key: str | None = None
        self._feature_cache_value: tuple[PreparedSam3Image, object] | None = None
        self._feature_cache_hits = 0
        self._feature_cache_misses = 0

    @torch.inference_mode()
    def predict(
        self,
        *,
        image_bytes: bytes,
        image_payload: object,
        prompt_items: tuple[object, ...],
        mask_threshold: float = DEFAULT_MASK_THRESHOLD,
        stability_offset: float = DEFAULT_STABILITY_OFFSET,
        min_component_area: int | None = None,
        polygon_simplify_ratio: float = DEFAULT_POLYGON_SIMPLIFY_RATIO,
    ) -> Sam3SemanticPrediction:
        """执行单图 semantic 推理。"""

        image_sha256 = sha256(image_bytes).hexdigest()
        feature_cache_key = "|".join(
            (
                self.model_asset_id,
                self.architecture_id,
                self.session_generation,
                self.checkpoint_sha256,
                self.device_name,
                str(self.runtime_torch_dtype),
                "1008x1008",
                image_sha256,
            )
        )
        feature_cache_hit = (
            self._feature_cache_key == feature_cache_key
            and self._feature_cache_value is not None
        )
        if feature_cache_hit:
            self._feature_cache_hits += 1
            assert self._feature_cache_value is not None
            prepared_image, backbone_out = self._feature_cache_value
            preprocess_ms = 0.0
            backbone_ms = 0.0
        else:
            preprocess_started_at = perf_counter()
            prepared_image = preprocess_sam3_image(
                image_bytes,
                image_payload=image_payload,
                precision="fp16"
                if self.runtime_torch_dtype == torch.float16
                else "bf16"
                if self.runtime_torch_dtype == torch.bfloat16
                else "fp32",
            )
            prepared_image = PreparedSam3Image(
                image_tensor=prepared_image.image_tensor.to(
                    device=self.model.segmentation_head.semantic_seg_head.weight.device,
                    dtype=self.runtime_torch_dtype,
                ),
                original_width=prepared_image.original_width,
                original_height=prepared_image.original_height,
                target_width=prepared_image.target_width,
                target_height=prepared_image.target_height,
                scale_x=prepared_image.scale_x,
                scale_y=prepared_image.scale_y,
            )
            preprocess_ms = round(
                (perf_counter() - preprocess_started_at) * 1000,
                3,
            )
            backbone_started_at = perf_counter()
            backbone_out = self.model.forward_image(prepared_image.image_tensor)
            backbone_ms = round(
                (perf_counter() - backbone_started_at) * 1000,
                3,
            )
            self._feature_cache_key = feature_cache_key
            self._feature_cache_value = (prepared_image, backbone_out)
            self._feature_cache_misses += 1
        prompt_prepare_started_at = perf_counter()
        prompt_groups = tuple(prompt_items)
        prompt_texts: list[str] = []
        prompt_text_offsets: list[tuple[int, int, int]] = []
        prompt_display_names: list[str] = []
        source_prompt_texts: list[str] = []
        positive_text_map: list[tuple[str, ...]] = []
        negative_text_map: list[tuple[str, ...]] = []
        prompt_group_languages: list[tuple[str, ...]] = []
        for group in prompt_groups:
            positive_texts = tuple(
                str(item) for item in getattr(group, "positive_texts", ())
            )
            negative_texts = tuple(
                str(item) for item in getattr(group, "negative_texts", ())
            )
            if not positive_texts:
                raise InvalidRequestError(
                    "SAM3 semantic-segment 至少需要一条 positive 文本提示"
                )
            positive_start = len(prompt_texts)
            prompt_texts.extend(positive_texts)
            prompt_texts.extend(negative_texts)
            prompt_text_offsets.append(
                (positive_start, len(positive_texts), len(negative_texts))
            )
            prompt_display_names.append(
                str(
                    getattr(group, "display_name", "")
                    or getattr(group, "prompt_id", "")
                )
            )
            source_prompt_texts.append(
                _build_group_source_prompt_text(positive_texts, negative_texts)
            )
            positive_text_map.append(positive_texts)
            negative_text_map.append(negative_texts)
            prompt_group_languages.append(
                tuple(
                    str(item) for item in getattr(group, "languages", ()) if str(item)
                )
            )
        prompt_prepare_ms = round(
            (perf_counter() - prompt_prepare_started_at) * 1000,
            3,
        )
        text_encoder_started_at = perf_counter()
        prompt_padding_mask, prompt_tokens = self.model.encode_text(prompt_texts)
        text_encoder_ms = round(
            (perf_counter() - text_encoder_started_at) * 1000,
            3,
        )
        prompt_padding_mask = prompt_padding_mask.to(
            self.model.segmentation_head.semantic_seg_head.weight.device
        )
        prompt_tokens = prompt_tokens.to(
            device=self.model.segmentation_head.semantic_seg_head.weight.device,
            dtype=self.runtime_torch_dtype,
        )
        prompt_padding_mask, prompt_tokens = _build_grouped_prompt_tokens(
            prompt_padding_mask=prompt_padding_mask,
            prompt_tokens=prompt_tokens,
            prompt_text_offsets=tuple(prompt_text_offsets),
            negative_prompt_weight=self.NEGATIVE_PROMPT_WEIGHT,
        )
        decoder_started_at = perf_counter()
        semantic_logits = self.model.predict_semantic_logits(
            backbone_out=backbone_out,
            prompt_tokens=prompt_tokens,
            prompt_padding_mask=prompt_padding_mask,
        )
        decoder_ms = round(
            (perf_counter() - decoder_started_at) * 1000,
            3,
        )
        postprocess_started_at = perf_counter()
        region_items = postprocess_sam3_interactive_masks(
            semantic_logits,
            source_width=prepared_image.original_width,
            source_height=prepared_image.original_height,
            prompt_items=prompt_items,
            threshold=mask_threshold,
            stability_offset=stability_offset,
            min_component_area=min_component_area,
            polygon_simplify_ratio=polygon_simplify_ratio,
        )
        postprocess_ms = round(
            (perf_counter() - postprocess_started_at) * 1000, 3
        )
        summary = {
            "project_native": True,
            "model_asset_id": self.model_asset_id,
            "architecture_id": self.architecture_id,
            "device": self.device_name,
            "precision": "fp16"
            if self.runtime_torch_dtype == torch.float16
            else "bf16"
            if self.runtime_torch_dtype == torch.bfloat16
            else "fp32",
            "prompt_count": len(prompt_groups),
            "prompt_item_count": len(prompt_texts),
            "prompt_group_count": len(prompt_groups),
            "positive_prompt_count": sum(len(item) for item in positive_text_map),
            "negative_prompt_count": sum(len(item) for item in negative_text_map),
            "negative_prompt_weight": self.NEGATIVE_PROMPT_WEIGHT,
            "prompt_texts": source_prompt_texts,
            "region_count": len(region_items),
            "inference_mode": "semantic-segment",
            "text_encoder": "checkpoint-language-backbone",
            "postprocess_profile": "sam3-default",
            "mask_threshold": mask_threshold,
            "stability_offset": stability_offset,
            "min_component_area": min_component_area,
            "polygon_simplify_ratio": polygon_simplify_ratio,
            "prompt_groups": [
                {
                    "prompt_id": str(getattr(group, "prompt_id", "")),
                    "display_name": prompt_display_names[index],
                    "positive_texts": list(positive_text_map[index]),
                    "negative_texts": list(negative_text_map[index]),
                    "languages": list(prompt_group_languages[index]),
                }
                for index, group in enumerate(prompt_groups)
            ],
            "feature_cache": {
                "scope": "latest-image",
                "key_components": [
                    "session-generation",
                    "model-asset",
                    "device",
                    "precision",
                    "inference-profile",
                    "image-content-sha256",
                ],
                "hit": feature_cache_hit,
                "hits": self._feature_cache_hits,
                "misses": self._feature_cache_misses,
                "session_generation": self.session_generation,
                "checkpoint_sha256": self.checkpoint_sha256 or None,
            },
            "timings_ms": {
                "preprocess": preprocess_ms,
                "backbone": backbone_ms,
                "prompt_prepare": prompt_prepare_ms,
                "prompt_encoder": text_encoder_ms,
                "decoder": decoder_ms,
                "postprocess": postprocess_ms,
            },
            "cuda_memory": _read_cuda_memory_summary(self.device_name),
            "checkpoint_compatibility": dict(
                getattr(self.model, "checkpoint_compatibility_summary", {})
            ),
        }
        return Sam3SemanticPrediction(regions=tuple(region_items), summary=summary)

    def close(self) -> None:
        """释放模型引用和可回收的 CUDA 显存。"""

        self.model.to(device=torch.device("cpu"))
        self._feature_cache_key = None
        self._feature_cache_value = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def _read_cuda_memory_summary(device_name: str) -> dict[str, int] | None:
    """读取当前 session 设备的 CUDA 显存诊断值。"""

    if not device_name.startswith("cuda") or not torch.cuda.is_available():
        return None
    device = torch.device(device_name)
    return {
        "allocated_bytes": int(torch.cuda.memory_allocated(device)),
        "reserved_bytes": int(torch.cuda.memory_reserved(device)),
        "max_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
        "max_reserved_bytes": int(torch.cuda.max_memory_reserved(device)),
    }


def _build_grouped_prompt_tokens(
    *,
    prompt_padding_mask: torch.Tensor,
    prompt_tokens: torch.Tensor,
    prompt_text_offsets: tuple[tuple[int, int, int], ...],
    negative_prompt_weight: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    """按 prompt 组聚合 token-level text memory，并把负提示作为抑制项并入。"""

    prompt_tokens_batch_first = prompt_tokens.transpose(0, 1).contiguous()
    grouped_padding_masks: list[torch.Tensor] = []
    grouped_prompt_tokens: list[torch.Tensor] = []
    for positive_start, positive_count, negative_count in prompt_text_offsets:
        positive_end = positive_start + positive_count
        positive_padding_mask = prompt_padding_mask[positive_start:positive_end]
        positive_prompt_tokens = prompt_tokens_batch_first[positive_start:positive_end]
        group_padding_mask, group_prompt_tokens = _average_group_prompt_tokens(
            prompt_padding_mask=positive_padding_mask,
            prompt_tokens=positive_prompt_tokens,
        )
        if negative_count > 0:
            negative_start = positive_end
            negative_end = negative_start + negative_count
            negative_padding_mask = prompt_padding_mask[negative_start:negative_end]
            negative_prompt_tokens = prompt_tokens_batch_first[
                negative_start:negative_end
            ]
            _negative_group_padding_mask, negative_group_prompt_tokens = (
                _average_group_prompt_tokens(
                    prompt_padding_mask=negative_padding_mask,
                    prompt_tokens=negative_prompt_tokens,
                )
            )
            group_prompt_tokens = (
                group_prompt_tokens
                - float(negative_prompt_weight) * negative_group_prompt_tokens
            )
            group_prompt_tokens = F.normalize(group_prompt_tokens, dim=-1, p=2)
            group_prompt_tokens[group_padding_mask] = 0.0
        grouped_padding_masks.append(group_padding_mask)
        grouped_prompt_tokens.append(group_prompt_tokens)
    return (
        torch.stack(grouped_padding_masks, dim=0).contiguous(),
        torch.stack(grouped_prompt_tokens, dim=0).transpose(0, 1).contiguous(),
    )


def _average_group_prompt_tokens(
    *,
    prompt_padding_mask: torch.Tensor,
    prompt_tokens: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """对同组文本提示的 token-level memory 做按有效位置平均。"""

    valid_mask = (~prompt_padding_mask).to(prompt_tokens.dtype)[..., None]
    valid_count = valid_mask.sum(dim=0)
    group_padding_mask = valid_count.squeeze(-1) <= 0
    normalized_valid_count = torch.clamp(valid_count, min=1.0)
    averaged_prompt_tokens = (prompt_tokens * valid_mask).sum(
        dim=0
    ) / normalized_valid_count
    averaged_prompt_tokens[group_padding_mask] = 0.0
    return group_padding_mask, averaged_prompt_tokens


def _build_group_source_prompt_text(
    positive_texts: tuple[str, ...],
    negative_texts: tuple[str, ...],
) -> str:
    """为 semantic 结果构造可追溯的文本组合摘要。"""

    positive_segment = " | ".join(str(item) for item in positive_texts)
    if not negative_texts:
        return positive_segment
    negative_segment = " | ".join(f"!{item}" for item in negative_texts)
    return f"{positive_segment} || {negative_segment}"


__all__ = [
    "Sam3SemanticImageModel",
    "Sam3SemanticPrediction",
    "Sam3SemanticRuntimeSession",
    "build_sam3_semantic_image_model",
]
