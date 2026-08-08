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
from backend.service.application.models.training.device_selection import (
    resolve_single_training_device_name,
    resolve_torch_amp_device_type,
)
from backend.service.application.models.training.classification_evaluation_report import (
    build_unavailable_test_metrics_report,
)
from backend.service.application.models.yolo_core_common.weights import (
    YOLO_WARM_START_MINIMUM_LOADABLE_RATIO,
    build_yolo_disabled_warm_start_summary,
    build_yolo_warm_start_summary,
)
from backend.service.application.models.yolo_core_common.data import (
    build_yolo_classification_augmentation_options,
    build_yolo_classification_augmentation_summary,
)
from backend.service.application.models.yolo_core_common.training import (
    YoloModelEMA,
    YoloUltralyticsOptimizerStep,
    build_yolo_ultralytics_optimizer,
    build_yolo_ultralytics_scheduler,
    build_yolo_classification_training_dataloader,
    load_yolo_classification_dataloader_imports,
    move_yolo_classification_batch_to_device,
    resolve_yolo_optimizer_base_learning_rate,
    replace_yolo_classification_dataloader_plan_seed,
    resolve_yolo_classification_dataloader_plan,
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
YOLOV8_CLASSIFICATION_DEFAULT_LR = 1e-2
YOLOV8_CLASSIFICATION_DEFAULT_WEIGHT_DECAY = 5e-4
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
    evaluation_interval: int
    validation_ran: bool
    input_size: tuple[int, int]
    learning_rate: float
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    train_metrics_snapshot: dict[str, object]
    validation_metrics_snapshot: dict[str, object]
    current_metric_name: str
    current_metric_value: float | None
    best_metric_name: str
    best_metric_value: float


@dataclass(frozen=True)
class YoloV8ClassificationTrainingSavePoint:
    latest_checkpoint_bytes: bytes
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    learning_rate: float
    is_best: bool = False


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
    ema_state_dict: dict[str, object] | None
    ema_updates: int
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
    previous_best_checkpoint_path: Path | None = None
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
    best_checkpoint_bytes: bytes | None = None
    test_metrics_payload: dict[str, object] | None = None


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

    (
        labels,
        train_annotations,
        val_annotations,
        test_annotations,
    ) = _load_classification_manifest(
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
            restore_checkpoint_attributes=False,
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
    augmentation_options = build_yolo_classification_augmentation_options(extra)
    dataloader_plan = resolve_yolo_classification_dataloader_plan(
        extra_options=extra,
        device=device_name,
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
    optimizer, training_schedule = build_yolo_ultralytics_optimizer(
        torch_module=imports.torch,
        model=model,
        num_classes=len(labels),
        batch_size=batch_size,
        train_sample_count=len(train_annotations),
        max_epochs=max_epochs,
        optimizer_name=str(extra.get("optimizer", "auto")),
        learning_rate=learning_rate,
        weight_decay=weight_decay,
        final_lr_ratio=min_lr_ratio,
        cosine_schedule=bool(extra.get("cos_lr", False)),
    )
    scaler = (
        imports.torch.GradScaler(
            resolve_torch_amp_device_type(device_name),
            enabled=(precision == "fp16"),
        )
        if hasattr(imports.torch, "GradScaler")
        else None
    )
    scheduler = build_yolo_ultralytics_scheduler(
        torch_module=imports.torch,
        optimizer=optimizer,
        max_epochs=max_epochs,
        final_lr_ratio=min_lr_ratio,
        cosine_schedule=training_schedule.cosine_schedule,
    )

    start_epoch = 0
    global_iteration = 0
    metrics_history: list[dict[str, float]] = []
    validation_history: list[dict[str, float]] = []
    # accuracy 合法下界为 0；使用 -1 保证首次 validation 即使为 0 也会成为真实 best。
    best_metric_value = -1.0
    best_metric_name = "val_top1_accuracy"
    checkpoint_bytes = b""
    best_checkpoint_bytes = b""
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
    ema = YoloModelEMA(
        model=model,
        updates=resume_state.ema_updates if resume_state is not None else 0,
    )
    if resume_state is not None and resume_state.ema_state_dict is not None:
        ema.load_state_dict(resume_state.ema_state_dict, strict=False)
    optimizer_step = YoloUltralyticsOptimizerStep(
        torch_module=imports.torch,
        model=model,
        optimizer=optimizer,
        scaler=scaler,
        schedule=training_schedule,
        ema=ema,
        grad_clip_norm=float(extra.get("grad_clip_norm", 10.0)),
        initial_iteration=global_iteration,
    )

    for epoch in range(start_epoch, max_epochs):
        model.train()
        train_loss_sum = 0.0
        train_correct = 0
        train_total = 0
        train_dataloader = build_yolo_classification_training_dataloader(
            torch_module=imports.torch,
            samples=train_annotations,
            batch_size=batch_size,
            input_size=input_size,
            training=True,
            augmentation_options=augmentation_options,
            plan=replace_yolo_classification_dataloader_plan_seed(
                plan=dataloader_plan,
                seed=epoch,
            ),
            shuffle=True,
            build_batch=build_yolov8_classification_training_batch,
            load_imports=load_yolo_classification_dataloader_imports,
        )
        max_iterations = max(1, len(train_dataloader))
        for iteration, cpu_batch in enumerate(train_dataloader, start=1):
            if cpu_batch is None:
                continue
            batch = move_yolo_classification_batch_to_device(
                batch=cpu_batch,
                device=device_name,
                precision=precision,
                torch_module=imports.torch,
            )
            if batch is None:
                continue
            batch_images = batch.images
            batch_targets = batch.targets
            global_iteration += 1
            optimizer_step.prepare_batch(
                iteration_index=global_iteration,
                epoch=epoch + 1,
                batch_size=int(batch_targets.size(0)),
            )
            with _autocast_context(imports, precision, device_name):
                outputs = model(batch_images)
                loss, probabilities = compute_yolov8_classification_loss(
                    torch_module=imports.torch,
                    outputs=outputs,
                    targets=batch_targets,
                )
            optimizer_step.backward_and_step(
                loss=loss,
                iteration_index=global_iteration,
                is_last_batch=(
                    epoch + 1 == max_epochs and iteration == max_iterations
                ),
            )
            _, predicted = imports.torch.max(probabilities, 1)
            train_correct += int((predicted == batch_targets).sum().item())
            train_total += int(batch_targets.size(0))
            train_loss_sum += float(loss.item()) * int(batch_targets.size(0))
        train_accuracy = train_correct / max(1, train_total)
        train_loss = train_loss_sum / max(1, train_total)
        epoch_metrics = {
            "loss": round(train_loss, 6),
            "accuracy": round(train_accuracy, 6),
        }
        metrics_history.append({"epoch": epoch, **epoch_metrics})
        val_metrics: dict[str, float] = {}
        should_evaluate = (
            len(val_annotations) > 0 and epoch > 0 and epoch % evaluation_interval == 0
        ) or epoch == max_epochs - 1
        if should_evaluate:
            val_metrics = evaluate_yolov8_classification_samples(
                model=ema.model,
                samples=val_annotations,
                labels=labels,
                batch_size=batch_size,
                input_size=input_size,
                device=device_name,
                precision=precision,
                imports=imports,
                dataloader_plan=replace_yolo_classification_dataloader_plan_seed(
                    plan=dataloader_plan,
                    seed=100_000 + epoch,
                ),
            )
            validation_history.append({"epoch": epoch, **val_metrics})
        current_val_metric = float(val_metrics.get("top1_accuracy", 0.0))
        current_metric_value = current_val_metric if should_evaluate else None
        is_best = should_evaluate and current_val_metric > best_metric_value
        if is_best:
            best_metric_value = current_val_metric
            best_metric_name = "val_top1_accuracy"
        scheduler.step()
        checkpoint_bytes = _build_checkpoint_bytes(
            epoch=epoch,
            global_iteration=global_iteration,
            model=model,
            ema=ema,
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
        if is_best:
            best_checkpoint_bytes = checkpoint_bytes
        epoch_progress = YoloV8ClassificationTrainingEpochProgress(
            epoch=epoch,
            max_epochs=max_epochs,
            evaluation_interval=evaluation_interval,
            validation_ran=should_evaluate,
            input_size=input_size,
            learning_rate=float(scheduler.get_last_lr()[0]),
            train_metrics={"epoch": epoch, **epoch_metrics},
            validation_metrics={"epoch": epoch, **val_metrics} if val_metrics else {},
            train_metrics_snapshot={
                "final_metrics": metrics_history[-1] if metrics_history else {},
                "epoch_history": [dict(item) for item in metrics_history],
                "scheduler": "LambdaLR",
                "optimizer": training_schedule.optimizer_name,
                "accumulate": training_schedule.accumulate,
                "scaled_weight_decay": training_schedule.scaled_weight_decay,
            },
            validation_metrics_snapshot={
                "final_metrics": validation_history[-1] if validation_history else {},
                "epoch_history": [dict(item) for item in validation_history],
            },
            current_metric_name=best_metric_name,
            current_metric_value=current_metric_value,
            best_metric_name=best_metric_name,
            best_metric_value=best_metric_value,
        )
        cmd = None
        if request.epoch_callback is not None:
            cmd = request.epoch_callback(epoch_progress)
        manual_save_requested = cmd is not None and cmd.save_checkpoint
        if request.savepoint_callback is not None and (
            is_best or manual_save_requested
        ):
            request.savepoint_callback(
                YoloV8ClassificationTrainingSavePoint(
                    latest_checkpoint_bytes=checkpoint_bytes,
                    train_metrics=epoch_progress.train_metrics,
                    validation_metrics=epoch_progress.validation_metrics,
                    best_metric_value=best_metric_value,
                    best_metric_name=best_metric_name,
                    epoch=epoch + 1,
                    learning_rate=float(scheduler.get_last_lr()[0]),
                    is_best=is_best,
                )
            )
        if cmd is not None and cmd.pause_training:
            raise YoloV8ClassificationTrainingPausedError()
        if cmd is not None and cmd.terminate_training:
            raise YoloV8ClassificationTrainingTerminatedError()
    final_val_metrics = validation_history[-1] if validation_history else {}
    if (
        not best_checkpoint_bytes
        and request.previous_best_checkpoint_path is not None
        and request.previous_best_checkpoint_path.is_file()
    ):
        best_checkpoint_bytes = request.previous_best_checkpoint_path.read_bytes()
    if not best_checkpoint_bytes:
        best_checkpoint_bytes = checkpoint_bytes
    test_metrics_payload = build_unavailable_test_metrics_report(
        reason="dataset export 未提供独立 test split"
    )
    if test_annotations:
        checkpoint_payload = imports.torch.load(
            io.BytesIO(best_checkpoint_bytes),
            map_location="cpu",
            weights_only=False,
        )
        ema_state_dict = (
            checkpoint_payload.get("ema_state_dict")
            if isinstance(checkpoint_payload, dict)
            else None
        )
        if not isinstance(ema_state_dict, dict):
            raise ServiceConfigurationError(
                "YOLOv8 classification best checkpoint 缺少 ema_state_dict"
            )
        ema.model.load_state_dict(ema_state_dict, strict=True)
        ema.model.to(device_name)
        test_metrics_payload = evaluate_yolov8_classification_samples(
            model=ema.model,
            samples=test_annotations,
            labels=labels,
            batch_size=batch_size,
            input_size=input_size,
            device=device_name,
            precision=precision,
            imports=imports,
            dataloader_plan=replace_yolo_classification_dataloader_plan_seed(
                plan=dataloader_plan,
                seed=200_000,
            ),
            include_details=True,
            split_name="test",
            checkpoint_role="best",
        )
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
            "scheduler": "LambdaLR",
            "optimizer": training_schedule.optimizer_name,
            "initial_learning_rate": training_schedule.initial_lr,
            "final_learning_rate": resolve_yolo_optimizer_base_learning_rate(
                optimizer=optimizer,
                initial_learning_rate=training_schedule.initial_lr,
            ),
            "accumulate": training_schedule.accumulate,
            "scaled_weight_decay": training_schedule.scaled_weight_decay,
            "augmentation": build_yolo_classification_augmentation_summary(
                augmentation_options
            ),
        },
        validation_metrics_payload={
            "final_metrics": final_val_metrics,
            "epoch_history": validation_history,
        },
        labels=labels,
        warm_start_summary=warm_start_summary,
        best_checkpoint_bytes=best_checkpoint_bytes,
        test_metrics_payload=test_metrics_payload,
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
    list[_ResolvedClassificationTrainingAnnotation],
]:
    splits = manifest_payload.get("splits")
    if not isinstance(splits, list) or len(splits) < 1:
        raise InvalidRequestError("classification 训练 manifest 缺少合法 splits")
    all_labels: dict[int, str] = {}
    train_annotations: list[_ResolvedClassificationTrainingAnnotation] = []
    val_annotations: list[_ResolvedClassificationTrainingAnnotation] = []
    test_annotations: list[_ResolvedClassificationTrainingAnnotation] = []
    for split in splits:
        if not isinstance(split, dict):
            continue
        split_name = str(split.get("name", ""))
        image_root = str(split.get("image_root", ""))
        annotation_file = str(split.get("annotation_file", ""))
        ann_path = dataset_storage.resolve_filesystem_path(annotation_file)
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
                    dataset_storage.resolve_filesystem_path(f"{image_root}/{file_name}")
                )
                resolved.append(
                    _ResolvedClassificationTrainingAnnotation(
                        image_path=resolved_path,
                        class_id=class_id,
                    )
                )
        if split_name == "train":
            train_annotations = resolved
        elif split_name in {"val", "valid", "validation"}:
            val_annotations = resolved
        elif split_name == "test":
            test_annotations = resolved
    if not train_annotations:
        raise InvalidRequestError(
            "YOLOv8 classification 训练 manifest 缺少有效 train 样本"
        )
    if not val_annotations:
        raise InvalidRequestError(
            "YOLOv8 classification 训练 manifest 缺少独立 validation 样本"
        )
    sorted_labels = sorted(all_labels.items())
    labels = tuple(name for _cid, name in sorted_labels)
    category_id_to_index = {cid: idx for idx, (cid, _name) in enumerate(sorted_labels)}
    remapped_train = _remap_classification_annotations(
        annotations=train_annotations,
        category_id_to_index=category_id_to_index,
    )
    remapped_val = _remap_classification_annotations(
        annotations=val_annotations,
        category_id_to_index=category_id_to_index,
    )
    remapped_test = _remap_classification_annotations(
        annotations=test_annotations,
        category_id_to_index=category_id_to_index,
    )
    return labels, remapped_train, remapped_val, remapped_test


def _remap_classification_annotations(
    *,
    annotations: list[_ResolvedClassificationTrainingAnnotation],
    category_id_to_index: dict[int, int],
) -> list[_ResolvedClassificationTrainingAnnotation]:
    """把原始 category id 严格映射为连续训练 id。"""

    remapped: list[_ResolvedClassificationTrainingAnnotation] = []
    for annotation in annotations:
        if annotation.class_id not in category_id_to_index:
            raise InvalidRequestError(
                "YOLOv8 classification 标注引用了未声明的 category_id",
                details={"category_id": annotation.class_id},
            )
        remapped.append(
            _ResolvedClassificationTrainingAnnotation(
                image_path=annotation.image_path,
                class_id=category_id_to_index[annotation.class_id],
            )
        )
    return remapped


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

    return resolve_single_training_device_name(
        torch_module=torch,
        extra_options=extra_options,
    )


def _autocast_context(imports: Any, precision: str, device_name: str):
    if precision == "fp16" and "cuda" in device_name:
        return imports.torch.amp.autocast(resolve_torch_amp_device_type(device_name))
    return nullcontext()


def _build_checkpoint_bytes(
    *,
    epoch: int,
    global_iteration: int,
    model: Any,
    ema: YoloModelEMA,
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
        "ema_state_dict": ema.state_dict(),
        "ema_updates": ema.updates,
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
        ema_state_dict=checkpoint.get("ema_state_dict"),
        ema_updates=max(0, int(checkpoint.get("ema_updates", 0))),
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
