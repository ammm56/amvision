"""OBB 训练执行模块。使用 probiou + 旋转框 TAL + 角度损失。"""

from __future__ import annotations

import io
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.application.models.yolo_primary_model_configs import build_yolo_primary_model
from backend.service.application.models.yolov8_core.data import (
    build_yolov8_obb_training_batch,
    build_yolov8_task_augmentation_options,
    resolve_yolov8_task_augmentation_for_epoch,
    resolve_yolov8_task_batch_input_size,
)
from backend.service.application.models.yolov8_core.evaluation import (
    evaluate_yolov8_obb_samples,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


YOLO_PRIMARY_OBB_IMPLEMENTATION_MODE = "yolo-primary-obb"
_OBB_DEF_INPUT = (640, 640)
_OBB_DEF_BS = 4
_OBB_DEF_EP = 50
YOLO_PRIMARY_OBB_DEFAULT_EVALUATION_INTERVAL = 5


@dataclass(frozen=True)
class YoloPrimaryObbTrainingBatchProgress:
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
class YoloPrimaryObbTrainingEpochProgress:
    epoch: int
    max_epochs: int
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class YoloPrimaryObbTrainingSavePoint:
    latest_checkpoint_bytes: bytes
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    learning_rate: float


@dataclass(frozen=True)
class YoloPrimaryObbTrainingControlCommand:
    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


class YoloPrimaryObbTrainingPausedError(Exception):
    pass


class YoloPrimaryObbTrainingTerminatedError(Exception):
    pass


@dataclass(frozen=True)
class _ObbAnnotation:
    """单张图片的 OBB 标注。"""
    image_path: str
    boxes_xywhr: list[list[float]]  # [[cx, cy, w, h, angle], ...]
    class_ids: list[int]


@dataclass(frozen=True)
class YoloPrimaryObbTrainingExecutionRequest:
    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_type: str
    model_scale: str
    batch_size: int = _OBB_DEF_BS
    max_epochs: int = _OBB_DEF_EP
    evaluation_interval: int = YOLO_PRIMARY_OBB_DEFAULT_EVALUATION_INTERVAL
    input_size: tuple[int, int] | None = None
    precision: str = "fp32"
    resume_checkpoint_path: Path | None = None
    extra_options: dict[str, object] | None = None
    epoch_callback: Callable | None = None
    savepoint_callback: Callable | None = None


@dataclass(frozen=True)
class YoloPrimaryObbTrainingExecutionResult:
    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    labels: tuple[str, ...]


@dataclass(frozen=True)
class _ObbPreparedTarget:
    """训练态单图目标结构。"""
    boxes_xywhr: list[list[float]]
    category_indexes: list[int]


def run_yolo_primary_obb_training(
    request: YoloPrimaryObbTrainingExecutionRequest,
) -> YoloPrimaryObbTrainingExecutionResult:
    """执行 OBB 训练。"""

    import cv2
    import numpy as np
    import torch

    device = "cpu"
    if (
        request.extra_options
        and str(request.extra_options.get("device", "")).startswith("cuda")
        and torch.cuda.is_available()
    ):
        device = str(request.extra_options["device"]).strip()

    precision = request.precision
    input_size = request.input_size or _OBB_DEF_INPUT
    use_amp = precision == "fp16" and device.startswith("cuda")

    labels, train_annotations, val_annotations = _load_obb_manifest(
        request.dataset_storage,
        request.manifest_payload,
    )
    num_classes = len(labels)

    model = build_yolo_primary_model(
        model_type=request.model_type,
        task_type="obb",
        model_scale=request.model_scale,
        num_classes=num_classes,
    )
    model.to(device)
    trainable_params = [p for p in model.parameters() if p.requires_grad]

    extra = dict(request.extra_options or {})
    lr = float(extra.get("learning_rate", 1e-3))
    weight_decay = float(extra.get("weight_decay", 1e-4))
    bs = max(1, int(extra.get("batch_size", request.batch_size)))
    max_epochs = max(1, int(extra.get("max_epochs", request.max_epochs)))
    yolov8_augmentation_options = (
        build_yolov8_task_augmentation_options(extra)
        if request.model_type == "yolov8"
        else None
    )

    optimizer = torch.optim.AdamW(trainable_params, lr=lr, weight_decay=weight_decay)
    iterations_per_epoch = max(1, (len(train_annotations) + bs - 1) // bs)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=max_epochs * iterations_per_epoch,
        eta_min=lr * 0.01,
    )
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp) if use_amp else None

    # 恢复训练
    start_epoch = 0
    if request.resume_checkpoint_path and request.resume_checkpoint_path.is_file():
        ckpt = torch.load(
            str(request.resume_checkpoint_path),
            map_location=device,
            weights_only=False,
        )
        model.load_state_dict(ckpt["model_state_dict"])
        if "optimizer_state_dict" in ckpt:
            optimizer.load_state_dict(ckpt["optimizer_state_dict"])
        if "scheduler_state_dict" in ckpt:
            scheduler.load_state_dict(ckpt["scheduler_state_dict"])
        start_epoch = int(ckpt.get("epoch", 0))

    best_metric_value = 0.0
    best_metric_name = "val_loss"
    metrics_history: list[dict[str, object]] = []
    global_iteration = 0
    total_iterations = max_epochs * iterations_per_epoch
    ckpt_bytes = b""
    validation_history: list[dict[str, object]] = []

    for epoch in range(start_epoch, max_epochs):
        model.train()
        epoch_losses: dict[str, float] = {}
        epoch_iters = 0
        effective_yolov8_augmentation_options = (
            resolve_yolov8_task_augmentation_for_epoch(
                augmentation_options=yolov8_augmentation_options,
                epoch_index=epoch,
                max_epochs=max_epochs,
            )
            if request.model_type == "yolov8"
            else None
        )

        # 随机打乱训练顺序
        indices = list(range(len(train_annotations)))
        import random
        random.shuffle(indices)
        shuffled = [train_annotations[i] for i in indices]

        for batch_start in range(0, len(shuffled), bs):
            batch_anns = shuffled[batch_start:batch_start + bs]
            if request.model_type == "yolov8":
                batch_input_size = resolve_yolov8_task_batch_input_size(
                    base_input_size=input_size,
                    augmentation_options=effective_yolov8_augmentation_options,
                )
                batch = build_yolov8_obb_training_batch(
                    samples=batch_anns,
                    input_size=batch_input_size,
                    device=device,
                    precision=precision,
                    imports=_build_yolov8_training_imports(cv2, np, torch),
                    augmentation_options=effective_yolov8_augmentation_options,
                    available_samples=shuffled,
                )
                if batch is None:
                    continue
                images = batch.images
                targets = batch.targets
            else:
                images, targets = _build_obb_batch(
                    batch_anns,
                    input_size,
                    device,
                    precision,
                    cv2,
                    np,
                    torch,
                )
                if images is None:
                    continue

            autocast_ctx = torch.amp.autocast("cuda", enabled=use_amp) if use_amp else nullcontext()
            with autocast_ctx:
                raw_outputs = model(images)
                if isinstance(raw_outputs, dict) and "one2many" in raw_outputs:
                    raw_for_loss = raw_outputs["one2many"]
                else:
                    raw_for_loss = raw_outputs

                if request.model_type == "yolov8":
                    from backend.service.application.models.yolov8_core.losses import (
                        compute_yolov8_obb_loss,
                    )

                    loss_dict = compute_yolov8_obb_loss(
                        torch=torch,
                        model=model,
                        raw_outputs=raw_for_loss,
                        batch_targets=targets,
                        num_classes=num_classes,
                    )
                else:
                    from backend.service.application.models.obb_loss import compute_obb_loss

                    loss_dict = compute_obb_loss(
                        torch=torch,
                        model=model,
                        raw_outputs=raw_for_loss,
                        batch_targets=targets,
                        num_classes=num_classes,
                    )

            total_loss = loss_dict["loss"]
            if not total_loss.requires_grad:
                total_loss = _build_obb_zero_grad_loss(raw_for_loss, torch)
            optimizer.zero_grad()
            if scaler is not None:
                scaler.scale(total_loss).backward()
                scaler.step(optimizer)
                scaler.update()
            else:
                total_loss.backward()
                optimizer.step()
            scheduler.step()
            global_iteration += 1

            for k, v in loss_dict.items():
                epoch_losses[k] = epoch_losses.get(k, 0.0) + float(v.item())
            epoch_iters += 1

            if request.epoch_callback and epoch_iters % max(1, iterations_per_epoch // 4) == 0:
                avg = {k: round(v / max(epoch_iters, 1), 6) for k, v in epoch_losses.items()}
                bp = YoloPrimaryObbTrainingBatchProgress(
                    epoch=epoch, max_epochs=max_epochs,
                    iteration=epoch_iters, max_iterations=iterations_per_epoch,
                    global_iteration=global_iteration, total_iterations=total_iterations,
                    input_size=input_size, learning_rate=float(scheduler.get_last_lr()[0]),
                    train_metrics=avg,
                )
                cmd = request.epoch_callback(bp)
                if cmd and cmd.terminate_training:
                    raise YoloPrimaryObbTrainingTerminatedError()

        # 计算 epoch 平均损失
        if epoch_iters > 0:
            avg_metrics = {k: round(v / epoch_iters, 6) for k, v in epoch_losses.items()}
        else:
            avg_metrics = {"loss": 0.0}

        metrics_history.append({"epoch": epoch, **avg_metrics})

        ep_progress = YoloPrimaryObbTrainingEpochProgress(
            epoch=epoch,
            max_epochs=max_epochs,
            input_size=input_size,
            learning_rate=float(scheduler.get_last_lr()[0]),
            train_metrics=avg_metrics,
        )
        cmd = request.epoch_callback(ep_progress) if request.epoch_callback else None
        if cmd and cmd.terminate_training:
            raise YoloPrimaryObbTrainingTerminatedError()

        val_metrics: dict[str, float] = {}
        should_evaluate = (
            request.model_type == "yolov8"
            and len(val_annotations) > 0
            and ((epoch > 0 and epoch % request.evaluation_interval == 0) or epoch == max_epochs - 1)
        )
        if should_evaluate:
            val_metrics = evaluate_yolov8_obb_samples(
                model=model,
                samples=val_annotations,
                labels=labels,
                input_size=input_size,
                device=device,
                precision=precision,
                score_threshold=float(extra.get("eval_confidence_threshold", 0.01)),
                nms_threshold=float(extra.get("eval_nms_threshold", 0.65)),
                imports=_build_yolov8_training_imports(cv2, np, torch),
            )
            validation_history.append({"epoch": epoch, **val_metrics})
            current_metric = float(val_metrics.get("map50_95", 0.0))
            if current_metric > best_metric_value:
                best_metric_value = current_metric
                best_metric_name = "val_map50_95"

        # 保存 checkpoint
        buf = io.BytesIO()
        torch.save(
            {
                "epoch": epoch + 1,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "scheduler_state_dict": scheduler.state_dict(),
                "metrics_history": metrics_history,
                "validation_history": validation_history,
            },
            buf,
        )
        ckpt_bytes = buf.getvalue()

        if cmd and cmd.save_checkpoint and request.savepoint_callback:
            request.savepoint_callback(
                YoloPrimaryObbTrainingSavePoint(
                    latest_checkpoint_bytes=ckpt_bytes,
                    train_metrics=avg_metrics,
                    validation_metrics=val_metrics,
                    best_metric_value=best_metric_value,
                    best_metric_name=best_metric_name,
                    epoch=epoch + 1,
                    learning_rate=float(scheduler.get_last_lr()[0]),
                )
            )

        if cmd and cmd.pause_training:
            raise YoloPrimaryObbTrainingPausedError()

    return YoloPrimaryObbTrainingExecutionResult(
        best_metric_value=best_metric_value,
        best_metric_name=best_metric_name,
        latest_checkpoint_bytes=ckpt_bytes,
        metrics_payload={
            "final_metrics": metrics_history[-1] if metrics_history else {},
            "epoch_history": metrics_history,
        },
        validation_metrics_payload={
            "final_metrics": validation_history[-1] if validation_history else {},
            "epoch_history": validation_history,
        },
        labels=labels,
    )


def _build_yolov8_training_imports(cv2: Any, np: Any, torch: Any) -> Any:
    """构建 YOLOv8 core data/evaluation 使用的依赖对象。"""

    from types import SimpleNamespace

    return SimpleNamespace(cv2=cv2, np=np, torch=torch)


def _build_obb_zero_grad_loss(raw_outputs: Any, torch: Any) -> Any:
    """用模型输出构建可反传的零损失。"""

    if torch.is_tensor(raw_outputs):
        return raw_outputs.sum() * 0.0
    if isinstance(raw_outputs, dict):
        tensors = [
            _build_obb_zero_grad_loss(value, torch)
            for value in raw_outputs.values()
            if _contains_obb_tensor(value, torch)
        ]
    elif isinstance(raw_outputs, list | tuple):
        tensors = [
            _build_obb_zero_grad_loss(value, torch)
            for value in raw_outputs
            if _contains_obb_tensor(value, torch)
        ]
    else:
        tensors = []
    if tensors:
        return sum(tensors)
    return torch.zeros((), requires_grad=True)


def _contains_obb_tensor(value: Any, torch: Any) -> bool:
    """判断输出结构里是否包含 torch Tensor。"""

    if torch.is_tensor(value):
        return True
    if isinstance(value, dict):
        return any(_contains_obb_tensor(item, torch) for item in value.values())
    if isinstance(value, list | tuple):
        return any(_contains_obb_tensor(item, torch) for item in value)
    return False


def _load_obb_manifest(
    dataset_storage: LocalDatasetStorage,
    manifest: dict[str, object],
) -> tuple[tuple[str, ...], list[_ObbAnnotation], list[_ObbAnnotation]]:
    """加载 OBB manifest，支持 COCO + angle 和 DOTA 四角点格式。"""

    splits = manifest.get("splits", [])
    all_categories: dict[int, str] = {}
    train_anns: list[_ObbAnnotation] = []
    val_anns: list[_ObbAnnotation] = []

    for split in (splits or []):
        if not isinstance(split, dict):
            continue
        split_name = str(split.get("name", ""))
        image_root = str(split.get("image_root", ""))
        annotation_file = str(split.get("annotation_file", ""))

        annotation_path = dataset_storage.resolve(annotation_file)
        if not annotation_path.is_file():
            continue

        payload = dataset_storage.read_json(annotation_file)
        if not isinstance(payload, dict):
            continue

        # 解析类别
        for cat in (payload.get("categories") or []):
            if isinstance(cat, dict):
                all_categories[int(cat.get("id", -1))] = str(cat.get("name", ""))

        # 解析图片映射
        image_map: dict[int, str] = {}
        for img in (payload.get("images") or []):
            if isinstance(img, dict):
                image_map[int(img.get("id", -1))] = str(img.get("file_name", ""))

        # 解析标注
        annotations_by_image: dict[int, list[dict[str, Any]]] = {}
        for ann in (payload.get("annotations") or []):
            if not isinstance(ann, dict):
                continue
            img_id = int(ann.get("image_id", -1))
            annotations_by_image.setdefault(img_id, []).append(ann)

        records: list[_ObbAnnotation] = []
        for img_id, file_name in image_map.items():
            anns = annotations_by_image.get(img_id, [])
            boxes_xywhr: list[list[float]] = []
            class_ids: list[int] = []
            for ann in anns:
                xywhr = _parse_obb_annotation(ann)
                if xywhr is not None:
                    boxes_xywhr.append(xywhr)
                    class_ids.append(int(ann.get("category_id", 0)))
            if boxes_xywhr:
                records.append(_ObbAnnotation(
                    image_path=str(dataset_storage.resolve(f"{image_root}/{file_name}")),
                    boxes_xywhr=boxes_xywhr,
                    class_ids=class_ids,
                ))

        if split_name == "train":
            train_anns = records
        elif split_name in ("val", "valid", "validation"):
            val_anns = records

    sorted_cats = sorted(all_categories.items())
    cat_id_map = {cid: idx for idx, (cid, _) in enumerate(sorted_cats)}
    labels = tuple(name for _, name in sorted_cats)

    def remap(anns: list[_ObbAnnotation]) -> list[_ObbAnnotation]:
        return [
            _ObbAnnotation(a.image_path, a.boxes_xywhr, [cat_id_map.get(c, 0) for c in a.class_ids])
            for a in anns
        ]

    return labels, remap(train_anns), remap(val_anns)


def _parse_obb_annotation(ann: dict[str, Any]) -> list[float] | None:
    """解析单条 OBB 标注，返回 [cx, cy, w, h, angle] 或 None。

    支持：
    - bbox (4 列 xywh) + angle 字段
    - rbox (5 列 xywhr)
    - poly (8 列四角点 xyxyxyxy)
    """
    # 优先检查 rbox (5 列 xywhr)
    rbox = ann.get("rbox")
    if isinstance(rbox, list) and len(rbox) == 5:
        return [float(v) for v in rbox]

    # 检查 polygon 四角点 (8 列)
    poly = ann.get("poly") or ann.get("polygon")
    if isinstance(poly, list) and len(poly) == 8:
        return _poly_to_xywhr([float(v) for v in poly])

    # 检查 bbox + angle
    bbox = ann.get("bbox")
    angle = ann.get("angle")
    if isinstance(bbox, list) and len(bbox) == 4:
        x, y, w, h = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        cx = x + w / 2.0
        cy = y + h / 2.0
        a = float(angle) if angle is not None else 0.0
        if w > 0 and h > 0:
            return [cx, cy, w, h, a]

    return None


def _poly_to_xywhr(poly: list[float]) -> list[float] | None:
    """把四角点 [x1,y1,x2,y2,x3,y3,x4,y4] 转为 [cx,cy,w,h,angle]。"""
    import numpy as np
    pts = np.array(poly, dtype=np.float64).reshape(4, 2)
    # 按 x 排序取左两点
    order = np.argsort(pts[:, 0])
    left = pts[order[:2]]
    right = pts[order[2:]]
    # 左上和左下
    if left[0, 1] > left[1, 1]:
        left = left[::-1]
    if right[0, 1] > right[1, 1]:
        right = right[::-1]
    p1, p4 = left[0], left[1]
    p2 = right[0]
    cx = float(np.mean(pts[:, 0]))
    cy = float(np.mean(pts[:, 1]))
    w = float(np.linalg.norm(p1 - p2))
    h = float(np.linalg.norm(p1 - p4))
    angle = float(np.arctan2(p2[1] - p1[1], p2[0] - p1[0]))
    if w > 0 and h > 0:
        return [cx, cy, w, h, angle]
    return None


def _build_obb_batch(
    annotations: list[_ObbAnnotation],
    input_size: tuple[int, int],
    device: str,
    precision: str,
    cv2: Any,
    np: Any,
    torch: Any,
) -> tuple[Any, tuple[_ObbPreparedTarget, ...]] | tuple[None, tuple[()]]:
    """构建 OBB 训练 batch，返回 (images, targets)。"""

    if not annotations:
        return None, ()

    target_w, target_h = input_size
    images = []
    targets: list[_ObbPreparedTarget] = []

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

        tensor = (
            canvas[:, :, ::-1]
            .transpose(2, 0, 1)
            .astype(np.float32)
            / 255.0
        )
        tensor = torch.from_numpy(tensor).to(device).float()
        if precision == "fp16":
            tensor = tensor.half()
        images.append(tensor)

        # 转换 OBB 标注到目标坐标空间
        scaled_boxes: list[list[float]] = []
        for box_xywhr in ann.boxes_xywhr:
            cx, cy, w, h, angle = box_xywhr
            # 缩放 + 平移
            new_cx = cx * ratio + pad_x
            new_cy = cy * ratio + pad_y
            new_w = w * ratio
            new_h = h * ratio
            if new_w > 1 and new_h > 1:
                scaled_boxes.append([new_cx, new_cy, new_w, new_h, angle])

        if len(scaled_boxes) <= len(ann.class_ids):
            category_indexes = ann.class_ids[: len(scaled_boxes)]
        else:
            category_indexes = ann.class_ids
        targets.append(
            _ObbPreparedTarget(
                boxes_xywhr=scaled_boxes,
                category_indexes=category_indexes,
            )
        )

    if not images:
        return None, ()

    return torch.stack(images, dim=0), tuple(targets)
