"""项目内 YOLOX detection head 实现。"""

from __future__ import annotations

import logging
import math

import torch
import torch.nn as nn
import torch.nn.functional as F

from ..utils import bboxes_iou, cxcywh2xyxy, meshgrid, visualize_assign
from .losses import IOUloss
from .network_blocks import BaseConv, DWConv


LOGGER = logging.getLogger(__name__)


class YOLOXHead(nn.Module):
    """实现与原 YOLOX 兼容的解耦检测头。"""

    def __init__(
        self,
        num_classes: int,
        width: float = 1.0,
        strides: list[int] | tuple[int, int, int] = (8, 16, 32),
        in_channels: list[int] | tuple[int, int, int] = (256, 512, 1024),
        act: str = "silu",
        depthwise: bool = False,
    ) -> None:
        """初始化 YOLOXHead。"""

        super().__init__()
        self.num_classes = num_classes
        self.decode_in_inference = True
        self.cls_convs = nn.ModuleList()
        self.reg_convs = nn.ModuleList()
        self.cls_preds = nn.ModuleList()
        self.reg_preds = nn.ModuleList()
        self.obj_preds = nn.ModuleList()
        self.stems = nn.ModuleList()
        conv_type = DWConv if depthwise else BaseConv

        for in_channel in in_channels:
            self.stems.append(
                BaseConv(
                    in_channels=int(in_channel * width),
                    out_channels=int(256 * width),
                    ksize=1,
                    stride=1,
                    act=act,
                )
            )
            self.cls_convs.append(
                nn.Sequential(
                    conv_type(int(256 * width), int(256 * width), 3, 1, act=act),
                    conv_type(int(256 * width), int(256 * width), 3, 1, act=act),
                )
            )
            self.reg_convs.append(
                nn.Sequential(
                    conv_type(int(256 * width), int(256 * width), 3, 1, act=act),
                    conv_type(int(256 * width), int(256 * width), 3, 1, act=act),
                )
            )
            self.cls_preds.append(
                nn.Conv2d(int(256 * width), self.num_classes, kernel_size=1, stride=1, padding=0)
            )
            self.reg_preds.append(
                nn.Conv2d(int(256 * width), 4, kernel_size=1, stride=1, padding=0)
            )
            self.obj_preds.append(
                nn.Conv2d(int(256 * width), 1, kernel_size=1, stride=1, padding=0)
            )

        self.use_l1 = False
        self.l1_loss = nn.L1Loss(reduction="none")
        self.bcewithlog_loss = nn.BCEWithLogitsLoss(reduction="none")
        self.iou_loss = IOUloss(reduction="none")
        self.strides = list(strides)
        self.grids = [torch.zeros(1)] * len(in_channels)

    def initialize_biases(self, prior_prob: float) -> None:
        """按原 YOLOX 方式初始化分类和目标置信度偏置。"""

        bias_value = -math.log((1 - prior_prob) / prior_prob)
        for conv in self.cls_preds:
            bias = conv.bias.view(1, -1)
            bias.data.fill_(bias_value)
            conv.bias = torch.nn.Parameter(bias.view(-1), requires_grad=True)
        for conv in self.obj_preds:
            bias = conv.bias.view(1, -1)
            bias.data.fill_(bias_value)
            conv.bias = torch.nn.Parameter(bias.view(-1), requires_grad=True)

    def forward(self, xin, labels=None, imgs=None):
        """执行 head 前向；训练态返回损失，推理态返回解码后的预测。"""

        outputs = []
        origin_preds = []
        x_shifts = []
        y_shifts = []
        expanded_strides = []

        for level_index, (cls_conv, reg_conv, stride_this_level, x) in enumerate(
            zip(self.cls_convs, self.reg_convs, self.strides, xin)
        ):
            x = self.stems[level_index](x)
            cls_feat = cls_conv(x)
            cls_output = self.cls_preds[level_index](cls_feat)

            reg_feat = reg_conv(x)
            reg_output = self.reg_preds[level_index](reg_feat)
            obj_output = self.obj_preds[level_index](reg_feat)

            if self.training:
                output = torch.cat([reg_output, obj_output, cls_output], 1)
                output, grid = self.get_output_and_grid(
                    output,
                    level_index,
                    stride_this_level,
                    xin[0].type(),
                )
                x_shifts.append(grid[:, :, 0])
                y_shifts.append(grid[:, :, 1])
                expanded_strides.append(
                    torch.zeros(1, grid.shape[1]).fill_(stride_this_level).type_as(xin[0])
                )
                if self.use_l1:
                    batch_size = reg_output.shape[0]
                    height_size, width_size = reg_output.shape[-2:]
                    reg_output = reg_output.view(batch_size, 1, 4, height_size, width_size)
                    reg_output = reg_output.permute(0, 1, 3, 4, 2).reshape(batch_size, -1, 4)
                    origin_preds.append(reg_output.clone())
            else:
                output = torch.cat([reg_output, obj_output.sigmoid(), cls_output.sigmoid()], 1)

            outputs.append(output)

        if self.training:
            return self.get_losses(
                imgs,
                x_shifts,
                y_shifts,
                expanded_strides,
                labels,
                torch.cat(outputs, 1),
                origin_preds,
                dtype=xin[0].dtype,
            )

        self.hw = [output.shape[-2:] for output in outputs]
        outputs = torch.cat([output.flatten(start_dim=2) for output in outputs], dim=2).permute(0, 2, 1)
        if self.decode_in_inference:
            return self.decode_outputs(outputs, dtype=xin[0].type())
        return outputs

    def get_output_and_grid(self, output, level_index: int, stride: int, dtype):
        """把原始卷积输出重排为 YOLOX 训练使用的网格表示。"""

        grid = self.grids[level_index]
        batch_size = output.shape[0]
        output_channels = 5 + self.num_classes
        height_size, width_size = output.shape[-2:]
        if grid.shape[2:4] != output.shape[2:4]:
            yv, xv = meshgrid([torch.arange(height_size), torch.arange(width_size)])
            grid = torch.stack((xv, yv), 2).view(1, 1, height_size, width_size, 2).type(dtype)
            self.grids[level_index] = grid

        output = output.view(batch_size, 1, output_channels, height_size, width_size)
        output = output.permute(0, 1, 3, 4, 2).reshape(batch_size, height_size * width_size, -1)
        grid = grid.view(1, -1, 2)
        output[..., :2] = (output[..., :2] + grid) * stride
        output[..., 2:4] = torch.exp(output[..., 2:4]) * stride
        return output, grid

    def decode_outputs(self, outputs, dtype):
        """把推理态输出解码到像素坐标空间。"""

        grids = []
        strides = []
        for (height_size, width_size), stride in zip(self.hw, self.strides):
            yv, xv = meshgrid([torch.arange(height_size), torch.arange(width_size)])
            grid = torch.stack((xv, yv), 2).view(1, -1, 2)
            grids.append(grid)
            shape = grid.shape[:2]
            strides.append(torch.full((*shape, 1), stride))

        grids = torch.cat(grids, dim=1).type(dtype)
        strides = torch.cat(strides, dim=1).type(dtype)
        return torch.cat(
            [
                (outputs[..., 0:2] + grids) * strides,
                torch.exp(outputs[..., 2:4]) * strides,
                outputs[..., 4:],
            ],
            dim=-1,
        )

    def get_losses(
        self,
        imgs,
        x_shifts,
        y_shifts,
        expanded_strides,
        labels,
        outputs,
        origin_preds,
        dtype,
    ):
        """计算 YOLOX detection 训练损失。"""

        bbox_preds = outputs[:, :, :4]
        obj_preds = outputs[:, :, 4:5]
        cls_preds = outputs[:, :, 5:]
        label_counts = (labels.sum(dim=2) > 0).sum(dim=1)

        total_num_anchors = outputs.shape[1]
        x_shifts = torch.cat(x_shifts, 1)
        y_shifts = torch.cat(y_shifts, 1)
        expanded_strides = torch.cat(expanded_strides, 1)
        if self.use_l1:
            origin_preds = torch.cat(origin_preds, 1)

        cls_targets = []
        reg_targets = []
        l1_targets = []
        obj_targets = []
        fg_masks = []
        num_fg = 0.0
        num_gts = 0.0

        for batch_index in range(outputs.shape[0]):
            num_gt = int(label_counts[batch_index])
            num_gts += num_gt
            if num_gt == 0:
                cls_target = outputs.new_zeros((0, self.num_classes))
                reg_target = outputs.new_zeros((0, 4))
                l1_target = outputs.new_zeros((0, 4))
                obj_target = outputs.new_zeros((total_num_anchors, 1))
                fg_mask = outputs.new_zeros(total_num_anchors).bool()
            else:
                gt_bboxes_per_image = labels[batch_index, :num_gt, 1:5]
                gt_classes = labels[batch_index, :num_gt, 0]
                bboxes_preds_per_image = bbox_preds[batch_index]

                try:
                    (
                        gt_matched_classes,
                        fg_mask,
                        pred_ious_this_matching,
                        matched_gt_inds,
                        num_fg_img,
                    ) = self.get_assignments(
                        batch_index,
                        num_gt,
                        gt_bboxes_per_image,
                        gt_classes,
                        bboxes_preds_per_image,
                        expanded_strides,
                        x_shifts,
                        y_shifts,
                        cls_preds,
                        obj_preds,
                    )
                except RuntimeError as error:
                    if "CUDA out of memory." not in str(error):
                        raise
                    LOGGER.warning(
                        "标签分配阶段发生 CUDA OOM，当前 batch 回退到 CPU 分配。"
                    )
                    torch.cuda.empty_cache()
                    (
                        gt_matched_classes,
                        fg_mask,
                        pred_ious_this_matching,
                        matched_gt_inds,
                        num_fg_img,
                    ) = self.get_assignments(
                        batch_index,
                        num_gt,
                        gt_bboxes_per_image,
                        gt_classes,
                        bboxes_preds_per_image,
                        expanded_strides,
                        x_shifts,
                        y_shifts,
                        cls_preds,
                        obj_preds,
                        mode="cpu",
                    )

                torch.cuda.empty_cache()
                num_fg += num_fg_img
                cls_target = F.one_hot(gt_matched_classes.to(torch.int64), self.num_classes) * pred_ious_this_matching.unsqueeze(-1)
                obj_target = fg_mask.unsqueeze(-1)
                reg_target = gt_bboxes_per_image[matched_gt_inds]
                if self.use_l1:
                    l1_target = self.get_l1_target(
                        outputs.new_zeros((num_fg_img, 4)),
                        gt_bboxes_per_image[matched_gt_inds],
                        expanded_strides[0][fg_mask],
                        x_shifts=x_shifts[0][fg_mask],
                        y_shifts=y_shifts[0][fg_mask],
                    )

            cls_targets.append(cls_target)
            reg_targets.append(reg_target)
            obj_targets.append(obj_target.to(dtype))
            fg_masks.append(fg_mask)
            if self.use_l1:
                l1_targets.append(l1_target)

        cls_targets = torch.cat(cls_targets, 0)
        reg_targets = torch.cat(reg_targets, 0)
        obj_targets = torch.cat(obj_targets, 0)
        fg_masks = torch.cat(fg_masks, 0)
        if self.use_l1:
            l1_targets = torch.cat(l1_targets, 0)

        num_fg = max(num_fg, 1)
        loss_iou = self.iou_loss(bbox_preds.view(-1, 4)[fg_masks], reg_targets).sum() / num_fg
        loss_obj = self.bcewithlog_loss(obj_preds.view(-1, 1), obj_targets).sum() / num_fg
        loss_cls = self.bcewithlog_loss(
            cls_preds.view(-1, self.num_classes)[fg_masks],
            cls_targets,
        ).sum() / num_fg
        if self.use_l1:
            loss_l1 = self.l1_loss(origin_preds.view(-1, 4)[fg_masks], l1_targets).sum() / num_fg
        else:
            loss_l1 = 0.0

        reg_weight = 5.0
        total_loss = reg_weight * loss_iou + loss_obj + loss_cls + loss_l1
        return total_loss, reg_weight * loss_iou, loss_obj, loss_cls, loss_l1, num_fg / max(num_gts, 1)

    def get_l1_target(self, l1_target, gt, stride, x_shifts, y_shifts, eps: float = 1e-8):
        """构造 L1 辅助监督目标。"""

        l1_target[:, 0] = gt[:, 0] / stride - x_shifts
        l1_target[:, 1] = gt[:, 1] / stride - y_shifts
        l1_target[:, 2] = torch.log(gt[:, 2] / stride + eps)
        l1_target[:, 3] = torch.log(gt[:, 3] / stride + eps)
        return l1_target

    @torch.no_grad()
    def get_assignments(
        self,
        batch_idx,
        num_gt,
        gt_bboxes_per_image,
        gt_classes,
        bboxes_preds_per_image,
        expanded_strides,
        x_shifts,
        y_shifts,
        cls_preds,
        obj_preds,
        mode: str = "gpu",
    ):
        """执行 YOLOX SimOTA 标签分配。"""

        target_device = gt_bboxes_per_image.device
        if mode == "cpu":
            gt_bboxes_per_image = gt_bboxes_per_image.cpu().float()
            bboxes_preds_per_image = bboxes_preds_per_image.cpu().float()
            gt_classes = gt_classes.cpu().float()
            expanded_strides = expanded_strides.cpu().float()
            x_shifts = x_shifts.cpu()
            y_shifts = y_shifts.cpu()

        fg_mask, geometry_relation = self.get_geometry_constraint(
            gt_bboxes_per_image,
            expanded_strides,
            x_shifts,
            y_shifts,
        )
        bboxes_preds_per_image = bboxes_preds_per_image[fg_mask]
        cls_preds_selected = cls_preds[batch_idx][fg_mask]
        obj_preds_selected = obj_preds[batch_idx][fg_mask]
        num_in_boxes_anchor = bboxes_preds_per_image.shape[0]

        pair_wise_ious = bboxes_iou(gt_bboxes_per_image, bboxes_preds_per_image, False)
        gt_cls_per_image = F.one_hot(gt_classes.to(torch.int64), self.num_classes).float()
        pair_wise_ious_loss = -torch.log(pair_wise_ious + 1e-8)

        if mode == "cpu":
            cls_preds_selected = cls_preds_selected.cpu()
            obj_preds_selected = obj_preds_selected.cpu()

        with torch.amp.autocast("cuda", enabled=False):
            cls_preds_selected = (
                cls_preds_selected.float().sigmoid_() * obj_preds_selected.float().sigmoid_()
            ).sqrt()
            pair_wise_cls_loss = F.binary_cross_entropy(
                cls_preds_selected.unsqueeze(0).repeat(num_gt, 1, 1),
                gt_cls_per_image.unsqueeze(1).repeat(1, num_in_boxes_anchor, 1),
                reduction="none",
            ).sum(-1)
        del cls_preds_selected

        cost = pair_wise_cls_loss + 3.0 * pair_wise_ious_loss + float(1e6) * (~geometry_relation)
        num_fg, gt_matched_classes, pred_ious_this_matching, matched_gt_inds = self.simota_matching(
            cost,
            pair_wise_ious,
            gt_classes,
            num_gt,
            fg_mask,
        )
        del pair_wise_cls_loss, cost, pair_wise_ious, pair_wise_ious_loss

        if mode == "cpu":
            gt_matched_classes = gt_matched_classes.to(target_device)
            fg_mask = fg_mask.to(target_device)
            pred_ious_this_matching = pred_ious_this_matching.to(target_device)
            matched_gt_inds = matched_gt_inds.to(target_device)

        return gt_matched_classes, fg_mask, pred_ious_this_matching, matched_gt_inds, num_fg

    def get_geometry_constraint(self, gt_bboxes_per_image, expanded_strides, x_shifts, y_shifts):
        """根据固定中心区域筛选候选 anchor。"""

        expanded_strides_per_image = expanded_strides[0]
        x_centers_per_image = ((x_shifts[0] + 0.5) * expanded_strides_per_image).unsqueeze(0)
        y_centers_per_image = ((y_shifts[0] + 0.5) * expanded_strides_per_image).unsqueeze(0)

        center_radius = 1.5
        center_distance = expanded_strides_per_image.unsqueeze(0) * center_radius
        gt_left = gt_bboxes_per_image[:, 0:1] - center_distance
        gt_right = gt_bboxes_per_image[:, 0:1] + center_distance
        gt_top = gt_bboxes_per_image[:, 1:2] - center_distance
        gt_bottom = gt_bboxes_per_image[:, 1:2] + center_distance

        center_left = x_centers_per_image - gt_left
        center_right = gt_right - x_centers_per_image
        center_top = y_centers_per_image - gt_top
        center_bottom = gt_bottom - y_centers_per_image
        center_deltas = torch.stack([center_left, center_top, center_right, center_bottom], 2)
        is_in_centers = center_deltas.min(dim=-1).values > 0.0
        anchor_filter = is_in_centers.sum(dim=0) > 0
        geometry_relation = is_in_centers[:, anchor_filter]
        return anchor_filter, geometry_relation

    def simota_matching(self, cost, pair_wise_ious, gt_classes, num_gt: int, fg_mask):
        """执行 YOLOX SimOTA 匹配过程。"""

        matching_matrix = torch.zeros_like(cost, dtype=torch.uint8)
        candidate_topk = min(10, pair_wise_ious.size(1))
        topk_ious, _ = torch.topk(pair_wise_ious, candidate_topk, dim=1)
        dynamic_ks = torch.clamp(topk_ious.sum(1).int(), min=1)
        for gt_index in range(num_gt):
            _, positive_indices = torch.topk(cost[gt_index], k=dynamic_ks[gt_index], largest=False)
            matching_matrix[gt_index][positive_indices] = 1

        anchor_matching_gt = matching_matrix.sum(0)
        if anchor_matching_gt.max() > 1:
            multiple_match_mask = anchor_matching_gt > 1
            _, cost_argmin = torch.min(cost[:, multiple_match_mask], dim=0)
            matching_matrix[:, multiple_match_mask] *= 0
            matching_matrix[cost_argmin, multiple_match_mask] = 1

        fg_mask_inboxes = anchor_matching_gt > 0
        num_fg = fg_mask_inboxes.sum().item()
        fg_mask[fg_mask.clone()] = fg_mask_inboxes
        matched_gt_inds = matching_matrix[:, fg_mask_inboxes].argmax(0)
        gt_matched_classes = gt_classes[matched_gt_inds]
        pred_ious_this_matching = (matching_matrix * pair_wise_ious).sum(0)[fg_mask_inboxes]
        return num_fg, gt_matched_classes, pred_ious_this_matching, matched_gt_inds

    def visualize_assign_result(self, xin, labels=None, imgs=None, save_prefix: str = "assign_vis_") -> None:
        """把当前 batch 的标签分配结果绘制到图像文件。"""

        outputs = []
        x_shifts = []
        y_shifts = []
        expanded_strides = []
        for level_index, (cls_conv, reg_conv, stride_this_level, x) in enumerate(
            zip(self.cls_convs, self.reg_convs, self.strides, xin)
        ):
            x = self.stems[level_index](x)
            cls_feat = cls_conv(x)
            cls_output = self.cls_preds[level_index](cls_feat)
            reg_feat = reg_conv(x)
            reg_output = self.reg_preds[level_index](reg_feat)
            obj_output = self.obj_preds[level_index](reg_feat)
            output = torch.cat([reg_output, obj_output, cls_output], 1)
            output, grid = self.get_output_and_grid(output, level_index, stride_this_level, xin[0].type())
            x_shifts.append(grid[:, :, 0])
            y_shifts.append(grid[:, :, 1])
            expanded_strides.append(torch.full((1, grid.shape[1]), stride_this_level).type_as(xin[0]))
            outputs.append(output)

        outputs = torch.cat(outputs, 1)
        bbox_preds = outputs[:, :, :4]
        obj_preds = outputs[:, :, 4:5]
        cls_preds = outputs[:, :, 5:]
        total_num_anchors = outputs.shape[1]
        x_shifts = torch.cat(x_shifts, 1)
        y_shifts = torch.cat(y_shifts, 1)
        expanded_strides = torch.cat(expanded_strides, 1)
        label_counts = (labels.sum(dim=2) > 0).sum(dim=1)

        for batch_index, num_gt in enumerate(label_counts):
            img = imgs[batch_index].permute(1, 2, 0).to(torch.uint8).cpu().numpy().copy()
            num_gt = int(num_gt)
            if num_gt == 0:
                fg_mask = outputs.new_zeros(total_num_anchors).bool()
                gt_bboxes_per_image = outputs.new_zeros((0, 4))
                matched_gt_inds = outputs.new_zeros((0,), dtype=torch.long)
            else:
                gt_bboxes_per_image = labels[batch_index, :num_gt, 1:5]
                gt_classes = labels[batch_index, :num_gt, 0]
                bboxes_preds_per_image = bbox_preds[batch_index]
                _, fg_mask, _, matched_gt_inds, _ = self.get_assignments(
                    batch_index,
                    num_gt,
                    gt_bboxes_per_image,
                    gt_classes,
                    bboxes_preds_per_image,
                    expanded_strides,
                    x_shifts,
                    y_shifts,
                    cls_preds,
                    obj_preds,
                )

            coords = torch.stack(
                [
                    ((x_shifts + 0.5) * expanded_strides).flatten()[fg_mask],
                    ((y_shifts + 0.5) * expanded_strides).flatten()[fg_mask],
                ],
                1,
            )
            xyxy_boxes = cxcywh2xyxy(gt_bboxes_per_image.clone())
            save_name = f"{save_prefix}{batch_index}.png"
            visualize_assign(img, xyxy_boxes, coords, matched_gt_inds, save_name)
            LOGGER.info("save img to %s", save_name)