"""YOLO 主线 pose 训练执行模块。复用 detection 损失 + 关键点损失。"""

from __future__ import annotations

import io
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.contracts.datasets.exports.dataset_formats import (
    COCO_KEYPOINTS_DATASET_FORMAT,
    YOLO_POSE_DATASET_FORMAT,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_dataset_manifest_support import (
    build_coco_payload_from_yolo_pose_split,
    normalize_yolo_category_names,
)
from backend.service.application.models.yolo_primary_model_configs import build_yolo_primary_model
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

YOLO_PRIMARY_POSE_IMPLEMENTATION_MODE = "yolo-primary-pose"
_POSE_DEF_INPUT_SIZE = (640, 640)
_POSE_DEF_BS = 4
_POSE_DEF_EPOCHS = 50
YOLO_PRIMARY_POSE_DEFAULT_EVALUATION_INTERVAL = 5
_POSE_DEF_ASSIGN_TOPK = 10
_POSE_DEF_CLS_W = 0.5
_POSE_DEF_BOX_W = 7.5
_POSE_DEF_DFL_W = 1.5
_POSE_DEF_KPT_W = 12.0
_POSE_DEF_ASSIGN_A = 0.5
_POSE_DEF_ASSIGN_B = 6.0
_POSE_DEF_MIN_LR = 0.01
_POSE_DEF_GRAD_CLIP = 10.0
_POSE_DEF_KPT_SHAPE = (17, 3)


@dataclass(frozen=True)
class YoloPrimaryPoseTrainingBatchProgress:
    epoch: int
    max_epochs: int
    iteration: int
    max_iterations: int
    global_iteration: int
    total_iterations: int
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class YoloPrimaryPoseTrainingEpochProgress:
    epoch: int
    max_epochs: int
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class YoloPrimaryPoseTrainingSavePoint:
    latest_checkpoint_bytes: bytes
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    learning_rate: float


@dataclass(frozen=True)
class YoloPrimaryPoseTrainingControlCommand:
    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


class YoloPrimaryPoseTrainingPausedError(Exception):
    pass


class YoloPrimaryPoseTrainingTerminatedError(Exception):
    pass


@dataclass(frozen=True)
class _PoseAnnotation:
    """单张图片的 Pose 标注。"""
    image_path: str
    boxes_xywh: list[list[float]]
    class_ids: list[int]
    keypoints: list[list[float]] | None = None  # 每个元素为 (K*3,) 扁平列表


@dataclass(frozen=True)
class _PosePreparedTarget:
    """训练态单图目标结构。"""
    boxes_xyxy: list[list[float]]
    category_indexes: list[int]
    keypoints: list[list[float]] | None = None  # (N, K*3) 扁平


@dataclass(frozen=True)
class YoloPrimaryPoseTrainingExecutionRequest:
    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_type: str
    model_scale: str
    batch_size: int = _POSE_DEF_BS
    max_epochs: int = _POSE_DEF_EPOCHS
    evaluation_interval: int = YOLO_PRIMARY_POSE_DEFAULT_EVALUATION_INTERVAL
    input_size: tuple[int, int] | None = None
    precision: str = "fp32"
    resume_checkpoint_path: Path | None = None
    extra_options: dict[str, object] | None = None
    epoch_callback: Callable | None = None
    savepoint_callback: Callable | None = None


@dataclass(frozen=True)
class YoloPrimaryPoseTrainingExecutionResult:
    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    labels: tuple[str, ...]


def run_yolo_primary_pose_training(
    request: YoloPrimaryPoseTrainingExecutionRequest,
) -> YoloPrimaryPoseTrainingExecutionResult:
    """执行 Pose 训练。"""

    import cv2
    import numpy as np
    import torch

    device = "cpu"
    if request.extra_options and str(request.extra_options.get("device", "")).startswith("cuda") and torch.cuda.is_available():
        device = str(request.extra_options["device"]).strip()

    precision = request.precision
    input_size = request.input_size or _POSE_DEF_INPUT_SIZE
    use_amp = precision == "fp16" and device.startswith("cuda")

    labels, train_anns, val_anns = _load_pose_manifest(request.dataset_storage, request.manifest_payload)
    num_classes = len(labels)
    kpt_shape = _POSE_DEF_KPT_SHAPE

    model = build_yolo_primary_model(
        model_type=request.model_type, task_type="pose",
        model_scale=request.model_scale, num_classes=num_classes,
    )
    model.to(device)
    trainable_params = [p for p in model.parameters() if p.requires_grad]

    extra = dict(request.extra_options or {})
    lr = float(extra.get("learning_rate", 1e-3))
    weight_decay = float(extra.get("weight_decay", 1e-4))
    min_lr = float(extra.get("min_lr_ratio", _POSE_DEF_MIN_LR))
    bs = max(1, int(extra.get("batch_size", request.batch_size)))
    max_epochs = max(1, int(extra.get("max_epochs", request.max_epochs)))
    cls_w = float(extra.get("class_loss_weight", _POSE_DEF_CLS_W))
    box_w = float(extra.get("box_loss_weight", _POSE_DEF_BOX_W))
    dfl_w = float(extra.get("dfl_loss_weight", _POSE_DEF_DFL_W))
    kpt_w = float(extra.get("kpt_loss_weight", _POSE_DEF_KPT_W))
    assign_topk = max(1, int(extra.get("assign_topk", _POSE_DEF_ASSIGN_TOPK)))
    assign_alpha = float(extra.get("assign_alpha", _POSE_DEF_ASSIGN_A))
    assign_beta = float(extra.get("assign_beta", _POSE_DEF_ASSIGN_B))
    grad_clip = max(0.0, float(extra.get("grad_clip_norm", _POSE_DEF_GRAD_CLIP)))

    optimizer = torch.optim.AdamW(trainable_params, lr=lr, weight_decay=weight_decay)
    iterations_per_epoch = max(1, (len(train_anns) + bs - 1) // bs)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=max_epochs * iterations_per_epoch, eta_min=lr * min_lr,
    )
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp) if use_amp else None

    # 恢复训练
    start_epoch = 0
    global_iteration = 0
    metrics_history: list[dict[str, object]] = []
    if request.resume_checkpoint_path and request.resume_checkpoint_path.is_file():
        ckpt = torch.load(str(request.resume_checkpoint_path), map_location=device, weights_only=False)
        model.load_state_dict(ckpt["model_state_dict"], strict=False)
        if "optimizer_state_dict" in ckpt:
            optimizer.load_state_dict(ckpt["optimizer_state_dict"])
        if "scheduler_state_dict" in ckpt and ckpt["scheduler_state_dict"] is not None:
            scheduler.load_state_dict(ckpt["scheduler_state_dict"])
        start_epoch = int(ckpt.get("epoch", 0))
        global_iteration = int(ckpt.get("global_iteration", 0))
        metrics_history = list(ckpt.get("metrics_history", []))

    best_metric_value = 0.0
    best_metric_name = "val_map50_95"
    ckpt_bytes = b""

    for epoch in range(start_epoch, max_epochs):
        model.train()
        epoch_losses: dict[str, float] = {}
        epoch_iters = 0

        import random
        indices = list(range(len(train_anns)))
        random.shuffle(indices)
        shuffled = [train_anns[i] for i in indices]

        for batch_start in range(0, len(shuffled), bs):
            batch_anns = shuffled[batch_start:batch_start + bs]
            images, targets = _build_pose_batch(batch_anns, input_size, device, precision, cv2, np, torch)
            if images is None:
                continue

            autocast_ctx = torch.amp.autocast("cuda", enabled=use_amp) if use_amp else nullcontext()
            with autocast_ctx:
                raw_outputs = model(images)
                if isinstance(raw_outputs, dict) and "one2many" in raw_outputs:
                    raw_for_loss = raw_outputs["one2many"]
                else:
                    raw_for_loss = raw_outputs

                from backend.service.application.models.pose_loss import compute_pose_loss
                loss_dict = compute_pose_loss(
                    torch=torch,
                    model=model,
                    raw_outputs=raw_for_loss,
                    batch_targets=targets,
                    num_classes=num_classes,
                    kpt_shape=kpt_shape,
                    class_loss_weight=cls_w,
                    box_loss_weight=box_w,
                    dfl_loss_weight=dfl_w,
                    kpt_loss_weight=kpt_w,
                    assign_topk=assign_topk,
                    assign_alpha=assign_alpha,
                    assign_beta=assign_beta,
                )

            total_loss = loss_dict["loss"]
            optimizer.zero_grad()
            if scaler is not None:
                scaler.scale(total_loss).backward()
                scaler.unscale_(optimizer)
                if grad_clip > 0:
                    torch.nn.utils.clip_grad_norm_(trainable_params, grad_clip)
                scaler.step(optimizer)
                scaler.update()
            else:
                total_loss.backward()
                if grad_clip > 0:
                    torch.nn.utils.clip_grad_norm_(trainable_params, grad_clip)
                optimizer.step()
            scheduler.step()
            global_iteration += 1

            for k, v in loss_dict.items():
                epoch_losses[k] = epoch_losses.get(k, 0.0) + float(v.item())
            epoch_iters += 1

        if epoch_iters > 0:
            avg_metrics = {k: round(v / epoch_iters, 6) for k, v in epoch_losses.items()}
        else:
            avg_metrics = {"loss": 0.0}

        metrics_history.append({"epoch": epoch, **avg_metrics})

        ep_progress = YoloPrimaryPoseTrainingEpochProgress(
            epoch=epoch, max_epochs=max_epochs, input_size=input_size,
            learning_rate=float(scheduler.get_last_lr()[0]),
            train_metrics=avg_metrics,
        )
        cmd = request.epoch_callback(ep_progress) if request.epoch_callback else None
        if cmd and cmd.terminate_training:
            raise YoloPrimaryPoseTrainingTerminatedError()

        # 保存 checkpoint
        buf = io.BytesIO()
        torch.save({
            "epoch": epoch + 1,
            "global_iteration": global_iteration,
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "scheduler_state_dict": scheduler.state_dict(),
            "metrics_history": metrics_history,
        }, buf)
        ckpt_bytes = buf.getvalue()

        if cmd and cmd.save_checkpoint and request.savepoint_callback:
            request.savepoint_callback(YoloPrimaryPoseTrainingSavePoint(
                latest_checkpoint_bytes=ckpt_bytes,
                train_metrics=avg_metrics,
                validation_metrics={},
                best_metric_value=best_metric_value,
                best_metric_name=best_metric_name,
                epoch=epoch + 1,
                learning_rate=float(scheduler.get_last_lr()[0]),
            ))

        if cmd and cmd.pause_training:
            raise YoloPrimaryPoseTrainingPausedError()

    return YoloPrimaryPoseTrainingExecutionResult(
        best_metric_value=best_metric_value,
        best_metric_name=best_metric_name,
        latest_checkpoint_bytes=ckpt_bytes,
        metrics_payload={"final_metrics": metrics_history[-1] if metrics_history else {}, "epoch_history": metrics_history},
        validation_metrics_payload={"epoch_history": []},
        labels=labels,
    )


def _load_pose_manifest(
    dataset_storage: LocalDatasetStorage,
    manifest: dict[str, object],
) -> tuple[tuple[str, ...], list[_PoseAnnotation], list[_PoseAnnotation]]:
    """加载 COCO keypoints 格式的 Pose manifest。"""

    splits = manifest.get("splits", [])
    format_id = str(manifest.get("format_id") or COCO_KEYPOINTS_DATASET_FORMAT).strip()
    yolo_category_names = (
        normalize_yolo_category_names(
            category_names=manifest.get("category_names"),
            format_label="YOLO pose",
        )
        if format_id == YOLO_POSE_DATASET_FORMAT
        else ()
    )
    all_categories: dict[int, str] = {}
    train_anns: list[_PoseAnnotation] = []
    val_anns: list[_PoseAnnotation] = []

    for split in (splits or []):
        if not isinstance(split, dict):
            continue
        split_name = str(split.get("name", ""))
        image_root = str(split.get("image_root", ""))
        if format_id == YOLO_POSE_DATASET_FORMAT:
            label_root = str(split.get("label_root", ""))
            image_root_path = dataset_storage.resolve(image_root)
            label_root_path = dataset_storage.resolve(label_root)
            if not image_root_path.is_dir():
                raise InvalidRequestError(
                    "pose 训练 split 缺少图片目录",
                    details={"split_name": split_name, "image_root": image_root},
                )
            if not label_root_path.is_dir():
                raise InvalidRequestError(
                    "pose 训练 split 缺少标签目录",
                    details={"split_name": split_name, "label_root": label_root},
                )
            payload = build_coco_payload_from_yolo_pose_split(
                split_name=split_name,
                image_root=image_root_path,
                label_root=label_root_path,
                category_names=yolo_category_names,
            )
        else:
            annotation_file = str(split.get("annotation_file", ""))
            annotation_path = dataset_storage.resolve(annotation_file)
            if not annotation_path.is_file():
                continue

            payload = dataset_storage.read_json(annotation_file)
            if not isinstance(payload, dict):
                continue

        for cat in (payload.get("categories") or []):
            if isinstance(cat, dict):
                all_categories[int(cat.get("id", -1))] = str(cat.get("name", ""))

        image_map: dict[int, str] = {}
        for img in (payload.get("images") or []):
            if isinstance(img, dict):
                image_map[int(img.get("id", -1))] = str(img.get("file_name", ""))

        annotations_by_image: dict[int, list[dict[str, Any]]] = {}
        for ann in (payload.get("annotations") or []):
            if not isinstance(ann, dict):
                continue
            img_id = int(ann.get("image_id", -1))
            annotations_by_image.setdefault(img_id, []).append(ann)

        records: list[_PoseAnnotation] = []
        for img_id, file_name in image_map.items():
            anns = annotations_by_image.get(img_id, [])
            boxes: list[list[float]] = []
            class_ids: list[int] = []
            keypoints: list[list[float]] = []
            for ann in anns:
                bb = ann.get("bbox")
                if not isinstance(bb, list) or len(bb) != 4:
                    continue
                boxes.append([float(v) for v in bb])
                class_ids.append(int(ann.get("category_id", 0)))
                kp = ann.get("keypoints")
                if isinstance(kp, list) and len(kp) > 0:
                    keypoints.append([float(v) for v in kp])
                else:
                    keypoints.append([])
            if boxes:
                records.append(_PoseAnnotation(
                    image_path=str(dataset_storage.resolve(f"{image_root}/{file_name}")),
                    boxes_xywh=boxes, class_ids=class_ids, keypoints=keypoints,
                ))

        if split_name == "train":
            train_anns = records
        elif split_name in ("val", "valid", "validation"):
            val_anns = records

    sorted_cats = sorted(all_categories.items())
    cat_id_map = {cid: idx for idx, (cid, _) in enumerate(sorted_cats)}
    labels = tuple(name for _, name in sorted_cats)

    def remap(anns: list[_PoseAnnotation]) -> list[_PoseAnnotation]:
        return [
            _PoseAnnotation(a.image_path, a.boxes_xywh, [cat_id_map.get(c, 0) for c in a.class_ids], a.keypoints)
            for a in anns
        ]

    return labels, remap(train_anns), remap(val_anns)


def _build_pose_batch(
    annotations: list[_PoseAnnotation],
    input_size: tuple[int, int],
    device: str,
    precision: str,
    cv2: Any,
    np: Any,
    torch: Any,
) -> tuple[Any, tuple[_PosePreparedTarget, ...]] | tuple[None, tuple[()]]:
    """构建 Pose 训练 batch。"""

    if not annotations:
        return None, ()

    target_w, target_h = input_size
    images = []
    targets: list[_PosePreparedTarget] = []

    for ann in annotations:
        img = cv2.imread(ann.image_path)
        if img is None:
            continue
        h0, w0 = img.shape[:2]
        ratio = min(target_w / w0, target_h / h0)
        new_w = int(round(w0 * ratio))
        new_h = int(round(h0 * ratio))
        resized = cv2.resize(img, (new_w, new_h))
        canvas = np.full((target_h, target_w, 3), 114, dtype=np.uint8)
        pad_x = (target_w - new_w) // 2
        pad_y = (target_h - new_h) // 2
        canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized

        tensor = canvas[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
        tensor = torch.from_numpy(tensor).to(device).float()
        if precision == "fp16":
            tensor = tensor.half()
        images.append(tensor)

        # 转换标注到目标坐标空间
        boxes_xyxy: list[list[float]] = []
        class_ids: list[int] = []
        kpts_transformed: list[list[float]] = []

        for i, (bb, ci) in enumerate(zip(ann.boxes_xywh, ann.class_ids)):
            x, y, w, h = bb
            # xywh -> xyxy，缩放到目标坐标
            x1 = (x * ratio + pad_x)
            y1 = (y * ratio + pad_y)
            x2 = ((x + w) * ratio + pad_x)
            y2 = ((y + h) * ratio + pad_y)
            if x2 - x1 < 2 or y2 - y1 < 2:
                continue
            boxes_xyxy.append([x1, y1, x2, y2])
            class_ids.append(ci)

            # 关键点坐标变换
            if ann.keypoints and i < len(ann.keypoints) and ann.keypoints[i]:
                raw_kp = ann.keypoints[i]
                nk = len(raw_kp) // 3
                transformed_kp: list[float] = []
                for k in range(nk):
                    kx = raw_kp[k * 3] * ratio + pad_x
                    ky = raw_kp[k * 3 + 1] * ratio + pad_y
                    kv = raw_kp[k * 3 + 2]
                    transformed_kp.extend([kx, ky, kv])
                kpts_transformed.append(transformed_kp)
            else:
                kpts_transformed.append([])

        targets.append(_PosePreparedTarget(
            boxes_xyxy=boxes_xyxy,
            category_indexes=class_ids,
            keypoints=kpts_transformed if kpts_transformed else None,
        ))

    if not images:
        return None, ()

    return torch.stack(images, dim=0), tuple(targets)
