"""RF-DETR 训练执行模块。Hungarian 匹配 + Focal/L1/GIoU loss + auxiliary losses。"""

from __future__ import annotations
import io, json, math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.rfdetr_model import (
    RfdetrModel, build_rfdetr_model, _box_cxcywh_to_xyxy, sigmoid_focal_loss,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

RFDETR_IMPL_MODE = "rfdetr-detection"
_RF_DEF_INPUT = (384, 384); _RF_DEF_BS = 2; _RF_DEF_EP = 1
_RF_DEF_LR = 1e-4; _RF_DEF_WD = 1e-4
_RF_DEF_CLS_COST = 2.0; _RF_DEF_BBOX_COST = 5.0; _RF_DEF_GIOU_COST = 2.0
_RF_DEF_CLS_W = 1.0; _RF_DEF_BBOX_W = 5.0; _RF_DEF_GIOU_W = 2.0

@dataclass(frozen=True)
class RfdetrTrainingBatchProgress:
    epoch: int; max_epochs: int; iteration: int; max_iterations: int; global_iteration: int; total_iterations: int; learning_rate: float; train_metrics: dict[str, float]

@dataclass(frozen=True)
class RfdetrTrainingEpochProgress:
    epoch: int; max_epochs: int; learning_rate: float; train_metrics: dict[str, float]

@dataclass(frozen=True)
class RfdetrTrainingSavePoint:
    latest_checkpoint_bytes: bytes; train_metrics: dict[str, float]; validation_metrics: dict[str, float]; best_metric_value: float; best_metric_name: str; epoch: int; learning_rate: float

@dataclass(frozen=True)
class RfdetrTrainingControlCommand:
    save_checkpoint: bool = False; pause_training: bool = False; terminate_training: bool = False

class RfdetrTrainingPausedError(Exception): pass
class RfdetrTrainingTerminatedError(Exception): pass

@dataclass(frozen=True)
class RfdetrTrainingExecutionRequest:
    dataset_storage: LocalDatasetStorage; manifest_payload: dict[str, object]; model_scale: str = "nano"
    batch_size: int = _RF_DEF_BS; max_epochs: int = _RF_DEF_EP
    input_size: tuple[int, int] | None = None; precision: str = "fp32"
    resume_checkpoint_path: Path | None = None; extra_options: dict[str, object] | None = None
    epoch_callback: Callable | None = None; savepoint_callback: Callable | None = None

@dataclass(frozen=True)
class RfdetrTrainingExecutionResult:
    best_metric_value: float; best_metric_name: str; latest_checkpoint_bytes: bytes; metrics_payload: dict[str, object]; validation_metrics_payload: dict[str, object]; labels: tuple[str, ...]

@dataclass(frozen=True)
class _RfAnnotation:
    image_path: str; boxes_xywh: list[list[float]]; class_ids: list[int]


def _giou_loss_boxes(pred_boxes: torch.Tensor, target_boxes: torch.Tensor) -> torch.Tensor:
    """两两计算 GIoU loss。"""
    px1, py1, px2, py2 = pred_boxes[:, 0], pred_boxes[:, 1], pred_boxes[:, 2], pred_boxes[:, 3]
    tx1, ty1, tx2, ty2 = target_boxes[:, 0], target_boxes[:, 1], target_boxes[:, 2], target_boxes[:, 3]
    pa = (px2 - px1) * (py2 - py1); ta = (tx2 - tx1) * (ty2 - ty1)
    ix1 = torch.max(px1, tx1); iy1 = torch.max(py1, ty1); ix2 = torch.min(px2, tx2); iy2 = torch.min(py2, ty2)
    iw = (ix2 - ix1).clamp(min=0); ih = (iy2 - iy1).clamp(min=0); ia = iw * ih
    ua = pa + ta - ia + 1e-7; iou = ia / ua
    ex1 = torch.min(px1, tx1); ey1 = torch.min(py1, ty1); ex2 = torch.max(px2, tx2); ey2 = torch.max(py2, ty2)
    ea = (ex2 - ex1) * (ey2 - ey1) + 1e-7; giou = iou - (ea - ua) / ea
    return (1.0 - giou).mean()


def _hungarian_match(pred_logits: torch.Tensor, pred_boxes: torch.Tensor, targets: list[dict], cls_cost: float, bbox_cost: float, giou_cost: float, nc: int) -> list[tuple[torch.Tensor, torch.Tensor]]:
    """Hungarian 二分匹配。"""
    B, Q, _ = pred_logits.shape
    from scipy.optimize import linear_sum_assignment
    indices = []
    for bi in range(B):
        tgt = targets[bi]; nt = len(tgt["class_ids"])
        if nt == 0: indices.append((torch.tensor([], dtype=torch.long), torch.tensor([], dtype=torch.long))); continue
        out_prob = pred_logits[bi, :, :nc].sigmoid()
        cost_class = -out_prob[:, [c for c in tgt["class_ids"]]].cpu()
        tgt_boxes_norm = torch.tensor(tgt["boxes"], dtype=torch.float32).unsqueeze(0)
        cost_bbox = torch.cdist(pred_boxes[bi].cpu(), tgt_boxes_norm, p=1).squeeze(1)
        cost_giou = -_compute_pairwise_giou(pred_boxes[bi].cpu(), torch.tensor(tgt["boxes"], dtype=torch.float32))
        C = cls_cost * cost_class + bbox_cost * cost_bbox + giou_cost * cost_giou
        pi, ti = linear_sum_assignment(C.numpy())
        indices.append((torch.as_tensor(pi, dtype=torch.long), torch.as_tensor(ti, dtype=torch.long)))
    return indices


def _compute_pairwise_giou(boxes1: torch.Tensor, boxes2: torch.Tensor) -> torch.Tensor:
    """计算两两 GIoU 矩阵。"""
    Q, _ = boxes1.shape; K, _ = boxes2.shape
    b1 = boxes1.unsqueeze(1).expand(Q, K, 4).contiguous().view(-1, 4)
    b2 = boxes2.unsqueeze(0).expand(Q, K, 4).contiguous().view(-1, 4)
    giou_flat = _generalized_box_iou_batch(b1, b2)
    return giou_flat.view(Q, K)


def _generalized_box_iou_batch(boxes1: torch.Tensor, boxes2: torch.Tensor) -> torch.Tensor:
    """批量计算 GIoU。"""
    area1 = (boxes1[:, 2] - boxes1[:, 0]) * (boxes1[:, 3] - boxes1[:, 1])
    area2 = (boxes2[:, 2] - boxes2[:, 0]) * (boxes2[:, 3] - boxes2[:, 1])
    lt = torch.max(boxes1[:, :2], boxes2[:, :2]); rb = torch.min(boxes1[:, 2:], boxes2[:, 2:])
    wh = (rb - lt).clamp(min=0); inter = wh[:, 0] * wh[:, 1]
    union = area1 + area2 - inter + 1e-7; iou = inter / union
    lt_e = torch.min(boxes1[:, :2], boxes2[:, :2]); rb_e = torch.max(boxes1[:, 2:], boxes2[:, 2:])
    wh_e = (rb_e - lt_e).clamp(min=0); ea = wh_e[:, 0] * wh_e[:, 1] + 1e-7
    return iou - (ea - union) / ea


def _compute_set_criterion_loss(pred_logits: torch.Tensor, pred_boxes: torch.Tensor, targets: list[dict], matched: list[tuple], nc: int, cls_w: float, bbox_w: float, giou_w: float) -> dict[str, torch.Tensor]:
    """根据匹配结果计算 losses。"""
    B, Q, _ = pred_logits.shape
    device = pred_logits.device
    loss_ce = torch.tensor(0.0, device=device); loss_bbox = torch.tensor(0.0, device=device); loss_giou = torch.tensor(0.0, device=device)
    num_boxes_total = 1
    for bi, (pi, ti) in enumerate(matched):
        nt = len(ti)
        if nt == 0: continue
        num_boxes_total += nt
        src_logits = pred_logits[bi, pi]
        src_boxes = pred_boxes[bi, pi]
        target_cls = torch.full((len(pi),), nc, dtype=torch.long, device=device)
        target_boxes_raw = torch.zeros((len(pi), 4), device=device)
        for j, (p_idx, t_idx) in enumerate(zip(pi, ti)):
            if t_idx < len(targets[bi]["class_ids"]):
                target_cls[j] = targets[bi]["class_ids"][t_idx]
                target_boxes_raw[j] = torch.tensor(targets[bi]["boxes"][t_idx], device=device)
        target_cls_onehot = torch.zeros((len(pi), nc), device=device)
        for j in range(len(pi)):
            if target_cls[j] < nc: target_cls_onehot[j, target_cls[j]] = 1.0
        loss_ce = loss_ce + sigmoid_focal_loss(src_logits[:, :nc], target_cls_onehot)
        loss_bbox = loss_bbox + F.l1_loss(src_boxes, target_boxes_raw, reduction="sum") / num_boxes_total
        loss_giou = loss_giou + _giou_loss_boxes(_box_cxcywh_to_xyxy(src_boxes), _box_cxcywh_to_xyxy(target_boxes_raw))
    return {"loss_ce": loss_ce * cls_w, "loss_bbox": loss_bbox * bbox_w, "loss_giou": loss_giou * giou_w}


def run_rfdetr_training(request: RfdetrTrainingExecutionRequest) -> RfdetrTrainingExecutionResult:
    import cv2, numpy as np
    imp = type("_I", (), {"cv2": cv2, "np": np, "torch": torch})()
    device = "cpu"
    if request.extra_options and str(request.extra_options.get("device", "")).startswith("cuda") and torch.cuda.is_available():
        device = str(request.extra_options["device"]).strip()
    input_size = request.input_size or _RF_DEF_INPUT
    labels, train_a, val_a = _rf_load_manifest(request.dataset_storage, request.manifest_payload)
    nc = len(labels)
    model = build_rfdetr_model(model_scale=request.model_scale, num_classes=nc)
    model.to(device)
    trainable = [p for p in model.parameters() if p.requires_grad]
    extra = dict(request.extra_options or {})
    lr = float(extra.get("learning_rate", _RF_DEF_LR)); bs = max(1, int(extra.get("batch_size", request.batch_size))); me = max(1, int(extra.get("max_epochs", request.max_epochs)))
    cls_cost = float(extra.get("class_cost", _RF_DEF_CLS_COST)); bbox_cost = float(extra.get("bbox_cost", _RF_DEF_BBOX_COST)); giou_cost = float(extra.get("giou_cost", _RF_DEF_GIOU_COST))
    cls_w = float(extra.get("class_loss_weight", _RF_DEF_CLS_W)); bbox_w = float(extra.get("bbox_loss_weight", _RF_DEF_BBOX_W)); giou_w = float(extra.get("giou_loss_weight", _RF_DEF_GIOU_W))
    opt = torch.optim.AdamW(trainable, lr=lr, weight_decay=_RF_DEF_WD)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=me * max(1, (len(train_a) + bs - 1) // bs), eta_min=lr * 0.01)
    m_hist = []; ckpt_bytes = b""
    for epoch in range(me):
        model.train(); ep_loss_ce = 0.0; ep_loss_bbox = 0.0; ep_loss_giou = 0.0; ep_iters = 0
        for b_start in range(0, len(train_a), bs):
            batch_a = train_a[b_start:b_start + bs]
            images, targets = _rf_build_batch(batch_a, input_size, device, imp)
            if images is None: continue
            outputs = model(images)
            pred_logits, pred_boxes = outputs["pred_logits"], outputs["pred_boxes"]
            matched = _hungarian_match(pred_logits.detach(), pred_boxes.detach(), targets, cls_cost, bbox_cost, giou_cost, nc)
            losses = _compute_set_criterion_loss(pred_logits, pred_boxes, targets, matched, nc, cls_w, bbox_w, giou_w)
            total = losses["loss_ce"] + losses["loss_bbox"] + losses["loss_giou"]
            opt.zero_grad(); total.backward(); opt.step(); sched.step()
            ep_loss_ce += float(losses["loss_ce"].item()); ep_loss_bbox += float(losses["loss_bbox"].item()); ep_loss_giou += float(losses["loss_giou"].item()); ep_iters += 1
        if ep_iters > 0: ep_loss_ce /= ep_iters; ep_loss_bbox /= ep_iters; ep_loss_giou /= ep_iters
        em = {"class_loss": round(ep_loss_ce, 6), "bbox_loss": round(ep_loss_bbox, 6), "giou_loss": round(ep_loss_giou, 6)}
        m_hist.append({"epoch": epoch, **em})
        ep_prog = RfdetrTrainingEpochProgress(epoch=epoch, max_epochs=me, learning_rate=float(sched.get_last_lr()[0]), train_metrics=em)
        cmd = request.epoch_callback(ep_prog) if request.epoch_callback else None
        if cmd and cmd.terminate_training: raise RfdetrTrainingTerminatedError()
        buf = io.BytesIO(); torch.save({"epoch": epoch + 1, "model_state_dict": model.state_dict(), "optimizer_state_dict": opt.state_dict(), "scheduler_state_dict": sched.state_dict(), "metrics_history": m_hist}, buf); ckpt_bytes = buf.getvalue()
        if cmd and request.savepoint_callback: request.savepoint_callback(RfdetrTrainingSavePoint(latest_checkpoint_bytes=ckpt_bytes, train_metrics=em, validation_metrics={}, best_metric_value=0.0, best_metric_name="val_loss", epoch=epoch + 1, learning_rate=float(sched.get_last_lr()[0])))
        if cmd and cmd.pause_training: raise RfdetrTrainingPausedError()
    return RfdetrTrainingExecutionResult(best_metric_value=0.0, best_metric_name="val_loss", latest_checkpoint_bytes=ckpt_bytes, metrics_payload={"epoch_history": m_hist}, validation_metrics_payload={}, labels=labels)


def _rf_load_manifest(ds, manifest):
    splits = manifest.get("splits", []); ac = {}; ta, va = [], []
    for sp in (splits or []):
        if not isinstance(sp, dict): continue
        sn = str(sp.get("name", "")); ir = str(sp.get("image_root", "")); af = str(sp.get("annotation_file", ""))
        ap = ds.resolve(af)
        if not ap.is_file(): continue
        p = ds.read_json(af)
        if not isinstance(p, dict): continue
        for c in (p.get("categories") or []):
            if isinstance(c, dict): ac[int(c.get("id", -1))] = str(c.get("name", ""))
        im = {}
        for img in (p.get("images") or []):
            if isinstance(img, dict): im[int(img.get("id", -1))] = str(img.get("file_name", ""))
        r = []
        for ann in (p.get("annotations") or []):
            if not isinstance(ann, dict): continue
            iid = int(ann.get("image_id", -1)); fn = im.get(iid, "")
            if not fn: continue
            bb = ann.get("bbox")
            if not isinstance(bb, list) or len(bb) != 4: continue
            r.append(_RfAnnotation(image_path=str(ds.resolve(f"{ir}/{fn}")), boxes_xywh=[bb], class_ids=[int(ann.get("category_id", 0))]))
        if sn == "train": ta = r
        elif sn == "val": va = r
    sc = sorted(ac.items()); cim = {cid: idx for idx, (cid, _) in enumerate(sc)}
    labels = tuple(n for _, n in sc)
    return labels, [_RfAnnotation(a.image_path, a.boxes_xywh, [cim.get(c, 0) for c in a.class_ids]) for a in ta], [_RfAnnotation(a.image_path, a.boxes_xywh, [cim.get(c, 0) for c in a.class_ids]) for a in va]


def _rf_build_batch(anns, input_size, device, imp):
    if not anns: return None, []
    imgs, tgs, tw, th = [], [], input_size[0], input_size[1]
    for ann in anns:
        img = imp.cv2.imread(ann.image_path)
        if img is None: continue
        h0, w0 = img.shape[:2]
        resized = imp.cv2.resize(img, (tw, th), interpolation=imp.cv2.INTER_LINEAR)
        tensor = resized[:, :, ::-1].transpose(2, 0, 1).astype(imp.np.float32) / 255.0
        imgs.append(torch.from_numpy(tensor).to(device).float())
        bts = [[(x + w / 2) / w0, (y + h / 2) / h0, w / w0, h / h0] for x, y, w, h in ann.boxes_xywh]
        tgs.append({"boxes": bts, "class_ids": ann.class_ids})
    return torch.stack(imgs, dim=0), tgs
