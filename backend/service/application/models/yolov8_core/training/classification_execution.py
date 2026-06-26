"""YOLOv8 classification 训练执行入口。"""

from __future__ import annotations

import io
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.models.yolo_core_common.weights import (
    YOLO_WARM_START_MINIMUM_LOADABLE_RATIO,
    build_yolo_disabled_warm_start_summary,
    build_yolo_warm_start_summary,
)
from backend.service.application.models.yolov8_core import build_yolov8_model
from backend.service.application.models.yolov8_core.data import (
    build_yolov8_classification_training_batch,
)
from backend.service.application.models.yolov8_core.evaluation import (
    evaluate_yolov8_classification_samples,
)
from backend.service.application.models.yolov8_core.losses import (
    compute_yolov8_classification_loss,
)
from backend.service.application.models.yolov8_core.weights import (
    load_yolov8_checkpoint_file,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


YOLOV8_CLASSIFICATION_IMPLEMENTATION_MODE = "yolov8-classification-core"
YOLOV8_CLASSIFICATION_DEFAULT_INPUT_SIZE = (224, 224)
YOLOV8_CLASSIFICATION_DEFAULT_BATCH_SIZE = 16
YOLOV8_CLASSIFICATION_DEFAULT_MAX_EPOCHS = 30
YOLOV8_CLASSIFICATION_DEFAULT_EVALUATION_INTERVAL = 1
YOLOV8_CLASSIFICATION_DEFAULT_LR = 1e-3
YOLOV8_CLASSIFICATION_DEFAULT_WEIGHT_DECAY = 1e-4
YOLOV8_CLASSIFICATION_DEFAULT_MIN_LR_RATIO = 0.01


@dataclass(frozen=True)
class YoloV8ClassificationTrainingBatchProgress:
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
class YoloV8ClassificationTrainingEpochProgress:
    epoch: int
    max_epochs: int
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class YoloV8ClassificationTrainingSavePoint:
    latest_checkpoint_bytes: bytes
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    learning_rate: float


@dataclass(frozen=True)
class YoloV8ClassificationTrainingControlCommand:
    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


class YoloV8ClassificationTrainingPausedError(Exception):
    """训练被显式暂停。"""


class YoloV8ClassificationTrainingTerminatedError(Exception):
    """训练被显式终止。"""


@dataclass(frozen=True)
class _LoadedClassificationResumeState:
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
    saved_max_epochs: int
    saved_batch_size: int
    saved_learning_rate: float
    saved_weight_decay: float
    saved_evaluation_interval: int
    saved_min_lr_ratio: float


@dataclass(frozen=True)
class _ResolvedClassificationTrainingAnnotation:
    image_path: str
    class_id: int


@dataclass(frozen=True)
class _ClassificationTrainingImports:
    """描述 classification 训练依赖的本地模块。"""

    cv2: Any
    np: Any
    torch: Any


@dataclass(frozen=True)
class YoloV8ClassificationTrainingExecutionRequest:
    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_type: str
    model_scale: str
    batch_size: int = YOLOV8_CLASSIFICATION_DEFAULT_BATCH_SIZE
    max_epochs: int = YOLOV8_CLASSIFICATION_DEFAULT_MAX_EPOCHS
    evaluation_interval: int = YOLOV8_CLASSIFICATION_DEFAULT_EVALUATION_INTERVAL
    input_size: tuple[int, int] | None = None
    precision: str = "fp32"
    warm_start_checkpoint_path: Path | None = None
    warm_start_source_summary: dict[str, object] | None = None
    resume_checkpoint_path: Path | None = None
    extra_options: dict[str, object] | None = None
    epoch_callback: (
        Callable[
            [YoloV8ClassificationTrainingEpochProgress],
            YoloV8ClassificationTrainingControlCommand | None,
        ]
        | None
    ) = None
    savepoint_callback: (
        Callable[[YoloV8ClassificationTrainingSavePoint], None] | None
    ) = None


@dataclass(frozen=True)
class YoloV8ClassificationTrainingExecutionResult:
    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    labels: tuple[str, ...]
    warm_start_summary: dict[str, object]


def run_yolov8_classification_training(
    request: YoloV8ClassificationTrainingExecutionRequest,
) -> YoloV8ClassificationTrainingExecutionResult:
    """执行一次 YOLOv8 classification 训练。"""

    if request.model_type != "yolov8":
        raise InvalidRequestError(
            "YOLOv8 classification 训练入口只接受 model_type=yolov8",
            details={"model_type": request.model_type},
        )

    imports = _require_training_imports()
    device_name = _resolve_training_device(request.extra_options)
    precision = request.precision
    input_size = request.input_size or YOLOV8_CLASSIFICATION_DEFAULT_INPUT_SIZE

    labels, train_annotations, val_annotations = _load_classification_manifest(
        dataset_storage=request.dataset_storage,
        manifest_payload=request.manifest_payload,
        cv2_module=imports.cv2,
    )

    model = build_yolov8_model(
        task_type="classification",
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

    resume_state: _LoadedClassificationResumeState | None = None
    if (
        request.resume_checkpoint_path is not None
        and request.resume_checkpoint_path.is_file()
    ):
        resume_state = _load_resume_state(request, imports)

    extra = request.extra_options or {}
    learning_rate = float(
        extra.get("learning_rate", YOLOV8_CLASSIFICATION_DEFAULT_LR)
    )
    weight_decay = float(
        extra.get(
            "weight_decay",
            YOLOV8_CLASSIFICATION_DEFAULT_WEIGHT_DECAY,
        )
    )
    min_lr_ratio = float(
        extra.get(
            "min_lr_ratio",
            YOLOV8_CLASSIFICATION_DEFAULT_MIN_LR_RATIO,
        )
    )
    batch_size = int(extra.get("batch_size", request.batch_size))
    max_epochs = int(extra.get("max_epochs", request.max_epochs))
    evaluation_interval = int(
        extra.get("evaluation_interval", request.evaluation_interval)
    )

    if resume_state is not None:
        _validate_resume_parameters(
            resume_state,
            batch_size=batch_size,
            max_epochs=max_epochs,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            evaluation_interval=evaluation_interval,
            min_lr_ratio=min_lr_ratio,
            extra=extra,
        )

    model.to(device_name)
    trainable_params = [p for p in model.parameters() if p.requires_grad]
    optimizer = imports.torch.optim.AdamW(
        trainable_params,
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    scaler = (
        imports.torch.GradScaler(
            device_name,
            enabled=(precision == "fp16"),
        )
        if hasattr(imports.torch, "GradScaler")
        else None
    )
    iterations_per_epoch = max(
        1,
        (len(train_annotations) + batch_size - 1) // batch_size,
    )
    total_iterations = max_epochs * iterations_per_epoch
    scheduler = imports.torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=total_iterations,
        eta_min=learning_rate * min_lr_ratio,
    )

    start_epoch = 0
    global_iteration = 0
    metrics_history: list[dict[str, float]] = []
    validation_history: list[dict[str, float]] = []
    best_metric_value = 0.0
    best_metric_name = "val_top1_accuracy"
    checkpoint_bytes = b""
    if resume_state is not None:
        _resolve_model_state(model, resume_state.model_state_dict, imports, device_name)
        optimizer.load_state_dict(resume_state.optimizer_state_dict)
        _resolve_optimizer_device(optimizer, device_name)
        if resume_state.scheduler_state_dict is not None:
            scheduler.load_state_dict(resume_state.scheduler_state_dict)
        if resume_state.scaler_state_dict is not None and scaler is not None:
            scaler.load_state_dict(resume_state.scaler_state_dict)
        metrics_history = list(resume_state.metrics_history)
        validation_history = list(resume_state.validation_history)
        best_metric_value = resume_state.best_metric_value
        best_metric_name = resume_state.best_metric_name
        start_epoch = resume_state.epoch
        global_iteration = resume_state.global_iteration

    for epoch in range(start_epoch, max_epochs):
        model.train()
        train_loss_sum = 0.0
        train_correct = 0
        train_total = 0
        epoch_iterations = 0
        for batch_start in range(0, len(train_annotations), batch_size):
            batch_annotations = train_annotations[
                batch_start : batch_start + batch_size
            ]
            batch = build_yolov8_classification_training_batch(
                samples=batch_annotations,
                input_size=input_size,
                device=device_name,
                precision=precision,
                imports=imports,
            )
            if batch is None:
                continue
            batch_images = batch.images
            batch_targets = batch.targets
            optimizer.zero_grad(set_to_none=True)
            with _autocast_context(imports, precision, device_name):
                outputs = model(batch_images)
                loss, probabilities = compute_yolov8_classification_loss(
                    torch_module=imports.torch,
                    outputs=outputs,
                    targets=batch_targets,
                )
            if scaler is not None:
                scaler.scale(loss).backward()
                scaler.step(optimizer)
                scaler.update()
            else:
                loss.backward()
                optimizer.step()
            scheduler.step()
            _, predicted = imports.torch.max(probabilities, 1)
            train_correct += int((predicted == batch_targets).sum().item())
            train_total += int(batch_targets.size(0))
            train_loss_sum += float(loss.item()) * int(batch_targets.size(0))
            epoch_iterations += 1
            global_iteration += 1
        train_accuracy = train_correct / max(1, train_total)
        train_loss = train_loss_sum / max(1, train_total)
        epoch_metrics = {
            "loss": round(train_loss, 6),
            "accuracy": round(train_accuracy, 6),
        }
        metrics_history.append({"epoch": epoch, **epoch_metrics})
        epoch_progress = YoloV8ClassificationTrainingEpochProgress(
            epoch=epoch,
            max_epochs=max_epochs,
            input_size=input_size,
            learning_rate=float(scheduler.get_last_lr()[0]),
            train_metrics=epoch_metrics,
        )
        cmd = None
        if request.epoch_callback is not None:
            cmd = request.epoch_callback(epoch_progress)
        if cmd is not None and cmd.terminate_training:
            raise YoloV8ClassificationTrainingTerminatedError()
        val_metrics: dict[str, float] = {}
        should_evaluate = (
            len(val_annotations) > 0 and epoch > 0 and epoch % evaluation_interval == 0
        ) or epoch == max_epochs - 1
        if should_evaluate:
            val_metrics = evaluate_yolov8_classification_samples(
                model=model,
                samples=val_annotations,
                labels=labels,
                batch_size=batch_size,
                input_size=input_size,
                device=device_name,
                precision=precision,
                imports=imports,
            )
            validation_history.append({"epoch": epoch, **val_metrics})
        current_val_metric = float(val_metrics.get("top1_accuracy", 0.0))
        is_best = current_val_metric > best_metric_value
        if is_best:
            best_metric_value = current_val_metric
            best_metric_name = "val_top1_accuracy"
        checkpoint_bytes = _build_checkpoint_bytes(
            epoch=epoch,
            global_iteration=global_iteration,
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            metrics_history=metrics_history,
            validation_history=validation_history,
            best_metric_value=best_metric_value,
            best_metric_name=best_metric_name,
            batch_size=batch_size,
            max_epochs=max_epochs,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            evaluation_interval=evaluation_interval,
            min_lr_ratio=min_lr_ratio,
            imports=imports,
        )
        if cmd is not None and request.savepoint_callback is not None:
            request.savepoint_callback(
                YoloV8ClassificationTrainingSavePoint(
                    latest_checkpoint_bytes=checkpoint_bytes,
                    train_metrics=epoch_metrics,
                    validation_metrics=val_metrics,
                    best_metric_value=best_metric_value,
                    best_metric_name=best_metric_name,
                    epoch=epoch + 1,
                    learning_rate=float(scheduler.get_last_lr()[0]),
                )
            )
        if cmd is not None and cmd.pause_training:
            raise YoloV8ClassificationTrainingPausedError()
    final_val_metrics = validation_history[-1] if validation_history else {}
    return YoloV8ClassificationTrainingExecutionResult(
        best_metric_value=best_metric_value,
        best_metric_name=best_metric_name,
        latest_checkpoint_bytes=checkpoint_bytes,
        metrics_payload={
            "final_metrics": (
                {
                    "loss": metrics_history[-1].get("loss", 0.0),
                    "accuracy": metrics_history[-1].get("accuracy", 0.0),
                }
                if metrics_history
                else {}
            ),
            "epoch_history": metrics_history,
            "scheduler": "CosineAnnealingLR",
        },
        validation_metrics_payload={
            "final_metrics": final_val_metrics,
            "epoch_history": validation_history,
        },
        labels=labels,
        warm_start_summary=warm_start_summary,
    )


def _load_classification_manifest(
    *,
    dataset_storage: LocalDatasetStorage,
    manifest_payload: dict[str, object],
    cv2_module: Any,
) -> tuple[
    tuple[str, ...],
    list[_ResolvedClassificationTrainingAnnotation],
    list[_ResolvedClassificationTrainingAnnotation],
]:
    splits = manifest_payload.get("splits")
    if not isinstance(splits, list) or len(splits) < 1:
        raise InvalidRequestError("classification 训练 manifest 缺少合法 splits")
    all_labels: dict[int, str] = {}
    train_annotations: list[_ResolvedClassificationTrainingAnnotation] = []
    val_annotations: list[_ResolvedClassificationTrainingAnnotation] = []
    for split in splits:
        if not isinstance(split, dict):
            continue
        split_name = str(split.get("name", ""))
        image_root = str(split.get("image_root", ""))
        annotation_file = str(split.get("annotation_file", ""))
        ann_path = dataset_storage.resolve(annotation_file)
        if not ann_path.is_file():
            raise InvalidRequestError(
                f"classification 标注文件不存在: {annotation_file}"
            )
        ann_payload = dataset_storage.read_json(annotation_file)
        if not isinstance(ann_payload, dict):
            raise InvalidRequestError(f"classification 标注格式无效: {annotation_file}")
        categories = ann_payload.get("categories", [])
        if isinstance(categories, list):
            for cat in categories:
                if isinstance(cat, dict):
                    cid = int(cat.get("id", -1))
                    cname = str(cat.get("name", ""))
                    if cid >= 0:
                        all_labels[cid] = cname
        annotations = ann_payload.get("annotations", [])
        image_map: dict[int, str] = {}
        images = ann_payload.get("images", [])
        if isinstance(images, list):
            for img in images:
                if isinstance(img, dict):
                    image_map[int(img.get("id", -1))] = str(img.get("file_name", ""))
        resolved: list[_ResolvedClassificationTrainingAnnotation] = []
        if isinstance(annotations, list):
            for ann in annotations:
                if not isinstance(ann, dict):
                    continue
                image_id = int(ann.get("image_id", -1))
                class_id = int(ann.get("category_id", -1))
                file_name = image_map.get(image_id, "")
                if not file_name:
                    continue
                resolved_path = str(
                    dataset_storage.resolve(f"{image_root}/{file_name}")
                )
                resolved.append(
                    _ResolvedClassificationTrainingAnnotation(
                        image_path=resolved_path,
                        class_id=class_id,
                    )
                )
        if split_name == "train":
            train_annotations = resolved
        elif split_name == "val":
            val_annotations = resolved
    sorted_labels = sorted(all_labels.items())
    labels = tuple(name for _cid, name in sorted_labels)
    category_id_to_index = {cid: idx for idx, (cid, _name) in enumerate(sorted_labels)}
    remapped_train = [
        _ResolvedClassificationTrainingAnnotation(
            image_path=annotation.image_path,
            class_id=category_id_to_index.get(annotation.class_id, 0),
        )
        for annotation in train_annotations
    ]
    remapped_val = [
        _ResolvedClassificationTrainingAnnotation(
            image_path=annotation.image_path,
            class_id=category_id_to_index.get(annotation.class_id, 0),
        )
        for annotation in val_annotations
    ]
    return labels, remapped_train, remapped_val


def _require_training_imports() -> _ClassificationTrainingImports:
    """导入 classification 训练需要的本地依赖。"""

    try:
        import cv2
        import numpy as np
        import torch
    except ImportError as exc:
        raise ServiceConfigurationError(
            "classification 训练缺少必要依赖",
            details={"missing": str(exc)},
        ) from exc
    return _ClassificationTrainingImports(cv2=cv2, np=np, torch=torch)


def _resolve_training_device(extra_options: dict[str, object] | None) -> str:
    """按请求解析训练设备。"""

    import torch

    requested = str((extra_options or {}).get("device", "cpu")).strip().lower()
    if requested == "cuda" and torch.cuda.is_available():
        return "cuda:0"
    if requested.startswith("cuda:") and torch.cuda.is_available():
        return requested
    return "cpu"


def _autocast_context(imports: Any, precision: str, device_name: str):
    if precision == "fp16" and "cuda" in device_name:
        return imports.torch.amp.autocast(device_name)
    return nullcontext()


def _build_checkpoint_bytes(
    *,
    epoch: int,
    global_iteration: int,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any | None,
    metrics_history: list[dict[str, float]],
    validation_history: list[dict[str, float]],
    best_metric_value: float,
    best_metric_name: str,
    batch_size: int,
    max_epochs: int,
    learning_rate: float,
    weight_decay: float,
    evaluation_interval: int,
    min_lr_ratio: float,
    imports: Any,
) -> bytes:
    payload = {
        "epoch": epoch + 1,
        "global_iteration": global_iteration,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "scheduler_state_dict": scheduler.state_dict(),
        "scaler_state_dict": scaler.state_dict() if scaler is not None else None,
        "metrics_history": metrics_history,
        "validation_history": validation_history,
        "best_metric_value": best_metric_value,
        "best_metric_name": best_metric_name,
        "saved_batch_size": batch_size,
        "saved_max_epochs": max_epochs,
        "saved_learning_rate": learning_rate,
        "saved_weight_decay": weight_decay,
        "saved_evaluation_interval": evaluation_interval,
        "saved_min_lr_ratio": min_lr_ratio,
    }
    buffer = io.BytesIO()
    imports.torch.save(payload, buffer)
    return buffer.getvalue()


def _load_resume_state(
    request: YoloV8ClassificationTrainingExecutionRequest,
    imports: Any,
) -> _LoadedClassificationResumeState:
    checkpoint = imports.torch.load(
        str(request.resume_checkpoint_path),
        map_location="cpu",
        weights_only=False,
    )
    return _LoadedClassificationResumeState(
        model_state_dict=checkpoint.get("model_state_dict", {}),
        optimizer_state_dict=checkpoint.get("optimizer_state_dict", {}),
        scheduler_state_dict=checkpoint.get("scheduler_state_dict"),
        scaler_state_dict=checkpoint.get("scaler_state_dict"),
        metrics_history=checkpoint.get("metrics_history", []),
        validation_history=checkpoint.get("validation_history", []),
        best_metric_value=float(checkpoint.get("best_metric_value", 0.0)),
        best_metric_name=str(checkpoint.get("best_metric_name", "val_top1_accuracy")),
        epoch=int(checkpoint.get("epoch", 0)),
        global_iteration=int(checkpoint.get("global_iteration", 0)),
        saved_max_epochs=int(checkpoint.get("saved_max_epochs", 0)),
        saved_batch_size=int(checkpoint.get("saved_batch_size", 0)),
        saved_learning_rate=float(checkpoint.get("saved_learning_rate", 0.0)),
        saved_weight_decay=float(checkpoint.get("saved_weight_decay", 0.0)),
        saved_evaluation_interval=int(checkpoint.get("saved_evaluation_interval", 0)),
        saved_min_lr_ratio=float(checkpoint.get("saved_min_lr_ratio", 0.0)),
    )


def _validate_resume_parameters(
    state: _LoadedClassificationResumeState,
    *,
    batch_size: int,
    max_epochs: int,
    learning_rate: float,
    weight_decay: float,
    evaluation_interval: int,
    min_lr_ratio: float,
    extra: dict[str, object],
) -> None:
    mismatches = []
    if state.saved_batch_size != batch_size:
        mismatches.append(f"batch_size ({state.saved_batch_size} -> {batch_size})")
    if state.saved_max_epochs != max_epochs and max_epochs > 0:
        mismatches.append(f"max_epochs ({state.saved_max_epochs} -> {max_epochs})")
    if abs(state.saved_learning_rate - learning_rate) > 1e-8:
        mismatches.append(
            f"learning_rate ({state.saved_learning_rate} -> {learning_rate})"
        )
    if abs(state.saved_weight_decay - weight_decay) > 1e-8:
        mismatches.append(
            f"weight_decay ({state.saved_weight_decay} -> {weight_decay})"
        )
    if state.saved_evaluation_interval != evaluation_interval:
        mismatches.append(
            f"evaluation_interval ({state.saved_evaluation_interval} -> {evaluation_interval})"
        )
    if abs(state.saved_min_lr_ratio - min_lr_ratio) > 1e-8:
        mismatches.append(
            f"min_lr_ratio ({state.saved_min_lr_ratio} -> {min_lr_ratio})"
        )
    if mismatches:
        raise InvalidRequestError(
            "resume 请求的训练参数与 checkpoint 记录不一致，请检查配置",
            details={"mismatches": mismatches},
        )


def _resolve_model_state(
    model: Any,
    state_dict: dict[str, object],
    imports: Any,
    device_name: str,
) -> None:
    filtered = {}
    skipped = []
    for key, value in state_dict.items():
        param = model.state_dict().get(key)
        if param is not None and param.shape == value.shape:
            filtered[key] = value
        else:
            skipped.append(key)
    model.load_state_dict(filtered, strict=False)
    if "cuda" in device_name:
        try:
            model.to(device_name)
        except Exception:
            pass


def _resolve_optimizer_device(optimizer: Any, device_name: str) -> None:
    if "cuda" not in device_name:
        return
    for state in optimizer.state.values():
        for k, v in state.items():
            if hasattr(v, "to") and hasattr(v, "device"):
                try:
                    state[k] = v.to(device_name)
                except Exception:
                    pass
