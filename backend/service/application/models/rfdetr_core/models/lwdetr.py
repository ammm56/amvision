"""RF-DETR core 模型结构模块：`models.lwdetr`。"""

import copy
import math
from typing import TYPE_CHECKING, Callable, Optional

import torch
from torch import nn

if TYPE_CHECKING:
    from backend.service.application.models.rfdetr_core.config import ModelConfig, TrainConfig

from backend.service.application.models.rfdetr_core.models._defaults import MODEL_DEFAULTS, ModelDefaults
from backend.service.application.models.rfdetr_core.models._types import BuilderArgs
from backend.service.application.models.rfdetr_core.models.backbone import build_backbone

from backend.service.application.models.rfdetr_core.models.criterion import (  # noqa: F401 — 兼容旧导出入口
    SetCriterion,
    dice_loss,
    dice_loss_jit,
    position_supervised_loss,
    sigmoid_ce_loss,
    sigmoid_ce_loss_jit,
    sigmoid_focal_loss,
    sigmoid_varifocal_loss,
)
from backend.service.application.models.rfdetr_core.models.heads.segmentation import SegmentationHead
from backend.service.application.models.rfdetr_core.models.matcher import build_matcher
from backend.service.application.models.rfdetr_core.models.math import MLP
from backend.service.application.models.rfdetr_core.models.postprocess import PostProcess
from backend.service.application.models.rfdetr_core.models.transformer import build_transformer
from backend.service.application.models.rfdetr_core.utilities.tensors import NestedTensor, nested_tensor_from_tensor_list


def _resize_linear(linear: nn.Linear, num_classes: int) -> nn.Linear:
    """执行 `_resize_linear`。
    
    参数：
    - `linear`：传入的 `linear` 参数。
    - `num_classes`：传入的 `num_classes` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    base = linear.weight.shape[0]
    num_repeats = int(math.ceil(num_classes / base))
    new_weight = linear.weight.detach().repeat(num_repeats, 1)[:num_classes]
    new_bias = linear.bias.detach().repeat(num_repeats)[:num_classes] if linear.bias is not None else None
    new_linear = nn.Linear(linear.in_features, num_classes, bias=new_bias is not None)
    with torch.no_grad():
        new_linear.weight.copy_(new_weight)
        if new_bias is not None and new_linear.bias is not None:
            new_linear.bias.copy_(new_bias)
    new_linear.weight.requires_grad = linear.weight.requires_grad
    if linear.bias is not None and new_linear.bias is not None:
        new_linear.bias.requires_grad = linear.bias.requires_grad
    return new_linear


class LWDETR(nn.Module):
    """RF-DETR core 类：`LWDETR`。"""

    def __init__(
        self,
        backbone,
        transformer,
        segmentation_head,
        num_classes,
        num_queries,
        aux_loss=False,
        group_detr=1,
        two_stage=False,
        lite_refpoint_refine=False,
        bbox_reparam=False,
    ):
        """执行 `__init__`。
        
        参数：
        - `backbone`：传入的 `backbone` 参数。
        - `transformer`：传入的 `transformer` 参数。
        - `segmentation_head`：传入的 `segmentation_head` 参数。
        - `num_classes`：传入的 `num_classes` 参数。
        - `num_queries`：传入的 `num_queries` 参数。
        - `aux_loss`：传入的 `aux_loss` 参数。
        - `group_detr`：传入的 `group_detr` 参数。
        - `two_stage`：传入的 `two_stage` 参数。
        - `lite_refpoint_refine`：传入的 `lite_refpoint_refine` 参数。
        - `bbox_reparam`：传入的 `bbox_reparam` 参数。
        """
        super().__init__()
        self.num_queries = num_queries
        self.transformer = transformer
        hidden_dim = transformer.d_model
        self.class_embed = nn.Linear(hidden_dim, num_classes)
        self.bbox_embed = MLP(hidden_dim, hidden_dim, 4, 3)
        self.segmentation_head = segmentation_head

        query_dim = 4
        self.refpoint_embed = nn.Embedding(num_queries * group_detr, query_dim)
        self.query_feat = nn.Embedding(num_queries * group_detr, hidden_dim)
        nn.init.constant_(self.refpoint_embed.weight.data, 0)

        self.backbone = backbone
        self.aux_loss = aux_loss
        self.group_detr = group_detr

        self.lite_refpoint_refine = lite_refpoint_refine
        if not self.lite_refpoint_refine:
            self.transformer.decoder.bbox_embed = self.bbox_embed
        else:
            self.transformer.decoder.bbox_embed = None

        self.bbox_reparam = bbox_reparam

        prior_prob = 0.01
        bias_value = -math.log((1 - prior_prob) / prior_prob)
        self.class_embed.bias.data = torch.ones(num_classes) * bias_value

        nn.init.constant_(self.bbox_embed.layers[-1].weight.data, 0)
        nn.init.constant_(self.bbox_embed.layers[-1].bias.data, 0)

        self.two_stage = two_stage
        if self.two_stage:
            self.transformer.enc_out_bbox_embed = nn.ModuleList(
                [copy.deepcopy(self.bbox_embed) for _ in range(group_detr)]
            )
            self.transformer.enc_out_class_embed = nn.ModuleList(
                [copy.deepcopy(self.class_embed) for _ in range(group_detr)]
            )

        self._export = False

    def reinitialize_detection_head(self, num_classes: int) -> None:
        """执行 `reinitialize_detection_head`。
        
        参数：
        - `num_classes`：传入的 `num_classes` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        self.class_embed = _resize_linear(self.class_embed, num_classes)

        if self.two_stage:
            self.transformer.enc_out_class_embed = nn.ModuleList(
                [_resize_linear(m, num_classes) for m in self.transformer.enc_out_class_embed]
            )

    def export(self):
        self._export = True
        self._forward_origin = self.forward
        self.forward = self.forward_export
        for name, m in self.named_modules():
            if hasattr(m, "export") and isinstance(m.export, Callable) and hasattr(m, "_export") and not m._export:
                m.export()

    def forward(self, samples: NestedTensor, targets=None):
        """执行 `forward`。
        
        参数：
        - `samples`：传入的 `samples` 参数。
        - `targets`：传入的 `targets` 参数。
        """
        if isinstance(samples, (list, torch.Tensor)):
            samples = nested_tensor_from_tensor_list(samples)
        features, poss = self.backbone(samples)

        srcs = []
        masks = []
        for feat in features:
            src, mask = feat.decompose()
            srcs.append(src)
            masks.append(mask)
            assert mask is not None

        if self.training:
            refpoint_embed_weight = self.refpoint_embed.weight
            query_feat_weight = self.query_feat.weight
        else:
            refpoint_embed_weight = self.refpoint_embed.weight[: self.num_queries]
            query_feat_weight = self.query_feat.weight[: self.num_queries]

        if self.segmentation_head is not None:
            seg_head_fwd = self.segmentation_head.sparse_forward if self.training else self.segmentation_head.forward

        hs, ref_unsigmoid, hs_enc, ref_enc = self.transformer(
            srcs, masks, poss, refpoint_embed_weight, query_feat_weight
        )

        if hs is not None:
            if self.bbox_reparam:
                outputs_coord_delta = self.bbox_embed(hs)
                outputs_coord_cxcy = outputs_coord_delta[..., :2] * ref_unsigmoid[..., 2:] + ref_unsigmoid[..., :2]
                outputs_coord_wh = outputs_coord_delta[..., 2:].exp() * ref_unsigmoid[..., 2:]
                outputs_coord = torch.concat([outputs_coord_cxcy, outputs_coord_wh], dim=-1)
            else:
                outputs_coord = (self.bbox_embed(hs) + ref_unsigmoid).sigmoid()

            outputs_class = self.class_embed(hs)

            if self.segmentation_head is not None:
                outputs_masks = seg_head_fwd(features[0].tensors, hs, samples.tensors.shape[-2:])

            out = {"pred_logits": outputs_class[-1], "pred_boxes": outputs_coord[-1]}
            if self.segmentation_head is not None:
                out["pred_masks"] = outputs_masks[-1]
            if self.aux_loss:
                out["aux_outputs"] = self._set_aux_loss(
                    outputs_class,
                    outputs_coord,
                    outputs_masks if self.segmentation_head is not None else None,
                )

        if self.two_stage:
            group_detr = self.group_detr if self.training else 1
            hs_enc_list = hs_enc.chunk(group_detr, dim=1)
            cls_enc = []
            for g_idx in range(group_detr):
                cls_enc_gidx = self.transformer.enc_out_class_embed[g_idx](hs_enc_list[g_idx])
                cls_enc.append(cls_enc_gidx)

            cls_enc = torch.cat(cls_enc, dim=1)

            if self.segmentation_head is not None:
                masks_enc = seg_head_fwd(
                    features[0].tensors,
                    [
                        hs_enc,
                    ],
                    samples.tensors.shape[-2:],
                    skip_blocks=True,
                )[0]

            if hs is not None:
                out["enc_outputs"] = {"pred_logits": cls_enc, "pred_boxes": ref_enc}
                if self.segmentation_head is not None:
                    out["enc_outputs"]["pred_masks"] = masks_enc
            else:
                out = {"pred_logits": cls_enc, "pred_boxes": ref_enc}
                if self.segmentation_head is not None:
                    out["pred_masks"] = masks_enc

        return out

    def forward_export(self, tensors):
        srcs, _, poss = self.backbone(tensors)
        refpoint_embed_weight = self.refpoint_embed.weight[: self.num_queries]
        query_feat_weight = self.query_feat.weight[: self.num_queries]

        hs, ref_unsigmoid, hs_enc, ref_enc = self.transformer(
            srcs, None, poss, refpoint_embed_weight, query_feat_weight
        )

        outputs_masks = None

        if hs is not None:
            if self.bbox_reparam:
                outputs_coord_delta = self.bbox_embed(hs)
                outputs_coord_cxcy = outputs_coord_delta[..., :2] * ref_unsigmoid[..., 2:] + ref_unsigmoid[..., :2]
                outputs_coord_wh = outputs_coord_delta[..., 2:].exp() * ref_unsigmoid[..., 2:]
                outputs_coord = torch.concat([outputs_coord_cxcy, outputs_coord_wh], dim=-1)
            else:
                outputs_coord = (self.bbox_embed(hs) + ref_unsigmoid).sigmoid()
            outputs_class = self.class_embed(hs)
            if self.segmentation_head is not None:
                outputs_masks = self.segmentation_head(
                    srcs[0],
                    [
                        hs,
                    ],
                    tensors.shape[-2:],
                )[0]
        else:
            assert self.two_stage, "if not using decoder, two_stage must be True"
            outputs_class = self.transformer.enc_out_class_embed[0](hs_enc)
            outputs_coord = ref_enc
            if self.segmentation_head is not None:
                outputs_masks = self.segmentation_head(
                    srcs[0],
                    [
                        hs_enc,
                    ],
                    tensors.shape[-2:],
                    skip_blocks=True,
                )[0]

        if outputs_masks is not None:
            return outputs_coord, outputs_class, outputs_masks
        else:
            return outputs_coord, outputs_class

    @torch.jit.unused
    def _set_aux_loss(self, outputs_class, outputs_coord, outputs_masks):
        if outputs_masks is not None:
            return [
                {"pred_logits": a, "pred_boxes": b, "pred_masks": c}
                for a, b, c in zip(outputs_class[:-1], outputs_coord[:-1], outputs_masks[:-1])
            ]
        else:
            return [{"pred_logits": a, "pred_boxes": b} for a, b in zip(outputs_class[:-1], outputs_coord[:-1])]

    def _get_backbone_encoder_layers(self) -> Optional[nn.ModuleList]:
        """执行 `_get_backbone_encoder_layers`。
        
        返回：
        - 当前函数的执行结果。
        """
        enc = self.backbone[0].encoder
        if hasattr(enc, "blocks"):
            return enc.blocks
        if hasattr(enc, "trunk") and hasattr(enc.trunk, "blocks"):
            return enc.trunk.blocks
        if hasattr(enc, "encoder") and hasattr(enc.encoder, "encoder") and hasattr(enc.encoder.encoder, "layer"):
            return enc.encoder.encoder.layer
        return None

    def update_drop_path(self, drop_path_rate: float, vit_encoder_num_layers: int) -> None:
        """执行 `update_drop_path`。
        
        参数：
        - `drop_path_rate`：传入的 `drop_path_rate` 参数。
        - `vit_encoder_num_layers`：传入的 `vit_encoder_num_layers` 参数。
        
        返回：
        - 当前函数的执行结果。
        """
        layers = self._get_backbone_encoder_layers()
        if layers is None:
            return
        n = min(vit_encoder_num_layers, len(layers))
        dp_rates = [x.item() for x in torch.linspace(0, drop_path_rate, n)]
        for i in range(n):
            if hasattr(layers[i], "drop_path") and hasattr(layers[i].drop_path, "drop_prob"):
                layers[i].drop_path.drop_prob = dp_rates[i]

    def update_dropout(self, drop_rate):
        for module in self.transformer.modules():
            if isinstance(module, nn.Dropout):
                module.p = drop_rate


def build_model(args: "BuilderArgs"):
    num_classes = args.num_classes + 1
    torch.device(args.device)

    backbone = build_backbone(
        encoder=args.encoder,
        vit_encoder_num_layers=args.vit_encoder_num_layers,
        pretrained_encoder=args.pretrained_encoder,
        window_block_indexes=args.window_block_indexes,
        drop_path=args.drop_path,
        out_channels=args.hidden_dim,
        out_feature_indexes=args.out_feature_indexes,
        projector_scale=args.projector_scale,
        use_cls_token=args.use_cls_token,
        hidden_dim=args.hidden_dim,
        position_embedding=args.position_embedding,
        freeze_encoder=args.freeze_encoder,
        layer_norm=args.layer_norm,
        target_shape=(
            args.shape
            if hasattr(args, "shape")
            else ((args.resolution, args.resolution) if hasattr(args, "resolution") else (640, 640))
        ),
        rms_norm=args.rms_norm,
        backbone_lora=args.backbone_lora,
        force_no_pretrain=args.force_no_pretrain,
        gradient_checkpointing=args.gradient_checkpointing,
        load_dinov2_weights=(args.pretrain_weights is None and not args.force_no_pretrain),
        patch_size=args.patch_size,
        num_windows=args.num_windows,
        positional_encoding_size=args.positional_encoding_size,
    )
    if args.encoder_only:
        return backbone[0].encoder, None, None
    if args.backbone_only:
        return backbone, None, None

    args.num_feature_levels = len(args.projector_scale)
    transformer = build_transformer(args)

    segmentation_head = (
        SegmentationHead(
            args.hidden_dim,
            args.dec_layers,
            downsample_ratio=args.mask_downsample_ratio,
        )
        if args.segmentation_head
        else None
    )

    model = LWDETR(
        backbone,
        transformer,
        segmentation_head,
        num_classes=num_classes,
        num_queries=args.num_queries,
        aux_loss=args.aux_loss,
        group_detr=args.group_detr,
        two_stage=args.two_stage,
        lite_refpoint_refine=args.lite_refpoint_refine,
        bbox_reparam=args.bbox_reparam,
    )
    return model


def build_criterion_and_postprocessors(args: "BuilderArgs"):
    device = torch.device(args.device)
    matcher = build_matcher(args)
    weight_dict = {"loss_ce": args.cls_loss_coef, "loss_bbox": args.bbox_loss_coef}
    weight_dict["loss_giou"] = args.giou_loss_coef
    if args.segmentation_head:
        weight_dict["loss_mask_ce"] = args.mask_ce_loss_coef
        weight_dict["loss_mask_dice"] = args.mask_dice_loss_coef
    if args.aux_loss:
        aux_weight_dict = {}
        for i in range(args.dec_layers - 1):
            aux_weight_dict.update({k + f"_{i}": v for k, v in weight_dict.items()})
        if args.two_stage:
            aux_weight_dict.update({k + "_enc": v for k, v in weight_dict.items()})
        weight_dict.update(aux_weight_dict)

    losses = ["labels", "boxes", "cardinality"]
    if args.segmentation_head:
        losses.append("masks")

    sum_group_losses = getattr(args, "sum_group_losses", False)
    if args.segmentation_head:
        criterion = SetCriterion(
            args.num_classes + 1,
            matcher=matcher,
            weight_dict=weight_dict,
            focal_alpha=args.focal_alpha,
            losses=losses,
            group_detr=args.group_detr,
            sum_group_losses=sum_group_losses,
            use_varifocal_loss=args.use_varifocal_loss,
            use_position_supervised_loss=args.use_position_supervised_loss,
            ia_bce_loss=args.ia_bce_loss,
            mask_point_sample_ratio=args.mask_point_sample_ratio,
        )
    else:
        criterion = SetCriterion(
            args.num_classes + 1,
            matcher=matcher,
            weight_dict=weight_dict,
            focal_alpha=args.focal_alpha,
            losses=losses,
            group_detr=args.group_detr,
            sum_group_losses=sum_group_losses,
            use_varifocal_loss=args.use_varifocal_loss,
            use_position_supervised_loss=args.use_position_supervised_loss,
            ia_bce_loss=args.ia_bce_loss,
        )
    criterion.to(device)
    postprocess = PostProcess(num_select=args.num_select)

    return criterion, postprocess


def build_model_from_config(
    model_config: "ModelConfig",
    train_config: Optional["TrainConfig"] = None,
    defaults: ModelDefaults = MODEL_DEFAULTS,
) -> LWDETR:
    """执行 `build_model_from_config`。
    
    参数：
    - `model_config`：传入的 `model_config` 参数。
    - `train_config`：传入的 `train_config` 参数。
    - `defaults`：传入的 `defaults` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    from backend.service.application.models.rfdetr_core._namespace import (
        _namespace_from_configs,
    )

    if defaults.encoder_only or defaults.backbone_only:
        raise ValueError(
            "build_model_from_config() requires defaults.encoder_only=False and defaults.backbone_only=False."
        )

    if train_config is None:
        from backend.service.application.models.rfdetr_core.config import TrainConfig

        train_config = TrainConfig(dataset_dir=".", output_dir=".")

    ns = _namespace_from_configs(model_config, train_config, defaults)
    return build_model(ns)


def build_criterion_from_config(
    model_config: "ModelConfig",
    train_config: "TrainConfig",
    defaults: ModelDefaults = MODEL_DEFAULTS,
) -> tuple[SetCriterion, PostProcess]:
    """执行 `build_criterion_from_config`。
    
    参数：
    - `model_config`：传入的 `model_config` 参数。
    - `train_config`：传入的 `train_config` 参数。
    - `defaults`：传入的 `defaults` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    from backend.service.application.models.rfdetr_core._namespace import (
        _namespace_from_configs,
    )

    ns = _namespace_from_configs(model_config, train_config, defaults)
    return build_criterion_and_postprocessors(ns)
