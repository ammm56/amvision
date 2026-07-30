"""SAM3.1 16-slot bucketized mask decoder。"""

from __future__ import annotations

import torch
from torch import nn

from .common import LayerNorm2d, MLP
from .prompt_mask_modules import SAM2TwoWayTransformer


class Sam3MultiplexMaskDecoder(nn.Module):
    """用一次 Two-Way Transformer 解码一个固定容量对象 bucket。"""

    def __init__(
        self,
        *,
        transformer_dim: int = 256,
        multiplex_count: int = 16,
        num_multimask_outputs: int = 3,
        use_high_res_features: bool = True,
        dynamic_multimask_via_stability: bool = False,
        dynamic_multimask_stability_delta: float = 0.05,
        dynamic_multimask_stability_thresh: float = 0.98,
        pred_obj_scores: bool = True,
        pred_obj_scores_mlp: bool = True,
        use_multimask_token_for_obj_ptr: bool = True,
    ) -> None:
        super().__init__()
        self.transformer_dim = transformer_dim
        self.transformer = SAM2TwoWayTransformer(
            depth=2,
            embedding_dim=transformer_dim,
            mlp_dim=2048,
            num_heads=8,
        )
        self.multiplex_count = multiplex_count
        self.num_multimask_outputs = num_multimask_outputs
        # SAM3.1 Multiplex 的 propagation decoder 只保存三个 multimask
        # token，不包含单独的 single-mask token。
        self.num_mask_output_per_object = num_multimask_outputs
        self.num_mask_tokens = (
            multiplex_count * self.num_mask_output_per_object
        )
        self.pred_obj_scores = pred_obj_scores
        self.use_multimask_token_for_obj_ptr = (
            use_multimask_token_for_obj_ptr
        )

        self.iou_token = nn.Embedding(multiplex_count, transformer_dim)
        self.obj_score_token = nn.Embedding(
            multiplex_count,
            transformer_dim,
        )
        self.mask_tokens = nn.Embedding(
            self.num_mask_tokens,
            transformer_dim,
        )
        self.output_upscaling = nn.Sequential(
            nn.ConvTranspose2d(
                transformer_dim,
                transformer_dim // 4,
                kernel_size=2,
                stride=2,
            ),
            LayerNorm2d(transformer_dim // 4),
            nn.GELU(),
            nn.ConvTranspose2d(
                transformer_dim // 4,
                transformer_dim // 8,
                kernel_size=2,
                stride=2,
            ),
            nn.GELU(),
        )
        self.use_high_res_features = use_high_res_features
        self.conv_s0 = nn.Conv2d(
            transformer_dim,
            transformer_dim // 8,
            kernel_size=1,
        )
        self.conv_s1 = nn.Conv2d(
            transformer_dim,
            transformer_dim // 4,
            kernel_size=1,
        )
        self.output_hypernetworks_mlps = nn.ModuleList(
            MLP(
                transformer_dim,
                transformer_dim,
                transformer_dim // 8,
                3,
            )
            for _ in range(self.num_mask_output_per_object)
        )
        self.iou_prediction_head = MLP(
            transformer_dim,
            256,
            self.num_mask_output_per_object,
            3,
        )
        self.pred_obj_score_head: nn.Module = nn.Linear(
            transformer_dim,
            1,
        )
        if pred_obj_scores_mlp:
            self.pred_obj_score_head = MLP(
                transformer_dim,
                transformer_dim,
                1,
                3,
            )

        self.dynamic_multimask_via_stability = (
            dynamic_multimask_via_stability
        )
        self.dynamic_multimask_stability_delta = (
            dynamic_multimask_stability_delta
        )
        self.dynamic_multimask_stability_thresh = (
            dynamic_multimask_stability_thresh
        )

    def forward(
        self,
        *,
        image_embeddings: torch.Tensor,
        image_pe: torch.Tensor,
        multimask_output: bool,
        high_res_features: list[torch.Tensor] | None = None,
        extra_per_object_embeddings: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        """解码 bucket 并保持对象 slot 维度。"""

        output = self.predict_masks(
            image_embeddings=image_embeddings,
            image_pe=image_pe,
            high_res_features=high_res_features,
            extra_per_object_embeddings=extra_per_object_embeddings,
        )
        masks = output["masks"]
        iou_prediction = output["iou_pred"]
        mask_tokens = output["mask_tokens_out"]
        if not multimask_output:
            raise ValueError(
                "SAM3.1 bucket decoder 只能按 checkpoint 的 multimask 模式执行"
            )
        object_tokens = (
            mask_tokens
            if self.use_multimask_token_for_obj_ptr
            else mask_tokens[:, :, :1]
        )
        output["masks"] = masks
        output["iou_pred"] = iou_prediction
        output["sam_tokens_out"] = object_tokens
        del output["mask_tokens_out"]
        return output

    def predict_masks(
        self,
        *,
        image_embeddings: torch.Tensor,
        image_pe: torch.Tensor,
        high_res_features: list[torch.Tensor] | None,
        extra_per_object_embeddings: torch.Tensor | None,
    ) -> dict[str, torch.Tensor]:
        """执行 bucket token transformer 和 hypernetwork mask 投影。"""

        batch_size = image_embeddings.shape[0]
        attribute_tokens = torch.cat(
            (
                self.obj_score_token.weight,
                self.iou_token.weight,
            ),
            dim=0,
        ).unsqueeze(0).expand(batch_size, -1, -1)
        mask_tokens = self.mask_tokens.weight.view(
            1,
            self.multiplex_count,
            self.num_mask_output_per_object,
            -1,
        ).expand(batch_size, -1, -1, -1)
        if extra_per_object_embeddings is not None:
            if tuple(extra_per_object_embeddings.shape[:2]) != (
                batch_size,
                self.multiplex_count,
            ):
                raise ValueError(
                    "SAM3 bucket suppression embedding shape 不匹配"
                )
            mask_tokens = (
                mask_tokens
                + extra_per_object_embeddings.unsqueeze(2)
            )
        flattened_mask_tokens = mask_tokens.flatten(1, 2)
        tokens = torch.cat(
            (attribute_tokens, flattened_mask_tokens),
            dim=1,
        )
        if image_pe.shape[0] != 1:
            raise ValueError("SAM3 propagation image_pe batch 必须是 1")
        position_source = image_pe.expand(batch_size, -1, -1, -1)
        hidden_states, source = self.transformer(
            image_embeddings,
            position_source,
            tokens,
        )
        token_offset = 0
        object_score_token = hidden_states[
            :,
            token_offset : token_offset + self.multiplex_count,
        ]
        token_offset += self.multiplex_count
        iou_token = hidden_states[
            :,
            token_offset : token_offset + self.multiplex_count,
        ]
        token_offset += self.multiplex_count
        mask_token_output = hidden_states[:, token_offset:]
        if mask_token_output.shape[1] != self.num_mask_tokens:
            raise RuntimeError("SAM3 bucket decoder 输出 token 数量不正确")

        channels = source.shape[-1]
        height, width = image_embeddings.shape[-2:]
        source = source.transpose(1, 2).reshape(
            batch_size,
            channels,
            height,
            width,
        )
        if self.use_high_res_features:
            if high_res_features is None or len(high_res_features) != 2:
                raise ValueError(
                    "SAM3 bucket decoder 缺少两级高分辨率特征"
                )
            deconv1, norm1, activation1, deconv2, activation2 = (
                self.output_upscaling
            )
            feature_s0, feature_s1 = high_res_features
            upscaled = activation1(
                norm1(deconv1(source) + feature_s1)
            )
            upscaled = activation2(deconv2(upscaled) + feature_s0)
        else:
            upscaled = self.output_upscaling(source)

        mask_token_output = mask_token_output.reshape(
            batch_size,
            self.multiplex_count,
            self.num_mask_output_per_object,
            -1,
        )
        hyper_inputs = torch.stack(
            tuple(
                hypernetwork(mask_token_output[:, :, index])
                for index, hypernetwork in enumerate(
                    self.output_hypernetworks_mlps
                )
            ),
            dim=2,
        )
        _, upscaled_channels, upscaled_height, upscaled_width = (
            upscaled.shape
        )
        masks = torch.bmm(
            hyper_inputs.flatten(1, 2),
            upscaled.reshape(
                batch_size,
                upscaled_channels,
                upscaled_height * upscaled_width,
            ),
        ).reshape(
            batch_size,
            self.multiplex_count,
            self.num_mask_output_per_object,
            upscaled_height,
            upscaled_width,
        )
        iou_prediction = self.iou_prediction_head(iou_token).reshape(
            batch_size,
            self.multiplex_count,
            self.num_mask_output_per_object,
        )
        object_score_logits = self.pred_obj_score_head(
            object_score_token
        )
        return {
            "masks": masks,
            "iou_pred": iou_prediction,
            "mask_tokens_out": mask_token_output,
            "object_score_logits": object_score_logits,
        }

    def _get_stability_scores(
        self,
        mask_logits: torch.Tensor,
    ) -> torch.Tensor:
        flattened = mask_logits.flatten(-2)
        intersection = (
            flattened > self.dynamic_multimask_stability_delta
        ).sum(dim=-1).float()
        union = (
            flattened > -self.dynamic_multimask_stability_delta
        ).sum(dim=-1).float()
        return torch.where(union > 0, intersection / union, 1.0)

    def _dynamic_multimask_via_stability(
        self,
        all_mask_logits: torch.Tensor,
        all_iou_scores: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        batch_size, multiplex_count = all_mask_logits.shape[:2]
        mask_logits = all_mask_logits.flatten(0, 1)
        iou_scores = all_iou_scores.flatten(0, 1)
        multi_logits = mask_logits[:, 1:]
        multi_scores = iou_scores[:, 1:]
        best_indices = multi_scores.argmax(dim=-1)
        batch_indices = torch.arange(
            multi_scores.shape[0],
            device=multi_scores.device,
        )
        best_logits = multi_logits[
            batch_indices,
            best_indices,
        ].unsqueeze(1)
        best_scores = multi_scores[
            batch_indices,
            best_indices,
        ].unsqueeze(1)
        single_logits = mask_logits[:, :1]
        single_scores = iou_scores[:, :1]
        stable = (
            self._get_stability_scores(single_logits)
            >= self.dynamic_multimask_stability_thresh
        )
        selected_logits = torch.where(
            stable[..., None, None],
            single_logits,
            best_logits,
        )
        selected_scores = torch.where(
            stable,
            single_scores,
            best_scores,
        )
        return (
            selected_logits.unflatten(0, (batch_size, multiplex_count)),
            selected_scores.unflatten(0, (batch_size, multiplex_count)),
        )


__all__ = ["Sam3MultiplexMaskDecoder"]
