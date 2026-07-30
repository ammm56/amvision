"""SAM3.1 Multiplex 视频 propagation 模型。"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import torch
from torch import nn
import torch.nn.functional as F

from backend.service.application.errors import InvalidRequestError

from ..checkpoint.loader import (
    Sam3CheckpointBranches,
    build_sam3_multiplex_propagation_state_dict,
)
from ..nn.common import MLP, get_1d_sine_pe
from ..nn.multiplex_mask_decoder import Sam3MultiplexMaskDecoder
from ..nn.multiplex_memory import (
    Sam3MultiplexMaskEncoder,
    build_sam3_multiplex_mask_encoder,
)
from ..nn.multiplex_transformer import Sam3MultiplexMemoryTransformer
from ..nn.prompt_mask_modules import PositionEmbeddingRandom
from ..nn.vision_backbone import (
    PositionEmbeddingSine,
    SAM3VisualBackbone,
    Sam3ViTDetNeck,
    ViT,
    release_rotary_device_caches,
)
from ..preprocess.image import PreparedSam3Image, preprocess_sam3_image
from ..state.multiplex import Sam3MultiplexState


@dataclass(frozen=True)
class Sam3MultiplexFrameFeatures:
    """描述一帧 propagation neck 输出。"""

    pixel_feature: torch.Tensor
    pixel_position: torch.Tensor
    high_resolution_features: tuple[torch.Tensor, torch.Tensor]


@dataclass(frozen=True)
class Sam3MultiplexMemoryEntry:
    """描述一帧请求内 memory state。"""

    frame_index: int
    conditioning: bool
    memory_feature: torch.Tensor
    memory_position: torch.Tensor
    image_feature: torch.Tensor
    image_position: torch.Tensor
    object_pointers: torch.Tensor


@dataclass(frozen=True)
class Sam3MultiplexPropagationOutput:
    """描述一次 bucket decoder 输出。"""

    mask_logits: torch.Tensor
    iou_scores: torch.Tensor
    object_score_logits: torch.Tensor
    object_pointers: torch.Tensor
    memory_entry: Sam3MultiplexMemoryEntry


@dataclass(frozen=True)
class Sam3MultiplexFrameContext:
    """描述一帧预处理结果和 propagation neck 特征。"""

    prepared_image: PreparedSam3Image
    features: Sam3MultiplexFrameFeatures
    image_identity: str
    preprocess_ms: float
    backbone_ms: float


class _Sam3MemoryTransformerWrapper(nn.Module):
    """保持 checkpoint 的 ``transformer.encoder`` 命名。"""

    def __init__(self) -> None:
        super().__init__()
        self.encoder = Sam3MultiplexMemoryTransformer()


class Sam3MultiplexPropagationModel(nn.Module):
    """持有 propagation neck、memory encoder 与 bucket decoder。"""

    image_size = 1008
    backbone_stride = 14
    hidden_dim = 256
    num_mask_memory = 7

    def __init__(
        self,
        *,
        shared_trunk: ViT,
        multiplex_count: int = 16,
    ) -> None:
        super().__init__()
        self.multiplex_count = multiplex_count
        self.image_encoder = SAM3VisualBackbone(
            vision_backbone=Sam3ViTDetNeck(
                trunk=shared_trunk,
                position_encoding=PositionEmbeddingSine(
                    num_pos_feats=256,
                    normalize=True,
                    scale=None,
                    temperature=10000,
                ),
                d_model=256,
                branch_name="propagation_convs",
            ),
            scalp=0,
        )
        self.transformer = _Sam3MemoryTransformerWrapper()
        self.maskmem_backbone: Sam3MultiplexMaskEncoder = (
            build_sam3_multiplex_mask_encoder(
                multiplex_count=multiplex_count
            )
        )
        self.sam_mask_decoder = Sam3MultiplexMaskDecoder(
            multiplex_count=multiplex_count
        )
        self.image_pe_layer = PositionEmbeddingRandom(
            self.hidden_dim // 2
        )
        self.maskmem_tpos_enc = nn.Parameter(
            torch.zeros(
                self.num_mask_memory,
                1,
                1,
                self.hidden_dim,
            )
        )
        self.no_obj_embed_spatial = nn.Parameter(
            torch.zeros(multiplex_count, self.hidden_dim)
        )
        self.output_valid_embed = nn.Parameter(
            torch.zeros(multiplex_count, self.hidden_dim)
        )
        self.output_invalid_embed = nn.Parameter(
            torch.zeros(multiplex_count, self.hidden_dim)
        )
        self.obj_ptr_proj = MLP(
            self.hidden_dim,
            self.hidden_dim,
            self.hidden_dim,
            3,
        )
        self.interactive_obj_ptr_proj = MLP(
            self.hidden_dim,
            self.hidden_dim,
            self.hidden_dim,
            3,
        )
        self.no_obj_ptr_linear = nn.Linear(
            self.hidden_dim,
            self.hidden_dim,
        )
        self.obj_ptr_tpos_proj = nn.Linear(
            self.hidden_dim,
            self.hidden_dim,
        )

    def extract_frame_features(
        self,
        image_tensor: torch.Tensor,
        *,
        trunk_feature: torch.Tensor,
    ) -> Sam3MultiplexFrameFeatures:
        """从共享 ViT 输出计算 propagation neck。"""

        backbone = self.image_encoder.forward_image(
            image_tensor,
            trunk_feature=trunk_feature,
        )
        feature_maps = backbone["backbone_fpn"]
        positions = backbone["vision_pos_enc"]
        high_resolution_features = (
            self.sam_mask_decoder.conv_s0(feature_maps[0]),
            self.sam_mask_decoder.conv_s1(feature_maps[1]),
        )
        return Sam3MultiplexFrameFeatures(
            pixel_feature=feature_maps[-1],
            pixel_position=positions[-1],
            high_resolution_features=high_resolution_features,
        )

    def project_interactive_object_tokens(
        self,
        object_tokens: torch.Tensor,
    ) -> torch.Tensor:
        """把 interactive decoder token 投影为视频 object pointer。"""

        return self.interactive_obj_ptr_proj(object_tokens)

    def encode_memory(
        self,
        *,
        frame_index: int,
        frame_features: Sam3MultiplexFrameFeatures,
        multiplex_state: Sam3MultiplexState,
        mask_logits: torch.Tensor,
        object_score_logits: torch.Tensor,
        object_pointers: torch.Tensor,
        conditioning: bool,
    ) -> Sam3MultiplexMemoryEntry:
        """把当前图像与对象 mask 编成下一帧可消费的 memory。"""

        bucket_count = multiplex_state.num_buckets
        pixel_feature = frame_features.pixel_feature.expand(
            bucket_count,
            -1,
            -1,
            -1,
        )
        mask_probability = (
            mask_logits.sigmoid().to(pixel_feature.dtype) * 2.0 - 1.0
        )
        multiplexed_masks = multiplex_state.mux(mask_probability).squeeze(2)
        condition_value = 1.0 if conditioning else 0.0
        condition_channels = torch.full_like(
            mask_probability,
            condition_value,
        )
        multiplexed_conditions = multiplex_state.mux(
            condition_channels
        ).squeeze(2)
        memory_input = torch.cat(
            (multiplexed_masks, multiplexed_conditions),
            dim=1,
        )
        encoded = self.maskmem_backbone(
            pixel_feature,
            memory_input,
            skip_mask_sigmoid=True,
        )
        memory_feature = encoded["vision_features"]
        memory_position = encoded["vision_pos_enc"][-1]
        multiplexed_object_scores = multiplex_state.mux(
            object_score_logits
        )
        appearing = (multiplexed_object_scores > 0).to(
            memory_feature.dtype
        )
        missing_embedding = (
            (1.0 - appearing)
            * self.no_obj_embed_spatial.unsqueeze(0)
        ).sum(dim=1)
        memory_feature = (
            memory_feature
            + missing_embedding[..., None, None]
        )
        return Sam3MultiplexMemoryEntry(
            frame_index=frame_index,
            conditioning=conditioning,
            memory_feature=memory_feature,
            memory_position=memory_position,
            image_feature=frame_features.pixel_feature,
            image_position=frame_features.pixel_position,
            object_pointers=object_pointers,
        )

    def propagate(
        self,
        *,
        frame_index: int,
        frame_features: Sam3MultiplexFrameFeatures,
        multiplex_state: Sam3MultiplexState,
        memory_entries: tuple[Sam3MultiplexMemoryEntry, ...],
        total_frame_count: int,
    ) -> Sam3MultiplexPropagationOutput:
        """用最近七帧 memory 和 16-slot decoder 传播对象 mask。"""

        if not memory_entries:
            raise ValueError("SAM3 propagation 缺少历史 memory")
        bucket_count = multiplex_state.num_buckets
        current_feature = frame_features.pixel_feature.expand(
            bucket_count,
            -1,
            -1,
            -1,
        )
        current_position = frame_features.pixel_position.expand(
            bucket_count,
            -1,
            -1,
            -1,
        )
        source = current_feature.flatten(2).transpose(1, 2)
        source_position = current_position.flatten(2).transpose(1, 2)
        conditioning_entries = tuple(
            entry for entry in memory_entries if entry.conditioning
        )
        non_conditioning_entries = tuple(
            entry for entry in memory_entries if not entry.conditioning
        )
        selected_entries = (
            conditioning_entries[:1]
            + non_conditioning_entries[
                -(self.num_mask_memory - 1) :
            ]
        )
        memory_features: list[torch.Tensor] = []
        memory_positions: list[torch.Tensor] = []
        memory_images: list[torch.Tensor] = []
        memory_image_positions: list[torch.Tensor] = []
        pointer_tokens: list[torch.Tensor] = []
        pointer_positions: list[torch.Tensor] = []
        for entry in selected_entries:
            temporal_distance = max(
                1,
                int(frame_index - entry.frame_index),
            )
            temporal_index = (
                self.num_mask_memory - 1
                if temporal_distance >= self.num_mask_memory
                else self.num_mask_memory - temporal_distance - 1
            )
            temporal_embedding = self.maskmem_tpos_enc[
                temporal_index
            ].to(entry.memory_position.dtype)
            memory_features.append(
                entry.memory_feature.flatten(2).transpose(1, 2)
            )
            memory_positions.append(
                entry.memory_position.flatten(2).transpose(1, 2)
                + temporal_embedding
            )
            memory_images.append(
                entry.image_feature.flatten(2).transpose(1, 2)
            )
            memory_image_positions.append(
                entry.image_position.flatten(2).transpose(1, 2)
                + temporal_embedding
            )
        pointer_limit = min(max(1, total_frame_count), 16)
        pointer_entries = (
            conditioning_entries[:1]
            + non_conditioning_entries[-(pointer_limit - 1) :]
            if pointer_limit > 1
            else conditioning_entries[:1]
        )
        for entry in pointer_entries:
            temporal_distance = max(
                1,
                int(frame_index - entry.frame_index),
            )
            pointer_tokens.append(entry.object_pointers)
            normalized_distance = torch.tensor(
                [
                    float(temporal_distance)
                    / float(max(1, pointer_limit - 1))
                ],
                device=current_feature.device,
                dtype=current_feature.dtype,
            )
            temporal_pointer = get_1d_sine_pe(
                normalized_distance,
                self.hidden_dim,
            ).to(dtype=current_feature.dtype)
            temporal_pointer = self.obj_ptr_tpos_proj(
                temporal_pointer
            )
            pointer_positions.append(
                temporal_pointer[:, None, :].expand(
                    bucket_count,
                    self.multiplex_count,
                    -1,
                )
            )
        memory = torch.cat(memory_features, dim=1)
        memory_position = torch.cat(memory_positions, dim=1)
        memory_image = torch.cat(memory_images, dim=1)
        memory_image_position = torch.cat(
            memory_image_positions,
            dim=1,
        )
        flattened_pointers = torch.cat(pointer_tokens, dim=1)
        flattened_pointer_positions = torch.cat(
            pointer_positions,
            dim=1,
        )
        memory = torch.cat((memory, flattened_pointers), dim=1)
        memory_position = torch.cat(
            (memory_position, flattened_pointer_positions),
            dim=1,
        )
        conditioned = self.transformer.encoder(
            image=source,
            source=source,
            memory_image=memory_image,
            memory=memory,
            source_position=source_position,
            memory_image_position=memory_image_position,
            memory_position=memory_position,
            object_pointer_token_count=flattened_pointers.shape[1],
        )["memory"]
        conditioned_feature = conditioned.transpose(1, 2).reshape(
            bucket_count,
            self.hidden_dim,
            current_feature.shape[-2],
            current_feature.shape[-1],
        )
        valid = (
            multiplex_state.get_valid_object_mask()
            .unsqueeze(-1)
            .to(conditioned_feature.dtype)
        )
        suppression = (
            valid * self.output_valid_embed.unsqueeze(0)
            + (1.0 - valid) * self.output_invalid_embed.unsqueeze(0)
        )
        high_resolution_features = [
            feature.expand(bucket_count, -1, -1, -1)
            for feature in frame_features.high_resolution_features
        ]
        decoded = self.sam_mask_decoder(
            image_embeddings=conditioned_feature,
            image_pe=self.image_pe_layer(
                (
                    conditioned_feature.shape[-2],
                    conditioned_feature.shape[-1],
                )
            )
            .unsqueeze(0)
            .to(
                device=conditioned_feature.device,
                dtype=conditioned_feature.dtype,
            ),
            high_res_features=high_resolution_features,
            multimask_output=True,
            extra_per_object_embeddings=suppression,
        )
        bucket_masks = decoded["masks"]
        bucket_ious = decoded["iou_pred"]
        best_indices = bucket_ious.argmax(dim=-1)
        batch_indices = torch.arange(
            bucket_count,
            device=bucket_ious.device,
        )[:, None]
        slot_indices = torch.arange(
            self.multiplex_count,
            device=bucket_ious.device,
        )[None, :]
        selected_bucket_masks = bucket_masks[
            batch_indices,
            slot_indices,
            best_indices,
        ].unsqueeze(2)
        selected_bucket_ious = bucket_ious[
            batch_indices,
            slot_indices,
            best_indices,
        ]
        token_candidates = decoded["sam_tokens_out"]
        selected_tokens = token_candidates[
            batch_indices,
            slot_indices,
            best_indices,
        ]
        bucket_object_scores = decoded["object_score_logits"]
        object_scores = multiplex_state.demux(
            bucket_object_scores
        )
        selected_masks = multiplex_state.demux(
            selected_bucket_masks
        )
        selected_ious = multiplex_state.demux(
            selected_bucket_ious
        )
        object_tokens = multiplex_state.demux(selected_tokens)
        object_pointers = self.obj_ptr_proj(object_tokens)
        object_present = object_scores > 0
        object_pointers = (
            object_present.to(object_pointers.dtype) * object_pointers
            + (~object_present).to(object_pointers.dtype)
            * self.no_obj_ptr_linear(object_pointers)
        )
        high_resolution_masks = F.interpolate(
            selected_masks.float(),
            size=(self.image_size, self.image_size),
            mode="bilinear",
            align_corners=False,
        )
        high_resolution_masks = torch.where(
            object_present[:, :, None, None],
            high_resolution_masks,
            high_resolution_masks.new_full((), -1024.0),
        )
        memory_entry = self.encode_memory(
            frame_index=frame_index,
            frame_features=frame_features,
            multiplex_state=multiplex_state,
            mask_logits=high_resolution_masks,
            object_score_logits=object_scores,
            object_pointers=multiplex_state.mux(object_pointers),
            conditioning=False,
        )
        return Sam3MultiplexPropagationOutput(
            mask_logits=high_resolution_masks,
            iou_scores=selected_ious,
            object_score_logits=object_scores,
            object_pointers=object_pointers,
            memory_entry=memory_entry,
        )


def load_sam3_multiplex_propagation_weights(
    *,
    model: Sam3MultiplexPropagationModel,
    checkpoint_path: Path,
    checkpoint_branches: Sam3CheckpointBranches,
) -> dict[str, object]:
    """严格验证 propagation 所需 checkpoint tensor 全部匹配。"""

    source = build_sam3_multiplex_propagation_state_dict(
        checkpoint_branches
    )
    target = model.state_dict()
    shape_mismatches = {
        key: {
            "expected": list(target[key].shape),
            "actual": list(value.shape),
        }
        for key, value in source.items()
        if key in target and tuple(target[key].shape) != tuple(value.shape)
    }
    compatible = {
        key: value
        for key, value in source.items()
        if key in target and tuple(target[key].shape) == tuple(value.shape)
    }
    incompatible = model.load_state_dict(compatible, strict=False)
    missing_parameters = sorted(
        key
        for key in incompatible.missing_keys
        if key in dict(model.named_parameters())
    )
    if shape_mismatches or missing_parameters:
        raise InvalidRequestError(
            "SAM3.1 Multiplex propagation 权重与模型结构不兼容",
            details={
                "checkpoint_path": str(checkpoint_path),
                "shape_mismatches": shape_mismatches,
                "missing_parameter_keys": missing_parameters,
            },
        )
    return {
        "loaded_key_count": len(compatible),
        "source_key_count": len(source),
        "ignored_source_key_count": len(source) - len(compatible),
        "multiplex_count": model.multiplex_count,
    }


class Sam3MultiplexRuntimeSession:
    """封装 AppRuntime 内可复用、请求内串行的 propagation 模型。"""

    def __init__(
        self,
        *,
        model: Sam3MultiplexPropagationModel,
        model_asset_id: str,
        architecture_id: str,
        checkpoint_sha256: str | None,
        device_name: str,
        runtime_torch_dtype: torch.dtype,
        shared_trunk_cache: object | None,
        owns_model: bool = False,
    ) -> None:
        self.model = model
        self.model_asset_id = model_asset_id
        self.architecture_id = architecture_id
        self.checkpoint_sha256 = str(checkpoint_sha256 or "").strip()
        self.device_name = device_name
        self.runtime_torch_dtype = runtime_torch_dtype
        self.session_generation = uuid4().hex
        self._shared_trunk_cache = shared_trunk_cache
        self._owns_model = bool(owns_model)

    @torch.inference_mode()
    def prepare_frame_context(
        self,
        *,
        image_bytes: bytes,
        image_payload: object,
    ) -> Sam3MultiplexFrameContext:
        """预处理单帧并提取 propagation neck 特征。"""

        preprocess_started_at = perf_counter()
        prepared_image = preprocess_sam3_image(
            image_bytes,
            image_payload=image_payload,
            precision=(
                "fp16"
                if self.runtime_torch_dtype == torch.float16
                else "bf16"
                if self.runtime_torch_dtype == torch.bfloat16
                else "fp32"
            ),
        )
        prepared_image = PreparedSam3Image(
            image_tensor=prepared_image.image_tensor.to(
                device=torch.device(self.device_name),
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
        image_identity = sha256(image_bytes).hexdigest()
        trunk_feature = None
        backbone_started_at = perf_counter()
        if self._shared_trunk_cache is not None:
            get_or_compute = getattr(
                self._shared_trunk_cache,
                "get_or_compute",
                None,
            )
            if callable(get_or_compute):
                trunk_feature = get_or_compute(
                    image_identity=image_identity,
                    image_tensor=prepared_image.image_tensor,
                    trunk=self.model.image_encoder.vision_backbone.trunk,
                )
        if trunk_feature is None:
            trunk_outputs = self.model.image_encoder.vision_backbone.trunk(
                prepared_image.image_tensor
            )
            if not trunk_outputs:
                raise RuntimeError("SAM3 propagation ViT trunk 没有返回特征")
            trunk_feature = trunk_outputs[-1]
        features = self.model.extract_frame_features(
            prepared_image.image_tensor,
            trunk_feature=trunk_feature,
        )
        if features.pixel_feature.is_cuda:
            torch.cuda.synchronize(features.pixel_feature.device)
        backbone_ms = round(
            (perf_counter() - backbone_started_at) * 1000,
            3,
        )
        return Sam3MultiplexFrameContext(
            prepared_image=prepared_image,
            features=features,
            image_identity=image_identity,
            preprocess_ms=preprocess_ms,
            backbone_ms=backbone_ms,
        )

    def diagnostics(self) -> dict[str, object]:
        """返回不包含 checkpoint 路径的运行时摘要。"""

        return {
            "project_native": True,
            "runtime": "sam3.1-multiplex-propagation",
            "model_asset_id": self.model_asset_id,
            "architecture_id": self.architecture_id,
            "device": self.device_name,
            "precision": (
                "fp16"
                if self.runtime_torch_dtype == torch.float16
                else "bf16"
                if self.runtime_torch_dtype == torch.bfloat16
                else "fp32"
            ),
            "checkpoint_sha256": self.checkpoint_sha256 or None,
            "session_generation": self.session_generation,
            "multiplex_count": self.model.multiplex_count,
            "memory_frame_limit": self.model.num_mask_memory,
            "request_state_scope": "node-execution",
            "session_serialized": True,
        }

    def close(self) -> None:
        """仅在独占模型时迁回 CPU。共享 owner 由上层统一释放。"""

        if self._owns_model:
            release_rotary_device_caches(self.model)
            self.model.to(device=torch.device("cpu"))
            if torch.cuda.is_available():
                torch.cuda.empty_cache()


__all__ = [
    "Sam3MultiplexFrameFeatures",
    "Sam3MultiplexFrameContext",
    "Sam3MultiplexMemoryEntry",
    "Sam3MultiplexPropagationModel",
    "Sam3MultiplexPropagationOutput",
    "Sam3MultiplexRuntimeSession",
    "load_sam3_multiplex_propagation_weights",
]
