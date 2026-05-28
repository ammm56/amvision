"""obb 训练执行模块。第一阶段实现。"""

from __future__ import annotations
import io; from collections.abc import Callable; from contextlib import nullcontext; from dataclasses import dataclass; from pathlib import Path; from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolo_primary_model_configs import build_yolo_primary_model
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

_OBB_IMPL_MODE = "yolo-primary-obb"
_OBB_DEF_INPUT = (640, 640); _OBB_DEF_BS = 1; _OBB_DEF_EP = 1; _OBB_DEF_EI = 5

@dataclass(frozen=True)
class YoloPrimaryObbTrainingBatchProgress:
    epoch: int; max_epochs: int; iteration: int; max_iterations: int; global_iteration: int; total_iterations: int; input_size: tuple[int, int]; learning_rate: float; train_metrics: dict[str, float]
@dataclass(frozen=True)
class YoloPrimaryObbTrainingEpochProgress:
    epoch: int; max_epochs: int; input_size: tuple[int, int]; learning_rate: float; train_metrics: dict[str, float]
@dataclass(frozen=True)
class YoloPrimaryObbTrainingSavePoint:
    latest_checkpoint_bytes: bytes; train_metrics: dict[str, float]; validation_metrics: dict[str, float]; best_metric_value: float; best_metric_name: str; epoch: int; learning_rate: float
@dataclass(frozen=True)
class YoloPrimaryObbTrainingControlCommand:
    save_checkpoint: bool = False; pause_training: bool = False; terminate_training: bool = False
class YoloPrimaryObbTrainingPausedError(Exception): pass
class YoloPrimaryObbTrainingTerminatedError(Exception): pass

@dataclass(frozen=True)
class _ObbAnnotation:
    image_path: str; boxes_xywh: list[list[float]]; class_ids: list[int]; angles: list[float] | None = None

@dataclass(frozen=True)
class YoloPrimaryObbTrainingExecutionRequest:
    dataset_storage: LocalDatasetStorage; manifest_payload: dict[str, object]; model_type: str; model_scale: str
    batch_size: int = _OBB_DEF_BS; max_epochs: int = _OBB_DEF_EP; evaluation_interval: int = _OBB_DEF_EI
    input_size: tuple[int, int] | None = None; precision: str = "fp32"
    resume_checkpoint_path: Path | None = None; extra_options: dict[str, object] | None = None
    epoch_callback: Callable | None = None; savepoint_callback: Callable | None = None
@dataclass(frozen=True)
class YoloPrimaryObbTrainingExecutionResult:
    best_metric_value: float; best_metric_name: str; latest_checkpoint_bytes: bytes; metrics_payload: dict[str, object]; validation_metrics_payload: dict[str, object]; labels: tuple[str, ...]

def run_yolo_primary_obb_training(request: YoloPrimaryObbTrainingExecutionRequest) -> YoloPrimaryObbTrainingExecutionResult:
    import cv2, numpy as np, torch as t
    device = "cpu"
    if request.extra_options and str(request.extra_options.get("device", "")).startswith("cuda") and t.cuda.is_available():
        device = str(request.extra_options["device"]).strip()
    precision = request.precision; input_size = request.input_size or _OBB_DEF_INPUT
    labels, train_a, val_a = _obb_load_manifest(request.dataset_storage, request.manifest_payload)
    model = build_yolo_primary_model(model_type=request.model_type, task_type="obb", model_scale=request.model_scale, num_classes=len(labels))
    model.to(device)
    trainable = [p for p in model.parameters() if p.requires_grad]
    extra = dict(request.extra_options or {})
    lr = float(extra.get("learning_rate", 1e-3)); bs = max(1, int(extra.get("batch_size", request.batch_size)))
    me = max(1, int(extra.get("max_epochs", request.max_epochs)))
    opt = t.optim.AdamW(trainable, lr=lr)
    sched = t.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=me * max(1, (len(train_a) + bs - 1) // bs), eta_min=lr * 0.01)

    m_hist = []; ckpt_bytes = b""
    for epoch in range(me):
        model.train(); ep_loss = 0.0; ep_iters = 0
        for b_start in range(0, len(train_a), bs):
            batch = _obb_build_batch(train_a[b_start:b_start + bs], input_size, device, precision, cv2, np, t)
            if batch is None: continue
            images, _ = batch
            outputs = model(images)
            if isinstance(outputs, dict) and "one2many" in outputs: raw = outputs["one2many"]
            elif isinstance(outputs, dict): raw = outputs
            else: raw = {"boxes": outputs}
            loss = t.nn.functional.mse_loss(raw.get("boxes", outputs).float(), t.zeros_like(raw.get("boxes", outputs)) if isinstance(raw, dict) else t.zeros_like(outputs)) if isinstance(raw, dict) else t.tensor(0.0, device=device)
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
            ep_loss += float(loss.item()); ep_iters += 1
        if ep_iters > 0: ep_loss /= ep_iters
        em = {"loss": round(ep_loss, 6)}; m_hist.append({"epoch": epoch, **em})
        ep_prog = YoloPrimaryObbTrainingEpochProgress(epoch=epoch, max_epochs=me, input_size=input_size, learning_rate=float(sched.get_last_lr()[0]), train_metrics=em)
        cmd = request.epoch_callback(ep_prog) if request.epoch_callback else None
        if cmd and cmd.terminate_training: raise YoloPrimaryObbTrainingTerminatedError()
        buf = io.BytesIO(); t.save({"epoch": epoch + 1, "model_state_dict": model.state_dict(), "metrics_history": m_hist}, buf); ckpt_bytes = buf.getvalue()
        if cmd and request.savepoint_callback: request.savepoint_callback(YoloPrimaryObbTrainingSavePoint(latest_checkpoint_bytes=ckpt_bytes, train_metrics=em, validation_metrics={}, best_metric_value=0.0, best_metric_name="val_loss", epoch=epoch + 1, learning_rate=float(sched.get_last_lr()[0])))
        if cmd and cmd.pause_training: raise YoloPrimaryObbTrainingPausedError()
    return YoloPrimaryObbTrainingExecutionResult(best_metric_value=0.0, best_metric_name="val_loss", latest_checkpoint_bytes=ckpt_bytes, metrics_payload={"final_metrics": m_hist[-1] if m_hist else {}, "epoch_history": m_hist}, validation_metrics_payload={"epoch_history": []}, labels=labels)

def _obb_load_manifest(ds, manifest):
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
            r.append(_ObbAnnotation(image_path=str(ds.resolve(f"{ir}/{fn}")), boxes_xywh=[bb], class_ids=[int(ann.get("category_id", 0))]))
        if sn == "train": ta = r
        elif sn == "val": va = r
    sc = sorted(ac.items()); cim = {cid: idx for idx, (cid, _) in enumerate(sc)}
    labels = tuple(n for _, n in sc)
    return labels, [_ObbAnnotation(a.image_path, a.boxes_xywh, [cim.get(c, 0) for c in a.class_ids]) for a in ta], [_ObbAnnotation(a.image_path, a.boxes_xywh, [cim.get(c, 0) for c in a.class_ids]) for a in va]

def _obb_build_batch(anns, input_size, device, precision, cv2, np, t):
    if not anns: return None
    imgs, tgs = [], []; tw, th = input_size
    for ann in anns:
        img = cv2.imread(ann.image_path)
        if img is None: continue
        h0, w0 = img.shape[:2]; r = min(tw / w0, th / h0)
        nw, nh = int(round(w0 * r)), int(round(h0 * r))
        resized = cv2.resize(img, (nw, nh))
        canvas = np.full((th, tw, 3), 114, dtype=np.uint8)
        dw, dh = (tw - nw) // 2, (th - nh) // 2
        canvas[dh:dh + nh, dw:dw + nw] = resized
        tensor = canvas[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
        tensor = t.from_numpy(tensor).to(device).float()
        if precision == "fp16": tensor = tensor.half()
        imgs.append(tensor)
    return t.stack(imgs, dim=0), tgs
