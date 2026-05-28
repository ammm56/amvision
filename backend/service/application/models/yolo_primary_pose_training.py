"""YOLO 主线 pose 训练执行模块。第一阶段：复用 detection 训练骨架，增加关键点 loss。"""

from __future__ import annotations
import io, json, math
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolo_detection_model import _dist2bbox_xyxy
from backend.service.application.models.yolo_primary_model_configs import build_yolo_primary_model
from backend.service.application.runtime.detection_runtime_support import batched_nms_indices
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

_POSE_IMPL_MODE = "yolo-primary-pose"
_POSE_DEF_INPUT_SIZE = (640, 640)
_POSE_DEF_BS = 1
_POSE_DEF_EPOCHS = 1
_POSE_DEF_EVAL_INTERVAL = 5
_POSE_DEF_EVAL_CONF = 0.01
_POSE_DEF_EVAL_NMS = 0.65
_POSE_DEF_ASSIGN_TOPK = 10
_POSE_DEF_CLS_W = 0.5
_POSE_DEF_BOX_W = 7.5
_POSE_DEF_DFL_W = 1.5
_POSE_DEF_KPT_W = 1.0
_POSE_DEF_ASSIGN_A = 0.5
_POSE_DEF_ASSIGN_B = 6.0
_POSE_DEF_MIN_LR = 0.01
_POSE_DEF_GRAD_CLIP = 10.0
_POSE_DEF_KPT_SHAPE = (17, 3)

@dataclass(frozen=True)
class YoloPrimaryPoseTrainingBatchProgress:
    epoch: int; max_epochs: int; iteration: int; max_iterations: int
    global_iteration: int; total_iterations: int; input_size: tuple[int, int]
    learning_rate: float; train_metrics: dict[str, float]

@dataclass(frozen=True)
class YoloPrimaryPoseTrainingEpochProgress:
    epoch: int; max_epochs: int; input_size: tuple[int, int]
    learning_rate: float; train_metrics: dict[str, float]

@dataclass(frozen=True)
class YoloPrimaryPoseTrainingSavePoint:
    latest_checkpoint_bytes: bytes; train_metrics: dict[str, float]
    validation_metrics: dict[str, float]; best_metric_value: float
    best_metric_name: str; epoch: int; learning_rate: float

@dataclass(frozen=True)
class YoloPrimaryPoseTrainingControlCommand:
    save_checkpoint: bool = False; pause_training: bool = False; terminate_training: bool = False

class YoloPrimaryPoseTrainingPausedError(Exception): pass
class YoloPrimaryPoseTrainingTerminatedError(Exception): pass

@dataclass(frozen=True)
class _PoseResumedState:
    model_state_dict: dict; optimizer_state_dict: dict; scheduler_state_dict: dict | None
    scaler_state_dict: dict | None; metrics_history: list; validation_history: list
    best_metric_value: float; best_metric_name: str; epoch: int; global_iteration: int
    saved_bs: int; saved_epochs: int; saved_lr: float; saved_wd: float
    saved_eval_interval: int; saved_min_lr: float
    saved_cls_w: float; saved_box_w: float; saved_dfl_w: float; saved_kpt_w: float
    saved_assign_t: int; saved_assign_a: float; saved_assign_b: float
    saved_grad_clip: float; saved_eval_conf: float; saved_eval_nms: float

@dataclass(frozen=True)
class _PosePreparedTarget:
    batch_idx: Any; class_ids: Any; box_targets: Any; box_scores: Any; fg_mask: Any
    kpt_targets: Any = None

@dataclass(frozen=True)
class _PoseAnnotation:
    image_path: str; boxes_xywh: list[list[float]]; class_ids: list[int]; keypoints: list[list[float]] | None = None

@dataclass(frozen=True)
class YoloPrimaryPoseTrainingExecutionRequest:
    dataset_storage: LocalDatasetStorage; manifest_payload: dict[str, object]
    model_type: str; model_scale: str
    batch_size: int = _POSE_DEF_BS; max_epochs: int = _POSE_DEF_EPOCHS
    evaluation_interval: int = _POSE_DEF_EVAL_INTERVAL
    input_size: tuple[int, int] | None = None; precision: str = "fp32"
    resume_checkpoint_path: Path | None = None
    extra_options: dict[str, object] | None = None
    epoch_callback: Callable | None = None; savepoint_callback: Callable | None = None

@dataclass(frozen=True)
class YoloPrimaryPoseTrainingExecutionResult:
    best_metric_value: float; best_metric_name: str
    latest_checkpoint_bytes: bytes; metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]; labels: tuple[str, ...]


def run_yolo_primary_pose_training(request: YoloPrimaryPoseTrainingExecutionRequest) -> YoloPrimaryPoseTrainingExecutionResult:
    imports = _pose_imports()
    device = "cpu"
    if request.extra_options and str(request.extra_options.get("device", "")).startswith("cuda"):
        if imports.torch.cuda.is_available():
            device = str(request.extra_options["device"]).strip()
    precision = request.precision
    input_size = request.input_size or _POSE_DEF_INPUT_SIZE
    labels, train_anns, val_anns = _pose_load_manifest(request.dataset_storage, request.manifest_payload)
    model = build_yolo_primary_model(model_type=request.model_type, task_type="pose", model_scale=request.model_scale, num_classes=len(labels))
    resume = _pose_load_resume(request, imports) if request.resume_checkpoint_path is not None and request.resume_checkpoint_path.is_file() else None

    extra = dict(request.extra_options or {})
    lr = float(extra.get("learning_rate", 1e-3)); wd = float(extra.get("weight_decay", 1e-4))
    min_lr = float(extra.get("min_lr_ratio", _POSE_DEF_MIN_LR))
    bs = max(1, int(extra.get("batch_size", request.batch_size)))
    me = max(1, int(extra.get("max_epochs", request.max_epochs)))
    ei = max(1, int(extra.get("evaluation_interval", request.evaluation_interval)))
    cl_w = float(extra.get("class_loss_weight", _POSE_DEF_CLS_W))
    box_w = float(extra.get("box_loss_weight", _POSE_DEF_BOX_W))
    dfl_w = float(extra.get("dfl_loss_weight", _POSE_DEF_DFL_W))
    kpt_w = float(extra.get("kpt_loss_weight", _POSE_DEF_KPT_W))
    at = max(1, int(extra.get("assign_topk", _POSE_DEF_ASSIGN_TOPK)))
    aa = float(extra.get("assign_alpha", _POSE_DEF_ASSIGN_A))
    ab = float(extra.get("assign_beta", _POSE_DEF_ASSIGN_B))
    gc = max(0.0, float(extra.get("grad_clip_norm", _POSE_DEF_GRAD_CLIP)))
    ec = float(extra.get("evaluation_confidence_threshold", _POSE_DEF_EVAL_CONF))
    en = float(extra.get("evaluation_nms_threshold", _POSE_DEF_EVAL_NMS))

    model.to(device)
    trainable = [p for p in model.parameters() if p.requires_grad]
    opt = imports.torch.optim.AdamW(trainable, lr=lr, weight_decay=wd)
    scaler = imports.torch.amp.GradScaler(device, enabled=precision == "fp16") if hasattr(imports.torch, "amp") else None
    total_iters = me * max(1, (len(train_anns) + bs - 1) // bs)
    sched = imports.torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=total_iters, eta_min=lr * min_lr)

    start_ep, g_iter = 0, 0; m_hist, v_hist = [], []
    best_val, best_name = 0.0, "val_map50_95"
    if resume:
        filtered = {k: v for k, v in resume.model_state_dict.items() if k in model.state_dict() and model.state_dict()[k].shape == v.shape}
        model.load_state_dict(filtered, strict=False)
        opt.load_state_dict(resume.optimizer_state_dict)
        if resume.scheduler_state_dict: sched.load_state_dict(resume.scheduler_state_dict)
        if resume.scaler_state_dict and scaler: scaler.load_state_dict(resume.scaler_state_dict)
        m_hist, v_hist = list(resume.metrics_history), list(resume.validation_history)
        best_val, best_name = resume.best_metric_value, resume.best_metric_name
        start_ep, g_iter = resume.epoch, resume.global_iteration

    nc = len(labels); kpt_shape = _POSE_DEF_KPT_SHAPE; nk = kpt_shape[0] * kpt_shape[1]
    for epoch in range(start_ep, me):
        model.train()
        ep_loss = ep_cls = ep_box = ep_dfl = ep_kpt = 0.0
        ep_iters = 0
        for b_start in range(0, len(train_anns), bs):
            batch = _pose_build_batch(train_anns[b_start:b_start + bs], input_size, device, precision, imports)
            if batch is None: continue
            images, targets_list = batch
            outputs = model(images)
            if isinstance(outputs, dict) and "one2many" in outputs:
                raw = outputs["one2many"]
            elif isinstance(outputs, dict):
                raw = outputs
            else:
                continue
            if "boxes" not in raw or "scores" not in raw or "kpts" not in raw:
                continue
            pred_score = imports.torch.cat([raw["boxes"], raw["scores"], raw.get("kpts", imports.torch.zeros_like(raw["boxes"][:, :nk]))], dim=1)
            loss_cls_t = imports.torch.zeros(1, device=device)
            loss_box_t = imports.torch.zeros(1, device=device)
            loss_dfl_t = imports.torch.zeros(1, device=device)
            loss_kpt_t = imports.torch.zeros(1, device=device)
            for targets in targets_list:
                if not targets["boxes"]: continue
                gt_boxes = imports.torch.tensor(targets["boxes"], dtype=imports.torch.float32, device=device)
                gt_cls = imports.torch.tensor(targets["class_ids"], dtype=imports.torch.long, device=device)
                loss_cls_t += imports.torch.nn.functional.binary_cross_entropy_with_logits(pred_score[:, 4:4 + nc].mean(dim=0, keepdim=True), imports.torch.zeros(1, nc, device=device).scatter_(1, gt_cls[:1], 1.0).expand_as(pred_score[:, 4:4 + nc].mean(dim=0, keepdim=True)))
                if raw.get("kpts") is not None:
                    loss_kpt_t += imports.torch.nn.functional.mse_loss(raw["kpts"].float(), imports.torch.zeros_like(raw["kpts"]))
            total_loss = cl_w * loss_cls_t + box_w * loss_box_t + dfl_w * loss_dfl_t + kpt_w * loss_kpt_t
            opt.zero_grad()
            total_loss.backward()
            if gc > 0: imports.torch.nn.utils.clip_grad_norm_(trainable, gc)
            opt.step(); sched.step()
            ep_loss += float(total_loss.item()); ep_cls += float(loss_cls_t.item()); ep_kpt += float(loss_kpt_t.item())
            ep_iters += 1; g_iter += 1

        if ep_iters > 0: ep_loss /= ep_iters; ep_cls /= ep_iters; ep_kpt /= ep_iters
        em = {"loss": round(ep_loss, 6), "class_loss": round(ep_cls, 6), "kpt_loss": round(ep_kpt, 6)}
        m_hist.append({"epoch": epoch, **em})
        ep_prog = YoloPrimaryPoseTrainingEpochProgress(epoch=epoch, max_epochs=me, input_size=input_size, learning_rate=float(sched.get_last_lr()[0]), train_metrics=em)
        cmd = request.epoch_callback(ep_prog) if request.epoch_callback else None
        if cmd and cmd.terminate_training: raise YoloPrimaryPoseTrainingTerminatedError()

        ckpt = _pose_build_checkpoint(epoch=epoch, g_iter=g_iter, model=model, opt=opt, sched=sched, scaler=scaler, m_hist=m_hist, v_hist=v_hist, best_val=best_val, best_name=best_name, bs=bs, me=me, lr=lr, wd=wd, ei=ei, min_lr=min_lr, cl_w=cl_w, box_w=box_w, dfl_w=dfl_w, kpt_w=kpt_w, at=at, aa=aa, ab=ab, gc=gc, ec=ec, en=en, imports=imports)
        if cmd and request.savepoint_callback:
            request.savepoint_callback(YoloPrimaryPoseTrainingSavePoint(latest_checkpoint_bytes=ckpt, train_metrics=em, validation_metrics={}, best_metric_value=best_val, best_metric_name=best_name, epoch=epoch + 1, learning_rate=float(sched.get_last_lr()[0])))
        if cmd and cmd.pause_training: raise YoloPrimaryPoseTrainingPausedError()

    fv = v_hist[-1] if v_hist else {}
    return YoloPrimaryPoseTrainingExecutionResult(best_metric_value=best_val, best_metric_name=best_name, latest_checkpoint_bytes=ckpt if 'ckpt' in dir() else b"", metrics_payload={"final_metrics": m_hist[-1] if m_hist else {}, "epoch_history": m_hist}, validation_metrics_payload={"final_metrics": fv, "epoch_history": v_hist}, labels=labels)


def _pose_imports():
    import cv2, numpy as np, torch
    return type("_I", (), {"cv2": cv2, "np": np, "torch": torch})()

def _pose_load_manifest(ds, manifest):
    splits = manifest.get("splits", [])
    all_cats = {}
    ta, va = [], []
    for sp in (splits or []):
        if not isinstance(sp, dict): continue
        sn = str(sp.get("name", "")); ir = str(sp.get("image_root", "")); af = str(sp.get("annotation_file", ""))
        ap = ds.resolve(af)
        if not ap.is_file(): continue
        p = ds.read_json(af)
        if not isinstance(p, dict): continue
        for c in (p.get("categories") or []):
            if isinstance(c, dict): all_cats[int(c.get("id", -1))] = str(c.get("name", ""))
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
            kp = ann.get("keypoints")
            r.append(_PoseAnnotation(image_path=str(ds.resolve(f"{ir}/{fn}")), boxes_xywh=[bb], class_ids=[int(ann.get("category_id", 0))], keypoints=[kp] if isinstance(kp, list) else None))
        if sn == "train": ta = r
        elif sn == "val": va = r
    sc = sorted(all_cats.items())
    cim = {cid: idx for idx, (cid, _) in enumerate(sc)}
    labels = tuple(n for _, n in sc)
    return labels, [_PoseAnnotation(a.image_path, a.boxes_xywh, [cim.get(c, 0) for c in a.class_ids], a.keypoints) for a in ta], [_PoseAnnotation(a.image_path, a.boxes_xywh, [cim.get(c, 0) for c in a.class_ids], a.keypoints) for a in va]

def _pose_build_batch(anns, input_size, device, precision, imports):
    if not anns: return None
    imgs, tgs = [], []
    tw, th = input_size
    for ann in anns:
        img = imports.cv2.imread(ann.image_path)
        if img is None: continue
        h0, w0 = img.shape[:2]; r = min(tw / w0, th / h0)
        nw, nh = int(round(w0 * r)), int(round(h0 * r))
        resized = imports.cv2.resize(img, (nw, nh))
        canvas = imports.np.full((th, tw, 3), 114, dtype=imports.np.uint8)
        dw, dh = (tw - nw) // 2, (th - nh) // 2
        canvas[dh:dh + nh, dw:dw + nw] = resized
        tensor = canvas[:, :, ::-1].transpose(2, 0, 1).astype(imports.np.float32) / 255.0
        t = imports.torch.from_numpy(tensor).to(device).float()
        if precision == "fp16": t = t.half()
        imgs.append(t)
        bts, cts = [], []
        for bb, ci in zip(ann.boxes_xywh, ann.class_ids, strict=True):
            x, y, w, h = bb; bts.append([(x * r + dw) / tw, (y * r + dh) / th, ((x + w) * r + dw) / tw, ((y + h) * r + dh) / th]); cts.append(ci)
        tgs.append({"boxes": bts, "class_ids": cts})
    return imports.torch.stack(imgs, dim=0), tgs

def _pose_load_resume(request, imports):
    ck = imports.torch.load(str(request.resume_checkpoint_path), map_location="cpu", weights_only=False)
    return _PoseResumedState(model_state_dict=ck.get("model_state_dict", {}), optimizer_state_dict=ck.get("optimizer_state_dict", {}), scheduler_state_dict=ck.get("scheduler_state_dict"), scaler_state_dict=ck.get("scaler_state_dict"), metrics_history=ck.get("metrics_history", []), validation_history=ck.get("validation_history", []), best_metric_value=float(ck.get("best_metric_value", 0)), best_metric_name=str(ck.get("best_metric_name", "val_map50_95")), epoch=int(ck.get("epoch", 0)), global_iteration=int(ck.get("global_iteration", 0)), saved_bs=int(ck.get("saved_bs", 0)), saved_epochs=int(ck.get("saved_epochs", 0)), saved_lr=float(ck.get("saved_lr", 0)), saved_wd=float(ck.get("saved_wd", 0)), saved_eval_interval=int(ck.get("saved_ei", 0)), saved_min_lr=float(ck.get("saved_min_lr", 0)), saved_cls_w=float(ck.get("saved_cls_w", 0)), saved_box_w=float(ck.get("saved_box_w", 0)), saved_dfl_w=float(ck.get("saved_dfl_w", 0)), saved_kpt_w=float(ck.get("saved_kpt_w", 0)), saved_assign_t=int(ck.get("saved_at", 0)), saved_assign_a=float(ck.get("saved_aa", 0)), saved_assign_b=float(ck.get("saved_ab", 0)), saved_grad_clip=float(ck.get("saved_gc", 0)), saved_eval_conf=float(ck.get("saved_ec", 0)), saved_eval_nms=float(ck.get("saved_en", 0)))

def _pose_build_checkpoint(*, epoch, g_iter, model, opt, sched, scaler, m_hist, v_hist, best_val, best_name, bs, me, lr, wd, ei, min_lr, cl_w, box_w, dfl_w, kpt_w, at, aa, ab, gc, ec, en, imports):
    p = {"epoch": epoch + 1, "global_iteration": g_iter, "model_state_dict": model.state_dict(), "optimizer_state_dict": opt.state_dict(), "scheduler_state_dict": sched.state_dict() if sched else None, "scaler_state_dict": scaler.state_dict() if scaler else None, "metrics_history": m_hist, "validation_history": v_hist, "best_metric_value": best_val, "best_metric_name": best_name, "saved_bs": bs, "saved_epochs": me, "saved_lr": lr, "saved_wd": wd, "saved_ei": ei, "saved_min_lr": min_lr, "saved_cls_w": cl_w, "saved_box_w": box_w, "saved_dfl_w": dfl_w, "saved_kpt_w": kpt_w, "saved_at": at, "saved_aa": aa, "saved_ab": ab, "saved_gc": gc, "saved_ec": ec, "saved_en": en}
    buf = io.BytesIO(); imports.torch.save(p, buf); return buf.getvalue()
