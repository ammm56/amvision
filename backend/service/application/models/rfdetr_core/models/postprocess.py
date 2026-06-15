"""RF-DETR core 模型结构模块：`models.postprocess`。"""

import torch
import torch.nn.functional as F  # noqa: N812
from torch import nn

from backend.service.application.models.rfdetr_core.utilities import box_ops


class PostProcess(nn.Module):
    """RF-DETR core 类：`PostProcess`。"""

    def __init__(self, num_select=300) -> None:
        super().__init__()
        self.num_select = num_select

    @torch.no_grad()
    def forward(self, outputs, target_sizes):
        """执行 `forward`。
        
        参数：
        - `outputs`：传入的 `outputs` 参数。
        - `target_sizes`：传入的 `target_sizes` 参数。
        """
        out_logits, out_bbox = outputs["pred_logits"], outputs["pred_boxes"]
        out_masks = outputs.get("pred_masks", None)

        assert len(out_logits) == len(target_sizes)
        assert target_sizes.shape[1] == 2

        prob = out_logits.sigmoid()
        topk_values, topk_indexes = torch.topk(prob.view(out_logits.shape[0], -1), self.num_select, dim=1)
        scores = topk_values
        topk_boxes = topk_indexes // out_logits.shape[2]
        labels = topk_indexes % out_logits.shape[2]
        boxes = box_ops.box_cxcywh_to_xyxy(out_bbox)
        boxes = torch.gather(boxes, 1, topk_boxes.unsqueeze(-1).repeat(1, 1, 4))

        img_h, img_w = target_sizes.unbind(1)
        scale_fct = torch.stack([img_w, img_h, img_w, img_h], dim=1)
        boxes = boxes * scale_fct[:, None, :]

        results = []
        if out_masks is not None:
            for i in range(out_masks.shape[0]):
                res_i = {"scores": scores[i], "labels": labels[i], "boxes": boxes[i]}
                k_idx = topk_boxes[i]
                masks_i = torch.gather(
                    out_masks[i],
                    0,
                    k_idx.unsqueeze(-1).unsqueeze(-1).repeat(1, out_masks.shape[-2], out_masks.shape[-1]),
                )
                h, w = target_sizes[i].tolist()
                masks_i = F.interpolate(
                    masks_i.unsqueeze(1),
                    size=(int(h), int(w)),
                    mode="bilinear",
                    align_corners=False,
                )
                res_i["masks"] = masks_i > 0.0
                results.append(res_i)
        else:
            results = [
                {"scores": score, "labels": label, "boxes": box} for score, label, box in zip(scores, labels, boxes)
            ]

        return results
