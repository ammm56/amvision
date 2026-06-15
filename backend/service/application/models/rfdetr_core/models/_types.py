"""RF-DETR core 模型结构模块：`models._types`。"""

from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable


@runtime_checkable
class BuilderArgs(Protocol):
    """RF-DETR core 类：`BuilderArgs`。"""

    encoder: str
    out_feature_indexes: List[int]
    dec_layers: int
    freeze_encoder: bool
    backbone_lora: bool
    two_stage: bool
    projector_scale: List[str]
    hidden_dim: int
    patch_size: int
    num_windows: int
    sa_nheads: int
    ca_nheads: int
    dec_n_points: int
    bbox_reparam: bool
    lite_refpoint_refine: bool
    layer_norm: bool
    amp: bool
    num_classes: int
    pretrain_weights: Optional[str]
    device: str
    resolution: int
    group_detr: int
    gradient_checkpointing: bool
    positional_encoding_size: int
    ia_bce_loss: bool
    cls_loss_coef: float
    segmentation_head: bool
    mask_downsample_ratio: int
    num_queries: int
    num_select: int
    vit_encoder_num_layers: int
    window_block_indexes: Optional[List[int]]
    position_embedding: str
    rms_norm: bool
    force_no_pretrain: bool
    dim_feedforward: int
    use_cls_token: bool
    pretrained_encoder: Optional[str]
    backbone_only: bool
    encoder_only: bool
    aux_loss: bool
    focal_alpha: float
    bbox_loss_coef: float
    giou_loss_coef: float
    set_cost_class: float
    set_cost_bbox: float
    set_cost_giou: float
    use_varifocal_loss: bool
    use_position_supervised_loss: bool
    sum_group_losses: bool
    mask_ce_loss_coef: float
    mask_dice_loss_coef: float
    mask_point_sample_ratio: int
