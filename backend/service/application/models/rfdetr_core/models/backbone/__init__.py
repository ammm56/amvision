from typing import Callable

import torch
from torch import nn

from backend.service.application.models.rfdetr_core.models.backbone.backbone import Backbone
from backend.service.application.models.rfdetr_core.models.position_encoding import build_position_encoding
from backend.service.application.models.rfdetr_core.utilities.tensors import NestedTensor


class Joiner(nn.Sequential):
    def __init__(self, backbone, position_embedding):
        super().__init__(backbone, position_embedding)
        self._export = False

    def forward(self, tensor_list: NestedTensor):
        """"""
        x = self[0](tensor_list)
        pos = []
        for x_ in x:
            pos.append(self[1](x_, align_dim_orders=False).to(x_.tensors.dtype))
        return x, pos

    def export(self):
        self._export = True
        self._forward_origin = self.forward
        self.forward = self.forward_export
        for name, m in self.named_modules():
            if hasattr(m, "export") and isinstance(m.export, Callable) and hasattr(m, "_export") and not m._export:
                m.export()

    def forward_export(self, inputs: torch.Tensor):
        feats, masks = self[0](inputs)
        poss = []
        for feat, mask in zip(feats, masks):
            poss.append(self[1](mask, align_dim_orders=False).to(feat.dtype))
        return feats, None, poss


def build_backbone(
    encoder,
    vit_encoder_num_layers,
    pretrained_encoder,
    window_block_indexes,
    drop_path,
    out_channels,
    out_feature_indexes,
    projector_scale,
    use_cls_token,
    hidden_dim,
    position_embedding,
    freeze_encoder,
    layer_norm,
    target_shape,
    rms_norm,
    backbone_lora,
    force_no_pretrain,
    gradient_checkpointing,
    load_dinov2_weights,
    patch_size,
    num_windows,
    positional_encoding_size,
):
    """执行 `build_backbone`。
    
    参数：
    - `encoder`：传入的 `encoder` 参数。
    - `vit_encoder_num_layers`：传入的 `vit_encoder_num_layers` 参数。
    - `pretrained_encoder`：传入的 `pretrained_encoder` 参数。
    - `window_block_indexes`：传入的 `window_block_indexes` 参数。
    - `drop_path`：传入的 `drop_path` 参数。
    - `out_channels`：传入的 `out_channels` 参数。
    - `out_feature_indexes`：传入的 `out_feature_indexes` 参数。
    - `projector_scale`：传入的 `projector_scale` 参数。
    - `use_cls_token`：传入的 `use_cls_token` 参数。
    - `hidden_dim`：传入的 `hidden_dim` 参数。
    - `position_embedding`：传入的 `position_embedding` 参数。
    - `freeze_encoder`：传入的 `freeze_encoder` 参数。
    - 其他参数：按函数签名传入。
    """
    position_embedding = build_position_encoding(hidden_dim, position_embedding)

    backbone = Backbone(
        encoder,
        pretrained_encoder,
        window_block_indexes=window_block_indexes,
        drop_path=drop_path,
        out_channels=out_channels,
        out_feature_indexes=out_feature_indexes,
        projector_scale=projector_scale,
        use_cls_token=use_cls_token,
        layer_norm=layer_norm,
        freeze_encoder=freeze_encoder,
        target_shape=target_shape,
        rms_norm=rms_norm,
        backbone_lora=backbone_lora,
        gradient_checkpointing=gradient_checkpointing,
        load_dinov2_weights=load_dinov2_weights,
        patch_size=patch_size,
        num_windows=num_windows,
        positional_encoding_size=positional_encoding_size,
    )

    model = Joiner(backbone, position_embedding)
    return model
