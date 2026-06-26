"""YOLOv8 segmentation 训练执行入口。"""

from __future__ import annotations

import io
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.contracts.datasets.exports.dataset_formats import (
    COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.models.yolo_core_common.weights import (
    YOLO_WARM_START_MINIMUM_LOADABLE_RATIO,
    build_yolo_disabled_warm_start_summary,
    build_yolo_warm_start_summary,
)
from backend.service.application.models.yolov8_core.assigners import (
    assign_yolov8_segmentation_targets,
)
from backend.service.application.models.yolov8_core.data import (
    build_yolov8_segmentation_training_batch,
    build_yolov8_task_augmentation_options,
    resolve_yolov8_task_augmentation_for_epoch,
    resolve_yolov8_task_batch_input_size,
)
from backend.service.application.models.yolov8_core.evaluation import (
    evaluate_yolov8_segmentation_samples,
)
from backend.service.application.models.yolov8_core.losses import (
    compute_yolov8_segmentation_detection_loss,
    compute_yolov8_segmentation_mask_loss,
)
from backend.service.application.models.support.yolo_dataset_manifest_support import (
    build_coco_payload_from_yolo_segmentation_split,
    normalize_yolo_category_names,
)
from backend.service.application.models.yolov8_core import build_yolov8_model
from backend.service.application.models.yolov8_core.weights import (
    load_yolov8_checkpoint_file,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


YOLOV8_SEGMENTATION_IMPLEMENTATION_MODE = "yolov8-segmentation-core"
_SEG_DEFAULT_INPUT_SIZE = (640, 640)
_SEG_DEFAULT_BATCH_SIZE = 1
_SEG_DEFAULT_MAX_EPOCHS = 1
_SEG_DEFAULT_EVAL_INTERVAL = 5
_SEG_DEFAULT_EVAL_CONF = 0.01
_SEG_DEFAULT_EVAL_NMS = 0.65
_SEG_DEFAULT_ASSIGN_TOPK = 10
_SEG_DEFAULT_CLASS_LOSS = 0.5
_SEG_DEFAULT_BOX_LOSS = 7.5
_SEG_DEFAULT_DFL_LOSS = 1.5
_SEG_DEFAULT_MASK_LOSS = 1.0
_SEG_DEFAULT_ASSIGN_ALPHA = 0.5
_SEG_DEFAULT_ASSIGN_BETA = 6.0
_SEG_DEFAULT_LR = 1e-3
_SEG_DEFAULT_WEIGHT_DECAY = 1e-4
_SEG_DEFAULT_MIN_LR = 0.01
_SEG_DEFAULT_GRAD_CLIP = 10.0


@dataclass(frozen=True)
class YoloV8SegmentationTrainingBatchProgress:
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
class YoloV8SegmentationTrainingEpochProgress:
    epoch: int
    max_epochs: int
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class YoloV8SegmentationTrainingSavePoint:
    latest_checkpoint_bytes: bytes
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    learning_rate: float


@dataclass(frozen=True)
class YoloV8SegmentationTrainingControlCommand:
    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


class YoloV8SegmentationTrainingPausedError(Exception):
    """训练被显式暂停。"""


class YoloV8SegmentationTrainingTerminatedError(Exception):
    """训练被显式终止。"""


@dataclass(frozen=True)
class _SegResumedState:
    model_state_dict: dict[str, object]
    optimizer_state_dict: dict[str, object]
    scheduler_state_dict: dict[str, object] | None
    scaler_state_dict: dict[str, object] | None
    metrics_history: list[dict[str, float]]
    validation_history: list[dict[str, float]]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    global_iteration: int
    saved_batch_size: int
    saved_max_epochs: int
    saved_lr: float
    saved_wd: float
    saved_eval_interval: int
    saved_min_lr: float
    saved_class_loss_weight: float
    saved_box_loss_weight: float
    saved_dfl_loss_weight: float
    saved_mask_loss_weight: float
    saved_assign_topk: int
    saved_assign_alpha: float
    saved_assign_beta: float
    saved_grad_clip: float
    saved_eval_conf: float
    saved_eval_nms: float


@dataclass(frozen=True)
class _SegTrainingAnnotation:
    image_path: str
    boxes_xywh: list[list[float]]
    class_ids: list[int]
    segmentations: list[list[list[float]] | None] | None = None


@dataclass(frozen=True)
class _SegTrainingImports:
    """描述 segmentation 训练依赖的本地模块。"""

    cv2: Any
    np: Any
    torch: Any


@dataclass(frozen=True)
class YoloV8SegmentationTrainingExecutionRequest:
    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_type: str
    model_scale: str
    batch_size: int = _SEG_DEFAULT_BATCH_SIZE
    max_epochs: int = _SEG_DEFAULT_MAX_EPOCHS
    evaluation_interval: int = _SEG_DEFAULT_EVAL_INTERVAL
    input_size: tuple[int, int] | None = None
    precision: str = "fp32"
    warm_start_checkpoint_path: Path | None = None
    warm_start_source_summary: dict[str, object] | None = None
    resume_checkpoint_path: Path | None = None
    extra_options: dict[str, object] | None = None
    epoch_callback: (
        Callable[
            [YoloV8SegmentationTrainingEpochProgress],
            YoloV8SegmentationTrainingControlCommand | None,
        ]
        | None
    ) = None
    savepoint_callback: (
        Callable[[YoloV8SegmentationTrainingSavePoint], None] | None
    ) = None


@dataclass(frozen=True)
class YoloV8SegmentationTrainingExecutionResult:
    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    labels: tuple[str, ...]
    warm_start_summary: dict[str, object]


def run_yolov8_segmentation_training(
    request: YoloV8SegmentationTrainingExecutionRequest,
) -> YoloV8SegmentationTrainingExecutionResult:
    """执行一次 YOLOv8 segmentation 训练。"""

    if request.model_type != "yolov8":
        raise InvalidRequestError(
            "YOLOv8 segmentation 训练入口只接受 model_type=yolov8",
            details={"model_type": request.model_type},
        )

    imports = _seg_require_imports()
    device = _seg_resolve_device(request.extra_options)
    precision = request.precision
    input_size = request.input_size or _SEG_DEFAULT_INPUT_SIZE

    labels, train_anns, val_anns = _seg_load_manifest(
        request.dataset_storage,
        request.manifest_payload,
    )

    model = build_yolov8_model(
        task_type="segmentation",
        model_scale=request.model_scale,
        num_classes=len(labels),
    )
    warm_start_summary = build_yolo_disabled_warm_start_summary()
    if (
        request.resume_checkpoint_path is None
        and request.warm_start_checkpoint_path is not None
        and request.warm_start_checkpoint_path.is_file()
    ):
        load_result = load_yolov8_checkpoint_file(
            torch_module=imports.torch,
            model=model,
            checkpoint_path=request.warm_start_checkpoint_path,
            minimum_loadable_ratio=YOLO_WARM_START_MINIMUM_LOADABLE_RATIO,
            strict_shape=False,
        )
        warm_start_summary = build_yolo_warm_start_summary(
            load_result=load_result,
            source_summary=request.warm_start_source_summary,
        )
    resume = None
    if (
        request.resume_checkpoint_path is not None
        and request.resume_checkpoint_path.is_file()
    ):
        resume = _seg_load_resume(request, imports)

    extra = dict(request.extra_options or {})
    lr = float(extra.get("learning_rate", _SEG_DEFAULT_LR))
    wd = float(extra.get("weight_decay", _SEG_DEFAULT_WEIGHT_DECAY))
    min_lr = float(extra.get("min_lr_ratio", _SEG_DEFAULT_MIN_LR))
    bs = max(1, int(extra.get("batch_size", request.batch_size)))
    me = max(1, int(extra.get("max_epochs", request.max_epochs)))
    eval_interval = max(
        1, int(extra.get("evaluation_interval", request.evaluation_interval))
    )
    cl_w = float(extra.get("class_loss_weight", _SEG_DEFAULT_CLASS_LOSS))
    box_w = float(extra.get("box_loss_weight", _SEG_DEFAULT_BOX_LOSS))
    dfl_w = float(extra.get("dfl_loss_weight", _SEG_DEFAULT_DFL_LOSS))
    mask_w = float(extra.get("mask_loss_weight", _SEG_DEFAULT_MASK_LOSS))
    assign_topk = max(1, int(extra.get("assign_topk", _SEG_DEFAULT_ASSIGN_TOPK)))
    assign_alpha = float(extra.get("assign_alpha", _SEG_DEFAULT_ASSIGN_ALPHA))
    assign_beta = float(extra.get("assign_beta", _SEG_DEFAULT_ASSIGN_BETA))
    grad_clip = max(0.0, float(extra.get("grad_clip_norm", _SEG_DEFAULT_GRAD_CLIP)))
    eval_conf = float(
        extra.get("evaluation_confidence_threshold", _SEG_DEFAULT_EVAL_CONF)
    )
    eval_nms = float(extra.get("evaluation_nms_threshold", _SEG_DEFAULT_EVAL_NMS))
    yolov8_augmentation_options = build_yolov8_task_augmentation_options(extra)

    if resume is not None:
        _seg_validate_resume(
            state=resume,
            batch_size=bs,
            max_epochs=me,
            learning_rate=lr,
            weight_decay=wd,
            evaluation_interval=eval_interval,
            min_lr_ratio=min_lr,
            class_loss_weight=cl_w,
            box_loss_weight=box_w,
            dfl_loss_weight=dfl_w,
            mask_loss_weight=mask_w,
            assign_topk=assign_topk,
            assign_alpha=assign_alpha,
            assign_beta=assign_beta,
            grad_clip=grad_clip,
            evaluation_confidence_threshold=eval_conf,
            evaluation_nms_threshold=eval_nms,
        )

    model.to(device)
    trainable = [p for p in model.parameters() if p.requires_grad]
    optimizer = imports.torch.optim.AdamW(trainable, lr=lr, weight_decay=wd)
    scaler = (
        imports.torch.amp.GradScaler(device, enabled=precision == "fp16")
        if hasattr(imports.torch, "amp") and hasattr(imports.torch.amp, "GradScaler")
        else None
    )
    total_iters = me * max(1, (len(train_anns) + bs - 1) // bs)
    scheduler = imports.torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=total_iters,
        eta_min=lr * min_lr,
    )

    start_epoch = 0
    g_iter = 0
    m_hist, v_hist = [], []
    best_val, best_name = 0.0, "val_map50_95"
    latest_checkpoint_bytes = b""
    if resume is not None:
        _seg_apply_resume(model, optimizer, scheduler, scaler, resume, imports, device)
        m_hist, v_hist = list(resume.metrics_history), list(resume.validation_history)
        best_val, best_name = resume.best_metric_value, resume.best_metric_name
        start_epoch = resume.epoch
        g_iter = resume.global_iteration

    nc = len(labels)
    strides = model.stride if hasattr(model, "stride") else (8, 16, 32)

    for epoch in range(start_epoch, me):
        model.train()
        ep_loss = 0.0
        ep_cls_loss, ep_box_loss, ep_dfl_loss, ep_mask_loss = 0.0, 0.0, 0.0, 0.0
        ep_iters = 0
        effective_yolov8_augmentation_options = resolve_yolov8_task_augmentation_for_epoch(
            augmentation_options=yolov8_augmentation_options,
            epoch_index=epoch,
            max_epochs=me,
        )
        for b_start in range(0, len(train_anns), bs):
            batch_annotations = train_anns[b_start : b_start + bs]
            batch_input_size = resolve_yolov8_task_batch_input_size(
                base_input_size=input_size,
                augmentation_options=effective_yolov8_augmentation_options,
            )
            batch = _seg_build_batch(
                batch_annotations,
                batch_input_size,
                device,
                precision,
                imports,
                yolov8_augmentation_options=effective_yolov8_augmentation_options,
                yolov8_available_samples=train_anns,
            )
            if batch is None:
                continue
            images, targets_list = batch
            with _seg_autocast(imports, precision, device):
                outputs = model(images)
                if isinstance(outputs, dict) and "one2many" in outputs:
                    raw_out = outputs["one2many"]
                elif isinstance(outputs, dict):
                    raw_out = outputs
                else:
                    continue
                if not isinstance(raw_out, dict) or "boxes" not in raw_out:
                    continue
                raw_boxes = raw_out["boxes"]
                raw_scores = raw_out["scores"]
                feature_maps = raw_out.get("feats", [])
                raw_mask_coeffs = raw_out.get("mask_coefficients")
                proto = raw_out.get("proto")
            if not feature_maps:
                continue
            anchor_points, stride_tensor = _seg_make_anchors_from_feats(
                feature_maps,
                strides,
                device,
                imports,
            )
            seg_head = model.model[-1]
            if int(getattr(seg_head, "reg_max", 1)) > 1:
                decoded_distances = seg_head.dfl(raw_boxes)
            else:
                decoded_distances = imports.torch.nn.functional.softplus(raw_boxes)
            prediction_parts = [
                decoded_distances.permute(0, 2, 1).contiguous(),
                raw_scores.permute(0, 2, 1).contiguous(),
            ]
            if raw_mask_coeffs is not None:
                prediction_parts.append(raw_mask_coeffs.permute(0, 2, 1).contiguous())
            pred_scores = imports.torch.cat(prediction_parts, dim=-1)
            distance_logits = raw_boxes.permute(0, 2, 1).contiguous()
            prepareds = [
                assign_yolov8_segmentation_targets(
                    torch_module=imports.torch,
                    targets=targets,
                    prediction=pred_scores[batch_index],
                    anchor_points=anchor_points,
                    stride_tensor=stride_tensor,
                    topk=assign_topk,
                    alpha=assign_alpha,
                    beta=assign_beta,
                    num_classes=nc,
                )
                for batch_index, targets in enumerate(targets_list)
            ]
            loss_cls = imports.torch.zeros(1, device=device)
            loss_box = imports.torch.zeros(1, device=device)
            loss_dfl = imports.torch.zeros(1, device=device)
            loss_mask_t = imports.torch.zeros(1, device=device)
            for batch_index, p in enumerate(prepareds):
                if p is None:
                    continue
                image_prediction = pred_scores[batch_index]
                fg = p.fg_mask.to(device)
                l_c, l_b, l_d = compute_yolov8_segmentation_detection_loss(
                    torch_module=imports.torch,
                    prediction=image_prediction,
                    assignment=p,
                    anchor_points=anchor_points,
                    stride_tensor=stride_tensor,
                    dfl_weight=dfl_w,
                    num_classes=nc,
                    distance_logits=distance_logits[batch_index],
                    reg_max=int(getattr(seg_head, "reg_max", 1)),
                )
                loss_cls += l_c
                loss_box += l_b
                loss_dfl += l_d
                if proto is not None and raw_mask_coeffs is not None:
                    l_m = _seg_compute_mask_loss(
                        image_prediction,
                        proto[batch_index],
                        p,
                        nc,
                        imports,
                        fg,
                    )
                    loss_mask_t += l_m
            total_loss = (
                cl_w * loss_cls
                + box_w * loss_box
                + dfl_w * loss_dfl
                + mask_w * loss_mask_t
            )
            if not total_loss.requires_grad:
                total_loss = raw_scores.sum() * 0.0
            optimizer.zero_grad()
            if scaler is not None:
                scaler.scale(total_loss).backward()
                if grad_clip > 0:
                    scaler.unscale_(optimizer)
                    imports.torch.nn.utils.clip_grad_norm_(trainable, grad_clip)
                scaler.step(optimizer)
                scaler.update()
            else:
                total_loss.backward()
                if grad_clip > 0:
                    imports.torch.nn.utils.clip_grad_norm_(trainable, grad_clip)
                optimizer.step()
            scheduler.step()
            ep_loss += float(total_loss.item())
            ep_cls_loss += float(loss_cls.item())
            ep_box_loss += float(loss_box.item())
            ep_dfl_loss += float(loss_dfl.item())
            ep_mask_loss += float(loss_mask_t.item())
            ep_iters += 1
            g_iter += 1

        if ep_iters > 0:
            ep_loss /= ep_iters
            ep_cls_loss /= ep_iters
            ep_box_loss /= ep_iters
            ep_dfl_loss /= ep_iters
            ep_mask_loss /= ep_iters
        epoch_metrics = {
            "loss": round(ep_loss, 6),
            "class_loss": round(ep_cls_loss, 6),
            "box_loss": round(ep_box_loss, 6),
            "dfl_loss": round(ep_dfl_loss, 6),
            "mask_loss": round(ep_mask_loss, 6),
        }
        m_hist.append({"epoch": epoch, **epoch_metrics})

        ep_progress = YoloV8SegmentationTrainingEpochProgress(
            epoch=epoch,
            max_epochs=me,
            input_size=input_size,
            learning_rate=float(scheduler.get_last_lr()[0]),
            train_metrics=epoch_metrics,
        )
        cmd = (
            request.epoch_callback(ep_progress)
            if request.epoch_callback is not None
            else None
        )
        if cmd is not None and cmd.terminate_training:
            raise YoloV8SegmentationTrainingTerminatedError()

        val_metrics: dict[str, float] = {}
        if (
            len(val_anns) > 0 and epoch > 0 and epoch % eval_interval == 0
        ) or epoch == me - 1:
            val_metrics = evaluate_yolov8_segmentation_samples(
                model=model,
                samples=val_anns,
                labels=labels,
                input_size=input_size,
                device=device,
                precision=precision,
                eval_confidence_threshold=eval_conf,
                eval_nms_threshold=eval_nms,
                imports=imports,
            )
            v_hist.append({"epoch": epoch, **val_metrics})
        current_val = float(val_metrics.get("map50_95", 0.0))
        if current_val > best_val:
            best_val = current_val
            best_name = "val_map50_95"

        latest_checkpoint_bytes = _seg_build_checkpoint(
            epoch=epoch,
            g_iter=g_iter,
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            m_hist=m_hist,
            v_hist=v_hist,
            best_val=best_val,
            best_name=best_name,
            bs=bs,
            me=me,
            lr=lr,
            wd=wd,
            eval_interval=eval_interval,
            min_lr=min_lr,
            cl_w=cl_w,
            box_w=box_w,
            dfl_w=dfl_w,
            mask_w=mask_w,
            assign_topk=assign_topk,
            assign_alpha=assign_alpha,
            assign_beta=assign_beta,
            grad_clip=grad_clip,
            eval_conf=eval_conf,
            eval_nms=eval_nms,
            imports=imports,
        )
        if cmd is not None and request.savepoint_callback is not None:
            request.savepoint_callback(
                YoloV8SegmentationTrainingSavePoint(
                    latest_checkpoint_bytes=latest_checkpoint_bytes,
                    train_metrics=epoch_metrics,
                    validation_metrics=val_metrics,
                    best_metric_value=best_val,
                    best_metric_name=best_name,
                    epoch=epoch + 1,
                    learning_rate=float(scheduler.get_last_lr()[0]),
                )
            )
        if cmd is not None and cmd.pause_training:
            raise YoloV8SegmentationTrainingPausedError()

    final_v = v_hist[-1] if v_hist else {}
    return YoloV8SegmentationTrainingExecutionResult(
        best_metric_value=best_val,
        best_metric_name=best_name,
        latest_checkpoint_bytes=latest_checkpoint_bytes,
        metrics_payload={
            "final_metrics": m_hist[-1] if m_hist else {},
            "epoch_history": m_hist,
            "scheduler": "CosineAnnealingLR",
        },
        validation_metrics_payload={
            "final_metrics": final_v,
            "epoch_history": v_hist,
        },
        labels=labels,
        warm_start_summary=warm_start_summary,
    )


def _seg_require_imports() -> _SegTrainingImports:
    """导入 segmentation 训练需要的本地依赖。"""

    try:
        import cv2
        import numpy as np
        import torch
    except ImportError as exc:
        raise ServiceConfigurationError(
            "segmentation 训练缺少必要依赖",
            details={"missing": str(exc)},
        ) from exc
    return _SegTrainingImports(cv2=cv2, np=np, torch=torch)


def _seg_resolve_device(extra: dict[str, object] | None) -> str:
    """按请求解析训练设备。"""

    import torch

    requested = str((extra or {}).get("device", "cpu")).strip().lower()
    if (
        requested == "cuda" or requested.startswith("cuda:")
    ) and torch.cuda.is_available():
        return requested
    return "cpu"


def _seg_autocast(imports: Any, precision: str, device: str):
    if precision == "fp16" and "cuda" in device:
        return imports.torch.amp.autocast(device)
    return nullcontext()


def _seg_load_manifest(
    dataset_storage: LocalDatasetStorage,
    manifest: dict[str, object],
) -> tuple[
    tuple[str, ...],
    list[_SegTrainingAnnotation],
    list[_SegTrainingAnnotation],
]:
    splits = manifest.get("splits")
    if not isinstance(splits, list):
        raise InvalidRequestError("segmentation 训练 manifest 缺少合法 splits")
    format_id = str(
        manifest.get("format_id") or COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT
    ).strip()
    yolo_category_names = (
        normalize_yolo_category_names(
            category_names=manifest.get("category_names"),
            format_label="YOLO segmentation",
        )
        if format_id == YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT
        else ()
    )
    all_cats: dict[int, str] = {}
    train_a, val_a = [], []
    for sp in splits:
        if not isinstance(sp, dict):
            continue
        sn = str(sp.get("name", ""))
        im_root = str(sp.get("image_root", ""))
        if format_id == YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT:
            label_root = str(sp.get("label_root", ""))
            image_root_path = dataset_storage.resolve(im_root)
            label_root_path = dataset_storage.resolve(label_root)
            if not image_root_path.is_dir():
                raise InvalidRequestError(
                    "segmentation 训练 split 缺少图片目录",
                    details={"split_name": sn, "image_root": im_root},
                )
            if not label_root_path.is_dir():
                raise InvalidRequestError(
                    "segmentation 训练 split 缺少标签目录",
                    details={"split_name": sn, "label_root": label_root},
                )
            payload = build_coco_payload_from_yolo_segmentation_split(
                split_name=sn,
                image_root=image_root_path,
                label_root=label_root_path,
                category_names=yolo_category_names,
            )
        else:
            af = str(sp.get("annotation_file", ""))
            ap = dataset_storage.resolve(af)
            if not ap.is_file():
                raise InvalidRequestError(f"标注文件不存在: {af}")
            payload = dataset_storage.read_json(af)
            if not isinstance(payload, dict):
                raise InvalidRequestError(f"标注格式无效: {af}")
        cats = payload.get("categories", [])
        if isinstance(cats, list):
            for c in cats:
                if isinstance(c, dict):
                    all_cats[int(c.get("id", -1))] = str(c.get("name", ""))
        img_map: dict[int, str] = {}
        for im in payload.get("images") or []:
            if isinstance(im, dict):
                img_map[int(im.get("id", -1))] = str(im.get("file_name", ""))
        result = []
        for ann in payload.get("annotations") or []:
            if not isinstance(ann, dict):
                continue
            img_id = int(ann.get("image_id", -1))
            fn = img_map.get(img_id, "")
            if not fn:
                continue
            bbox = ann.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            result.append(
                _SegTrainingAnnotation(
                    image_path=str(dataset_storage.resolve(f"{im_root}/{fn}")),
                    boxes_xywh=[bbox],
                    class_ids=[int(ann.get("category_id", 0))],
                    segmentations=_extract_segmentation_polygons(ann),
                )
            )
        if sn == "train":
            train_a = result
        elif sn == "val":
            val_a = result
    sorted_cats = sorted(all_cats.items())
    cat_id_to_idx = {cid: idx for idx, (cid, _) in enumerate(sorted_cats)}
    labels = tuple(name for _, name in sorted_cats)
    remapped_train = [
        _SegTrainingAnnotation(
            image_path=annotation.image_path,
            boxes_xywh=annotation.boxes_xywh,
            class_ids=[
                cat_id_to_idx.get(class_id, 0) for class_id in annotation.class_ids
            ],
            segmentations=annotation.segmentations,
        )
        for annotation in train_a
    ]
    remapped_val = [
        _SegTrainingAnnotation(
            image_path=annotation.image_path,
            boxes_xywh=annotation.boxes_xywh,
            class_ids=[
                cat_id_to_idx.get(class_id, 0) for class_id in annotation.class_ids
            ],
            segmentations=annotation.segmentations,
        )
        for annotation in val_a
    ]
    return labels, remapped_train, remapped_val


def _extract_segmentation_polygons(
    annotation: dict[str, object],
) -> list[list[list[float]] | None] | None:
    """从 COCO 标注提取 segmentation 多边形数据。"""

    seg = annotation.get("segmentation")
    if not isinstance(seg, list) or len(seg) == 0:
        return None
    if isinstance(seg[0], list):
        return seg
    return None


def _seg_build_batch(
    anns: list[_SegTrainingAnnotation],
    input_size: tuple[int, int],
    device: str,
    precision: str,
    imports: Any,
    *,
    yolov8_augmentation_options: Any | None = None,
    yolov8_available_samples: list[_SegTrainingAnnotation] | None = None,
) -> tuple[Any, list[dict[str, Any]]] | None:
    """构造 YOLOv8 segmentation 训练 batch。"""

    batch = build_yolov8_segmentation_training_batch(
        samples=anns,
        input_size=input_size,
        device=device,
        precision=precision,
        imports=imports,
        augmentation_options=yolov8_augmentation_options,
        available_samples=yolov8_available_samples,
    )
    if batch is None:
        return None
    return batch.images, batch.targets


def _seg_compute_mask_loss(
    pred,
    proto,
    p,
    nc,
    imports,
    fg_mask,
):
    """在 mask_coefficients 和 proto 存在时计算 mask 损失。"""

    return compute_yolov8_segmentation_mask_loss(
        torch_module=imports.torch,
        prediction=pred,
        proto=proto,
        foreground_mask=fg_mask,
        target_masks=p.mask_targets,
        target_mask_valid=p.mask_valid,
        matched_gt_indices=p.matched_gt_indices,
        num_classes=nc,
        target_boxes=p.box_targets,
    )


def _seg_make_anchors_from_feats(
    feature_maps: list[Any],
    strides: tuple[int, ...],
    device: Any,
    imports: Any,
) -> tuple[Any, Any]:
    """根据真实特征图生成 anchor points 和 stride tensor。"""

    anchor_list = []
    stride_list = []
    for feat, stride in zip(feature_maps, strides, strict=True):
        _, _, h, w = feat.shape
        grid_y, grid_x = imports.torch.meshgrid(
            imports.torch.arange(h, device=device),
            imports.torch.arange(w, device=device),
            indexing="ij",
        )
        anchors = imports.torch.stack((grid_x, grid_y), dim=-1).reshape(-1, 2) * stride
        strides_t = imports.torch.full((h * w, 1), stride, device=device)
        anchor_list.append(anchors)
        stride_list.append(strides_t)
    return imports.torch.cat(anchor_list), imports.torch.cat(stride_list)


def _seg_load_resume(request, imports) -> _SegResumedState | None:
    ckpt = imports.torch.load(
        str(request.resume_checkpoint_path),
        map_location="cpu",
        weights_only=False,
    )
    return _SegResumedState(
        model_state_dict=ckpt.get("model_state_dict", {}),
        optimizer_state_dict=ckpt.get("optimizer_state_dict", {}),
        scheduler_state_dict=ckpt.get("scheduler_state_dict"),
        scaler_state_dict=ckpt.get("scaler_state_dict"),
        metrics_history=ckpt.get("metrics_history", []),
        validation_history=ckpt.get("validation_history", []),
        best_metric_value=float(ckpt.get("best_metric_value", 0)),
        best_metric_name=str(ckpt.get("best_metric_name", "val_map50_95")),
        epoch=int(ckpt.get("epoch", 0)),
        global_iteration=int(ckpt.get("global_iteration", 0)),
        saved_batch_size=int(ckpt.get("saved_batch_size", 0)),
        saved_max_epochs=int(ckpt.get("saved_max_epochs", 0)),
        saved_lr=float(ckpt.get("saved_lr", 0)),
        saved_wd=float(ckpt.get("saved_wd", 0)),
        saved_eval_interval=int(ckpt.get("saved_eval_interval", 0)),
        saved_min_lr=float(ckpt.get("saved_min_lr", 0)),
        saved_class_loss_weight=float(ckpt.get("saved_class_loss_weight", 0)),
        saved_box_loss_weight=float(ckpt.get("saved_box_loss_weight", 0)),
        saved_dfl_loss_weight=float(ckpt.get("saved_dfl_loss_weight", 0)),
        saved_mask_loss_weight=float(ckpt.get("saved_mask_loss_weight", 0)),
        saved_assign_topk=int(ckpt.get("saved_assign_topk", 0)),
        saved_assign_alpha=float(ckpt.get("saved_assign_alpha", 0)),
        saved_assign_beta=float(ckpt.get("saved_assign_beta", 0)),
        saved_grad_clip=float(ckpt.get("saved_grad_clip", 0)),
        saved_eval_conf=float(ckpt.get("saved_eval_conf", 0)),
        saved_eval_nms=float(ckpt.get("saved_eval_nms", 0)),
    )


def _seg_validate_resume(
    state,
    batch_size,
    max_epochs,
    learning_rate,
    weight_decay,
    evaluation_interval,
    min_lr_ratio,
    class_loss_weight,
    box_loss_weight,
    dfl_loss_weight,
    mask_loss_weight,
    assign_topk,
    assign_alpha,
    assign_beta,
    grad_clip,
    evaluation_confidence_threshold,
    evaluation_nms_threshold,
):
    issues = []
    if state.saved_batch_size != batch_size:
        issues.append("batch_size")
    if state.saved_max_epochs != max_epochs:
        issues.append("max_epochs")
    if abs(state.saved_lr - learning_rate) > 1e-8:
        issues.append("learning_rate")
    if issues:
        raise InvalidRequestError(
            "resume 请求的训练参数与 checkpoint 不一致", details={"mismatches": issues}
        )


def _seg_apply_resume(model, opt, sched, scaler, state, imports, device):
    filtered = {}
    for k, v in state.model_state_dict.items():
        p = model.state_dict().get(k)
        if p is not None and p.shape == v.shape:
            filtered[k] = v
    model.load_state_dict(filtered, strict=False)
    opt.load_state_dict(state.optimizer_state_dict)
    if hasattr(opt, "param_groups"):
        for pg in opt.param_groups:
            for p in pg.get("params", []):
                if hasattr(p, "device") and str(p.device) != device:
                    pg["params"] = [
                        parameter.to(device) if hasattr(parameter, "to") else parameter
                        for parameter in pg["params"]
                    ]
    if state.scheduler_state_dict is not None and sched is not None:
        sched.load_state_dict(state.scheduler_state_dict)
    if state.scaler_state_dict is not None and scaler is not None:
        scaler.load_state_dict(state.scaler_state_dict)


def _seg_build_checkpoint(
    *,
    epoch,
    g_iter,
    model,
    optimizer,
    scheduler,
    scaler,
    m_hist,
    v_hist,
    best_val,
    best_name,
    bs,
    me,
    lr,
    wd,
    eval_interval,
    min_lr,
    cl_w,
    box_w,
    dfl_w,
    mask_w,
    assign_topk,
    assign_alpha,
    assign_beta,
    grad_clip,
    eval_conf,
    eval_nms,
    imports,
):
    payload = {
        "epoch": epoch + 1,
        "global_iteration": g_iter,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "scheduler_state_dict": scheduler.state_dict() if scheduler else None,
        "scaler_state_dict": scaler.state_dict() if scaler else None,
        "metrics_history": m_hist,
        "validation_history": v_hist,
        "best_metric_value": best_val,
        "best_metric_name": best_name,
        "saved_batch_size": bs,
        "saved_max_epochs": me,
        "saved_lr": lr,
        "saved_wd": wd,
        "saved_eval_interval": eval_interval,
        "saved_min_lr": min_lr,
        "saved_class_loss_weight": cl_w,
        "saved_box_loss_weight": box_w,
        "saved_dfl_loss_weight": dfl_w,
        "saved_mask_loss_weight": mask_w,
        "saved_assign_topk": assign_topk,
        "saved_assign_alpha": assign_alpha,
        "saved_assign_beta": assign_beta,
        "saved_grad_clip": grad_clip,
        "saved_eval_conf": eval_conf,
        "saved_eval_nms": eval_nms,
    }
    buf = io.BytesIO()
    imports.torch.save(payload, buf)
    return buf.getvalue()
