"""RF-DETR core 模型结构模块：`models.criterion`。"""

import torch
import torch.nn.functional as F  # noqa: N812
from torch import nn

from backend.service.application.models.rfdetr_core.models.heads.segmentation import (
    calculate_uncertainty,
    get_uncertain_point_coords_with_randomness,
    point_sample,
)
from backend.service.application.models.rfdetr_core.models.math import accuracy
from backend.service.application.models.rfdetr_core.utilities import box_ops
from backend.service.application.models.rfdetr_core.utilities.distributed import get_world_size, is_dist_avail_and_initialized


def sigmoid_focal_loss(inputs, targets, num_boxes, alpha: float = 0.25, gamma: float = 2):
    """执行 `sigmoid_focal_loss`。
    
    参数：
    - `inputs`：传入的 `inputs` 参数。
    - `targets`：传入的 `targets` 参数。
    - `num_boxes`：传入的 `num_boxes` 参数。
    - `alpha`：传入的 `alpha` 参数。
    - `gamma`：传入的 `gamma` 参数。
    """
    prob = inputs.sigmoid()
    ce_loss = F.binary_cross_entropy_with_logits(inputs, targets, reduction="none")
    p_t = prob * targets + (1 - prob) * (1 - targets)
    loss = ce_loss * ((1 - p_t) ** gamma)

    if alpha >= 0:
        alpha_t = alpha * targets + (1 - alpha) * (1 - targets)
        loss = alpha_t * loss

    return loss.mean(1).sum() / num_boxes


def sigmoid_varifocal_loss(inputs, targets, num_boxes, alpha: float = 0.25, gamma: float = 2):
    prob = inputs.sigmoid()
    focal_weight = (
        targets * (targets > 0.0).float() + (1 - alpha) * (prob - targets).abs().pow(gamma) * (targets <= 0.0).float()
    )
    ce_loss = F.binary_cross_entropy_with_logits(inputs, targets, reduction="none")
    loss = ce_loss * focal_weight

    return loss.mean(1).sum() / num_boxes


def position_supervised_loss(inputs, targets, num_boxes, alpha: float = 0.25, gamma: float = 2):
    prob = inputs.sigmoid()
    ce_loss = F.binary_cross_entropy_with_logits(inputs, targets, reduction="none")
    loss = ce_loss * (torch.abs(targets - prob) ** gamma)

    if alpha >= 0:
        alpha_t = alpha * (targets > 0.0).float() + (1 - alpha) * (targets <= 0.0).float()
        loss = alpha_t * loss

    return loss.mean(1).sum() / num_boxes


def dice_loss(
    inputs: torch.Tensor,
    targets: torch.Tensor,
    num_masks: float,
):
    """执行 `dice_loss`。
    
    参数：
    - `inputs`：传入的 `inputs` 参数。
    - `targets`：传入的 `targets` 参数。
    - `num_masks`：传入的 `num_masks` 参数。
    """
    inputs = inputs.sigmoid()
    inputs = inputs.flatten(1)
    numerator = 2 * (inputs * targets).sum(-1)
    denominator = inputs.sum(-1) + targets.sum(-1)
    loss = 1 - (numerator + 1) / (denominator + 1)
    return loss.sum() / num_masks


dice_loss_jit = torch.jit.script(dice_loss)  # type: torch.jit.ScriptModule


def sigmoid_ce_loss(
    inputs: torch.Tensor,
    targets: torch.Tensor,
    num_masks: float,
):
    """执行 `sigmoid_ce_loss`。
    
    参数：
    - `inputs`：传入的 `inputs` 参数。
    - `targets`：传入的 `targets` 参数。
    - `num_masks`：传入的 `num_masks` 参数。
    """
    loss = F.binary_cross_entropy_with_logits(inputs, targets, reduction="none")

    return loss.mean(1).sum() / num_masks


sigmoid_ce_loss_jit = torch.jit.script(sigmoid_ce_loss)  # type: torch.jit.ScriptModule


class SetCriterion(nn.Module):
    """RF-DETR core 类：`SetCriterion`。"""

    def __init__(
        self,
        num_classes,
        matcher,
        weight_dict,
        focal_alpha,
        losses,
        group_detr=1,
        sum_group_losses=False,
        use_varifocal_loss=False,
        use_position_supervised_loss=False,
        ia_bce_loss=False,
        mask_point_sample_ratio: int = 16,
    ):
        """执行 `__init__`。
        
        参数：
        - `num_classes`：传入的 `num_classes` 参数。
        - `matcher`：传入的 `matcher` 参数。
        - `weight_dict`：传入的 `weight_dict` 参数。
        - `focal_alpha`：传入的 `focal_alpha` 参数。
        - `losses`：传入的 `losses` 参数。
        - `group_detr`：传入的 `group_detr` 参数。
        - `sum_group_losses`：传入的 `sum_group_losses` 参数。
        - `use_varifocal_loss`：传入的 `use_varifocal_loss` 参数。
        - `use_position_supervised_loss`：传入的 `use_position_supervised_loss` 参数。
        - `ia_bce_loss`：传入的 `ia_bce_loss` 参数。
        - `mask_point_sample_ratio`：传入的 `mask_point_sample_ratio` 参数。
        """
        super().__init__()
        self.num_classes = num_classes
        self.matcher = matcher
        self.weight_dict = weight_dict
        self.losses = losses
        self.focal_alpha = focal_alpha
        self.group_detr = group_detr
        self.sum_group_losses = sum_group_losses
        self.use_varifocal_loss = use_varifocal_loss
        self.use_position_supervised_loss = use_position_supervised_loss
        self.ia_bce_loss = ia_bce_loss
        self.mask_point_sample_ratio = mask_point_sample_ratio

    def loss_labels(self, outputs, targets, indices, num_boxes, log=True):
        """执行 `loss_labels`。
        
        参数：
        - `outputs`：传入的 `outputs` 参数。
        - `targets`：传入的 `targets` 参数。
        - `indices`：传入的 `indices` 参数。
        - `num_boxes`：传入的 `num_boxes` 参数。
        - `log`：传入的 `log` 参数。
        """
        assert "pred_logits" in outputs
        src_logits = outputs["pred_logits"]

        idx = self._get_src_permutation_idx(indices)
        target_classes_o = torch.cat([t["labels"][J] for t, (_, J) in zip(targets, indices)])

        if self.ia_bce_loss:
            alpha = self.focal_alpha
            gamma = 2
            src_boxes = outputs["pred_boxes"][idx]
            target_boxes = torch.cat([t["boxes"][i] for t, (_, i) in zip(targets, indices)], dim=0)

            iou_targets = torch.diag(
                box_ops.box_iou(
                    box_ops.box_cxcywh_to_xyxy(src_boxes.detach()),
                    box_ops.box_cxcywh_to_xyxy(target_boxes),
                )[0]
            )
            pos_ious = iou_targets.clone().detach()
            prob = src_logits.sigmoid()
            pos_weights = torch.zeros_like(src_logits)
            neg_weights = prob**gamma

            pos_ind = [id for id in idx]
            pos_ind.append(target_classes_o)

            t = prob[tuple(pos_ind)].pow(alpha) * pos_ious.pow(1 - alpha)
            t = torch.clamp(t, 0.01).detach()

            pos_weights[tuple(pos_ind)] = t.to(pos_weights.dtype)
            neg_weights[tuple(pos_ind)] = 1 - t.to(neg_weights.dtype)
            loss_ce = neg_weights * src_logits - F.logsigmoid(src_logits) * (pos_weights + neg_weights)
            loss_ce = loss_ce.sum() / num_boxes

        elif self.use_position_supervised_loss:
            src_boxes = outputs["pred_boxes"][idx]
            target_boxes = torch.cat([t["boxes"][i] for t, (_, i) in zip(targets, indices)], dim=0)

            iou_targets = torch.diag(
                box_ops.box_iou(
                    box_ops.box_cxcywh_to_xyxy(src_boxes.detach()),
                    box_ops.box_cxcywh_to_xyxy(target_boxes),
                )[0]
            )
            pos_ious = iou_targets.clone().detach()
            pos_ious_func = pos_ious

            cls_iou_func_targets = torch.zeros(
                (src_logits.shape[0], src_logits.shape[1], self.num_classes),
                dtype=src_logits.dtype,
                device=src_logits.device,
            )

            pos_ind = [id for id in idx]
            pos_ind.append(target_classes_o)
            pos_ious_func = pos_ious_func.to(cls_iou_func_targets.dtype)
            cls_iou_func_targets[tuple(pos_ind)] = pos_ious_func
            norm_cls_iou_func_targets = cls_iou_func_targets / (
                cls_iou_func_targets.view(cls_iou_func_targets.shape[0], -1, 1).amax(1, True) + 1e-8
            )
            loss_ce = (
                position_supervised_loss(
                    src_logits,
                    norm_cls_iou_func_targets,
                    num_boxes,
                    alpha=self.focal_alpha,
                    gamma=2,
                )
                * src_logits.shape[1]
            )

        elif self.use_varifocal_loss:
            src_boxes = outputs["pred_boxes"][idx]
            target_boxes = torch.cat([t["boxes"][i] for t, (_, i) in zip(targets, indices)], dim=0)

            iou_targets = torch.diag(
                box_ops.box_iou(
                    box_ops.box_cxcywh_to_xyxy(src_boxes.detach()),
                    box_ops.box_cxcywh_to_xyxy(target_boxes),
                )[0]
            )
            pos_ious = iou_targets.clone().detach()

            cls_iou_targets = torch.zeros(
                (src_logits.shape[0], src_logits.shape[1], self.num_classes),
                dtype=src_logits.dtype,
                device=src_logits.device,
            )

            pos_ind = [id for id in idx]
            pos_ind.append(target_classes_o)
            cls_iou_targets[tuple(pos_ind)] = pos_ious
            loss_ce = (
                sigmoid_varifocal_loss(
                    src_logits,
                    cls_iou_targets,
                    num_boxes,
                    alpha=self.focal_alpha,
                    gamma=2,
                )
                * src_logits.shape[1]
            )
        else:
            target_classes = torch.full(
                src_logits.shape[:2],
                self.num_classes,
                dtype=torch.int64,
                device=src_logits.device,
            )
            target_classes[idx] = target_classes_o

            target_classes_onehot = torch.zeros(
                [src_logits.shape[0], src_logits.shape[1], src_logits.shape[2] + 1],
                dtype=src_logits.dtype,
                layout=src_logits.layout,
                device=src_logits.device,
            )
            target_classes_onehot.scatter_(2, target_classes.unsqueeze(-1), 1)

            target_classes_onehot = target_classes_onehot[:, :, :-1]
            loss_ce = (
                sigmoid_focal_loss(
                    src_logits,
                    target_classes_onehot,
                    num_boxes,
                    alpha=self.focal_alpha,
                    gamma=2,
                )
                * src_logits.shape[1]
            )
        losses = {"loss_ce": loss_ce}

        if log:
            losses["class_error"] = 100 - accuracy(src_logits[idx], target_classes_o)[0]
        return losses

    @torch.no_grad()
    def loss_cardinality(self, outputs, targets, indices, num_boxes):
        """执行 `loss_cardinality`。
        
        参数：
        - `outputs`：传入的 `outputs` 参数。
        - `targets`：传入的 `targets` 参数。
        - `indices`：传入的 `indices` 参数。
        - `num_boxes`：传入的 `num_boxes` 参数。
        """
        pred_logits = outputs["pred_logits"]
        device = pred_logits.device
        tgt_lengths = torch.as_tensor([len(v["labels"]) for v in targets], device=device)
        card_pred = (pred_logits.argmax(-1) != pred_logits.shape[-1] - 1).sum(1)
        card_err = F.l1_loss(card_pred.float(), tgt_lengths.float())
        losses = {"cardinality_error": card_err}
        return losses

    def loss_boxes(self, outputs, targets, indices, num_boxes):
        """执行 `loss_boxes`。
        
        参数：
        - `outputs`：传入的 `outputs` 参数。
        - `targets`：传入的 `targets` 参数。
        - `indices`：传入的 `indices` 参数。
        - `num_boxes`：传入的 `num_boxes` 参数。
        """
        assert "pred_boxes" in outputs
        idx = self._get_src_permutation_idx(indices)
        src_boxes = outputs["pred_boxes"][idx]
        target_boxes = torch.cat([t["boxes"][i] for t, (_, i) in zip(targets, indices)], dim=0)

        loss_bbox = F.l1_loss(src_boxes, target_boxes, reduction="none")

        losses = {}
        losses["loss_bbox"] = loss_bbox.sum() / num_boxes

        loss_giou = 1 - torch.diag(
            box_ops.generalized_box_iou(
                box_ops.box_cxcywh_to_xyxy(src_boxes),
                box_ops.box_cxcywh_to_xyxy(target_boxes),
            )
        )
        losses["loss_giou"] = loss_giou.sum() / num_boxes
        return losses

    def loss_masks(self, outputs, targets, indices, num_boxes):
        """执行 `loss_masks`。
        
        参数：
        - `outputs`：传入的 `outputs` 参数。
        - `targets`：传入的 `targets` 参数。
        - `indices`：传入的 `indices` 参数。
        - `num_boxes`：传入的 `num_boxes` 参数。
        """
        assert "pred_masks" in outputs, "pred_masks missing in model outputs"
        idx = self._get_src_permutation_idx(indices)
        pred_masks = outputs["pred_masks"]

        if isinstance(pred_masks, torch.Tensor):
            src_masks = pred_masks[idx]
        else:
            spatial_features = outputs["pred_masks"]["spatial_features"]
            query_features = outputs["pred_masks"]["query_features"]
            bias = outputs["pred_masks"]["bias"]
            if idx[0].numel() == 0:
                device = spatial_features.device
                src_masks = torch.tensor([], device=device)
            else:
                batched_selected_masks = []
                per_batch_counts = idx[0].unique(return_counts=True)[1]
                batch_indices = torch.cat((torch.zeros_like(per_batch_counts[:1]), per_batch_counts), dim=0).cumsum(0)

                for i in range(per_batch_counts.shape[0]):
                    batch_indicator = idx[0][batch_indices[i] : batch_indices[i + 1]]
                    box_indicator = idx[1][batch_indices[i] : batch_indices[i + 1]]

                    this_batch_queries = query_features[(batch_indicator, box_indicator)]
                    this_batch_spatial_features = spatial_features[idx[0][batch_indices[i + 1] - 1]]

                    this_batch_masks = (
                        torch.einsum(
                            "chw,nc->nhw",
                            this_batch_spatial_features,
                            this_batch_queries,
                        )
                        + bias
                    )

                    batched_selected_masks.append(this_batch_masks)

                src_masks = torch.cat(batched_selected_masks)

        if src_masks.numel() == 0:
            return {
                "loss_mask_ce": src_masks.sum(),
                "loss_mask_dice": src_masks.sum(),
            }
        target_masks = torch.cat([t["masks"][j] for t, (_, j) in zip(targets, indices)], dim=0)

        src_masks = src_masks.unsqueeze(1)
        target_masks = target_masks.unsqueeze(1).float()

        num_points = max(
            src_masks.shape[-2],
            src_masks.shape[-2] * src_masks.shape[-1] // self.mask_point_sample_ratio,
        )

        with torch.no_grad():
            point_coords = get_uncertain_point_coords_with_randomness(
                src_masks,
                lambda logits: calculate_uncertainty(logits),
                num_points,
                3,
                0.75,
            )

        point_logits = point_sample(
            src_masks,
            point_coords,
            align_corners=False,
        ).squeeze(1)

        with torch.no_grad():
            point_labels = point_sample(
                target_masks,
                point_coords,
                align_corners=False,
                mode="nearest",
            ).squeeze(1)

        losses = {
            "loss_mask_ce": sigmoid_ce_loss_jit(point_logits, point_labels, num_boxes),
            "loss_mask_dice": dice_loss_jit(point_logits, point_labels, num_boxes),
        }

        del src_masks
        del target_masks
        return losses

    def _get_src_permutation_idx(self, indices):
        batch_idx = torch.cat([torch.full_like(src, i) for i, (src, _) in enumerate(indices)])
        src_idx = torch.cat([src for (src, _) in indices])
        return batch_idx, src_idx

    def _get_tgt_permutation_idx(self, indices):
        batch_idx = torch.cat([torch.full_like(tgt, i) for i, (_, tgt) in enumerate(indices)])
        tgt_idx = torch.cat([tgt for (_, tgt) in indices])
        return batch_idx, tgt_idx

    def get_loss(self, loss, outputs, targets, indices, num_boxes, **kwargs):
        loss_map = {
            "labels": self.loss_labels,
            "cardinality": self.loss_cardinality,
            "boxes": self.loss_boxes,
            "masks": self.loss_masks,
        }
        assert loss in loss_map, f"do you really want to compute {loss} loss?"
        return loss_map[loss](outputs, targets, indices, num_boxes, **kwargs)

    def forward(self, outputs, targets):
        """执行 `forward`。
        
        参数：
        - `outputs`：传入的 `outputs` 参数。
        - `targets`：传入的 `targets` 参数。
        """
        group_detr = self.group_detr if self.training else 1
        outputs_without_aux = {k: v for k, v in outputs.items() if k != "aux_outputs"}

        indices = self.matcher(outputs_without_aux, targets, group_detr=group_detr)

        num_boxes = sum(len(t["labels"]) for t in targets)
        if not self.sum_group_losses:
            num_boxes = num_boxes * group_detr
        num_boxes = torch.as_tensor([num_boxes], dtype=torch.float, device=next(iter(outputs.values())).device)
        if is_dist_avail_and_initialized():
            torch.distributed.all_reduce(num_boxes)
        num_boxes = torch.clamp(num_boxes / get_world_size(), min=1).item()

        losses = {}
        for loss in self.losses:
            losses.update(self.get_loss(loss, outputs, targets, indices, num_boxes))

        if "aux_outputs" in outputs:
            for i, aux_outputs in enumerate(outputs["aux_outputs"]):
                indices = self.matcher(aux_outputs, targets, group_detr=group_detr)
                for loss in self.losses:
                    kwargs = {}
                    if loss == "labels":
                        kwargs = {"log": False}
                    l_dict = self.get_loss(loss, aux_outputs, targets, indices, num_boxes, **kwargs)
                    l_dict = {k + f"_{i}": v for k, v in l_dict.items()}
                    losses.update(l_dict)

        if "enc_outputs" in outputs:
            enc_outputs = outputs["enc_outputs"]
            indices = self.matcher(enc_outputs, targets, group_detr=group_detr)
            for loss in self.losses:
                kwargs = {}
                if loss == "labels":
                    kwargs["log"] = False
                l_dict = self.get_loss(loss, enc_outputs, targets, indices, num_boxes, **kwargs)
                l_dict = {k + "_enc": v for k, v in l_dict.items()}
                losses.update(l_dict)

        return losses
