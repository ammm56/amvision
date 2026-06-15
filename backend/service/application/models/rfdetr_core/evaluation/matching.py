"""RF-DETR core 评估处理模块：`evaluation.matching`。"""

from typing import Any

import numpy as np
import torch
import torch.nn.functional as F  # noqa: N812
from torchvision.ops import box_iou

from backend.service.application.models.rfdetr_core.utilities import all_gather


def _compute_mask_iou(pred_masks: torch.Tensor, gt_masks: torch.Tensor) -> torch.Tensor:
    """执行 `_compute_mask_iou`。
    
    参数：
    - `pred_masks`：传入的 `pred_masks` 参数。
    - `gt_masks`：传入的 `gt_masks` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    n = pred_masks.shape[0]
    m = gt_masks.shape[0]
    if pred_masks.shape[-2:] != gt_masks.shape[-2:]:
        h, w = pred_masks.shape[-2:]
        gt_masks = F.interpolate(gt_masks.float().unsqueeze(1), size=(h, w), mode="nearest").squeeze(1)
    pred_flat = pred_masks.bool().view(n, -1).float()
    gt_flat = gt_masks.bool().view(m, -1).float()
    inter = torch.mm(pred_flat, gt_flat.t())
    pred_area = pred_flat.sum(dim=1, keepdim=True)
    gt_area = gt_flat.sum(dim=1, keepdim=True)
    union = pred_area + gt_area.t() - inter
    return torch.where(union > 0, inter / union, torch.zeros_like(inter))


def _match_single_class(
    pred_scores: torch.Tensor,
    pred_items: torch.Tensor,
    gt_items: torch.Tensor,
    gt_crowd: torch.Tensor,
    iou_threshold: float,
    iou_type: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """执行 `_match_single_class`。
    
    参数：
    - `pred_scores`：传入的 `pred_scores` 参数。
    - `pred_items`：传入的 `pred_items` 参数。
    - `gt_items`：传入的 `gt_items` 参数。
    - `gt_crowd`：传入的 `gt_crowd` 参数。
    - `iou_threshold`：传入的 `iou_threshold` 参数。
    - `iou_type`：传入的 `iou_type` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    n = pred_scores.shape[0]
    m = gt_items.shape[0]

    sort_idx = torch.argsort(pred_scores, descending=True)
    pred_scores_sorted = pred_scores[sort_idx]
    pred_sorted = pred_items[sort_idx]

    if iou_type == "bbox":
        iou_matrix = box_iou(pred_sorted, gt_items)
    else:
        iou_matrix = _compute_mask_iou(pred_sorted, gt_items)

    device = pred_scores.device
    gt_matched = torch.zeros(m, dtype=torch.bool, device=device)
    pred_match = torch.zeros(n, dtype=torch.long, device=device)
    pred_ignore = torch.zeros(n, dtype=torch.bool, device=device)

    for i in range(n):
        ious = iou_matrix[i]

        nc_ious = ious.clone()
        nc_ious[gt_crowd] = -1.0
        nc_ious[gt_matched & ~gt_crowd] = -1.0

        best_nc_iou, best_nc_idx = nc_ious.max(dim=0)
        if best_nc_iou >= iou_threshold:
            pred_match[i] = 1
            gt_matched[best_nc_idx] = True
        else:
            if gt_crowd.any():
                crowd_ious = ious.clone()
                crowd_ious[~gt_crowd] = -1.0
                if crowd_ious.max() >= iou_threshold:
                    pred_ignore[i] = True

    total_gt = int((~gt_crowd).sum().item())
    return (
        pred_scores_sorted.float().cpu().numpy().astype(np.float32),
        pred_match.cpu().numpy(),
        pred_ignore.cpu().numpy().astype(bool),
        total_gt,
    )


def build_matching_data(
    preds_list: list[dict[str, torch.Tensor]],
    targets_list: list[dict[str, torch.Tensor]],
    iou_threshold: float = 0.5,
    iou_type: str = "bbox",
) -> dict[int, dict[str, Any]]:
    """执行 `build_matching_data`。
    
    参数：
    - `preds_list`：传入的 `preds_list` 参数。
    - `targets_list`：传入的 `targets_list` 参数。
    - `iou_threshold`：传入的 `iou_threshold` 参数。
    - `iou_type`：传入的 `iou_type` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    acc: dict[int, dict[str, list | int]] = {}

    for preds, targets in zip(preds_list, targets_list):
        pred_boxes = preds["boxes"]
        pred_scores = preds["scores"]
        pred_labels = preds["labels"]
        pred_masks = preds.get("masks")

        gt_boxes = targets["boxes"]
        gt_labels = targets["labels"]
        gt_masks = targets.get("masks")
        raw_crowd = targets.get(
            "iscrowd",
            torch.zeros(len(gt_labels), dtype=torch.long, device=gt_labels.device),
        )
        gt_crowd = raw_crowd.bool()

        all_class_ids: set[int] = set(gt_labels.tolist()) | set(pred_labels.tolist())

        for class_id in all_class_ids:
            pred_mask_c = pred_labels == class_id
            gt_mask_c = gt_labels == class_id

            p_scores = pred_scores[pred_mask_c]
            gt_crowd_c = gt_crowd[gt_mask_c]
            n_pred = int(pred_mask_c.sum().item())
            n_gt = int(gt_mask_c.sum().item())

            entry = acc.setdefault(
                class_id,
                {"scores": [], "matches": [], "ignore": [], "total_gt": 0},
            )

            if n_pred == 0:
                entry["total_gt"] += int((~gt_crowd_c).sum().item())
                continue

            if n_gt == 0:
                sc = p_scores.float().cpu().numpy()
                order = np.argsort(-sc)
                entry["scores"].extend(sc[order].tolist())
                entry["matches"].extend([0] * n_pred)
                entry["ignore"].extend([False] * n_pred)
                continue

            if iou_type == "bbox":
                p_items: torch.Tensor = pred_boxes[pred_mask_c]
                gt_items: torch.Tensor = gt_boxes[gt_mask_c]
            else:
                if pred_masks is None or gt_masks is None:
                    raise ValueError("iou_type='segm' requires 'masks' in both preds and targets")
                p_items = pred_masks[pred_mask_c]
                gt_items = gt_masks[gt_mask_c]

            scores_np, matches_np, ignore_np, total_gt = _match_single_class(
                p_scores, p_items, gt_items, gt_crowd_c, iou_threshold, iou_type
            )

            entry["scores"].extend(scores_np.tolist())
            entry["matches"].extend(matches_np.tolist())
            entry["ignore"].extend(ignore_np.tolist())
            entry["total_gt"] += total_gt

    return {
        class_id: {
            "scores": np.array(data["scores"], dtype=np.float32),
            "matches": np.array(data["matches"], dtype=np.int64),
            "ignore": np.array(data["ignore"], dtype=bool),
            "total_gt": data["total_gt"],
        }
        for class_id, data in acc.items()
    }


def init_matching_accumulator() -> dict[int, dict[str, Any]]:
    """执行 `init_matching_accumulator`。
    
    返回：
    - 当前函数的执行结果。
    """
    return {}


def merge_matching_data(
    accumulator: dict[int, dict[str, Any]],
    new_data: dict[int, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """执行 `merge_matching_data`。
    
    参数：
    - `accumulator`：传入的 `accumulator` 参数。
    - `new_data`：传入的 `new_data` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    for class_id, data in new_data.items():
        if class_id not in accumulator:
            accumulator[class_id] = {
                "scores": data["scores"].copy(),
                "matches": data["matches"].copy(),
                "ignore": data["ignore"].copy(),
                "total_gt": data["total_gt"],
            }
        else:
            entry = accumulator[class_id]
            entry["scores"] = np.concatenate([entry["scores"], data["scores"]])
            entry["matches"] = np.concatenate([entry["matches"], data["matches"]])
            entry["ignore"] = np.concatenate([entry["ignore"], data["ignore"]])
            entry["total_gt"] += data["total_gt"]
    return accumulator


def distributed_merge_matching_data(
    local_data: dict[int, dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """执行 `distributed_merge_matching_data`。
    
    参数：
    - `local_data`：传入的 `local_data` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    gathered: list[dict[int, dict[str, Any]]] = all_gather(local_data)
    merged: dict[int, dict[str, Any]] = {}
    for rank_data in gathered:
        merge_matching_data(merged, rank_data)
    return merged


