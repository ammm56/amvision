"""RF-DETR core 模型结构模块：`models._defaults`。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True, slots=True)
class ModelDefaults:
    """RF-DETR core 类：`ModelDefaults`。"""

    drop_mode: str = "standard"
    drop_schedule: str = "constant"
    cutoff_epoch: int = 0
    pretrained_encoder: Optional[str] = None
    pretrain_exclude_keys: Optional[List[str]] = None
    pretrain_keys_modify_to_load: Optional[Dict[str, str]] = None
    pretrained_distiller: Optional[str] = None
    vit_encoder_num_layers: int = 12
    window_block_indexes: Optional[List[int]] = None
    position_embedding: str = "sine"
    rms_norm: bool = False
    force_no_pretrain: bool = False
    dim_feedforward: int = 2048
    decoder_norm: str = "LN"
    freeze_batch_norm: bool = False
    use_cls_token: bool = False
    encoder_only: bool = False
    backbone_only: bool = False
    aux_loss: bool = True
    focal_alpha: float = 0.25
    set_cost_class: float = 2.0
    set_cost_bbox: float = 5.0
    set_cost_giou: float = 2.0
    bbox_loss_coef: float = 5.0
    giou_loss_coef: float = 2.0
    sum_group_losses: bool = False
    use_varifocal_loss: bool = False
    use_position_supervised_loss: bool = False
    print_freq: int = 10
    do_benchmark: bool = False
    dropout: float = 0.0
    coco_path: Optional[str] = None
    dont_save_weights: bool = False
    start_epoch: int = 0
    eval: bool = False
    world_size: int = 1
    dist_url: str = "env://"
    lr_scheduler: str = "step"
    lr_min_factor: float = 0.0
    subcommand: Optional[str] = None


MODEL_DEFAULTS = ModelDefaults()
