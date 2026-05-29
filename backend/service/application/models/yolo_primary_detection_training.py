"""YOLO 主线 detection 共享训练执行模块。"""

from __future__ import annotations

import io
import json
import math
import random
from collections.abc import Callable
from contextlib import nullcontext, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolo_detection_model import (
    _dist2bbox_xyxy,
    _make_anchors,
)
from backend.service.application.models.yolo_primary_detection_model import (
    build_yolo_primary_detection_model,
    load_yolo_primary_checkpoint,
)
from backend.service.application.runtime.detection_runtime_support import batched_nms_indices
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


YOLO_PRIMARY_IMPLEMENTATION_MODE = "yolo-primary-detection"
YOLO_PRIMARY_DEFAULT_INPUT_SIZE = (640, 640)
YOLO_PRIMARY_DEFAULT_BATCH_SIZE = 1
YOLO_PRIMARY_DEFAULT_MAX_EPOCHS = 1
YOLO_PRIMARY_DEFAULT_EVALUATION_INTERVAL = 5
YOLO_PRIMARY_DEFAULT_EVAL_CONFIDENCE_THRESHOLD = 0.01
YOLO_PRIMARY_DEFAULT_EVAL_NMS_THRESHOLD = 0.65
YOLO_PRIMARY_DEFAULT_ASSIGN_TOPK = 10
YOLO_PRIMARY_DEFAULT_CLASS_LOSS_WEIGHT = 0.5
YOLO_PRIMARY_DEFAULT_BOX_LOSS_WEIGHT = 7.5
YOLO_PRIMARY_DEFAULT_DFL_LOSS_WEIGHT = 1.5
YOLO_PRIMARY_DEFAULT_ASSIGN_ALPHA = 0.5
YOLO_PRIMARY_DEFAULT_ASSIGN_BETA = 6.0
YOLO_PRIMARY_DEFAULT_MIN_LR_RATIO = 0.01
YOLO_PRIMARY_DEFAULT_GRAD_CLIP_NORM = 10.0


@dataclass(frozen=True)
class YoloPrimaryTrainingBatchProgress:
    """描述单个训练 batch 完成后的进度快照。"""

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
class YoloPrimaryTrainingEpochProgress:
    """描述单轮训练结束后的进度快照。"""

    epoch: int
    max_epochs: int
    evaluation_interval: int
    validation_ran: bool
    evaluated_epochs: tuple[int, ...]
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    train_metrics_snapshot: dict[str, object]
    validation_snapshot: dict[str, object] | None
    current_metric_name: str
    current_metric_value: float | None
    best_metric_name: str
    best_metric_value: float | None


@dataclass(frozen=True)
class YoloPrimaryTrainingControlCommand:
    """描述单轮训练结束后由上层返回给训练循环的控制命令。"""

    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


@dataclass(frozen=True)
class YoloPrimaryTrainingSavePoint:
    """描述训练在某个 epoch 边界导出的可恢复 savepoint。"""

    epoch: int
    latest_checkpoint_bytes: bytes
    best_checkpoint_bytes: bytes | None = None
    best_metric_name: str = ""
    best_metric_value: float | None = None


@dataclass(frozen=True)
class YoloPrimaryDetectionTrainingExecutionRequest:
    """描述一次 YOLO 主线 detection 共享训练执行请求。"""

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_scale: str
    model_type: str = "yolov8"
    implementation_mode: str = YOLO_PRIMARY_IMPLEMENTATION_MODE
    evaluation_interval: int | None = None
    max_epochs: int | None = None
    batch_size: int | None = None
    gpu_count: int | None = None
    precision: str | None = None
    warm_start_checkpoint_path: Path | None = None
    resume_checkpoint_path: Path | None = None
    warm_start_source_summary: dict[str, object] | None = None
    input_size: tuple[int, int] | None = None
    extra_options: dict[str, object] | None = None
    batch_callback: Callable[[YoloPrimaryTrainingBatchProgress], None] | None = None
    epoch_callback: Callable[[YoloPrimaryTrainingEpochProgress], YoloPrimaryTrainingControlCommand | None] | None = None
    savepoint_callback: Callable[[YoloPrimaryTrainingSavePoint], None] | None = None


@dataclass(frozen=True)
class YoloPrimaryDetectionTrainingExecutionResult:
    """描述一次 YOLO 主线 detection 共享训练执行结果。"""

    checkpoint_bytes: bytes
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    warm_start_summary: dict[str, object]
    implementation_mode: str
    best_metric_name: str
    best_metric_value: float
    evaluation_interval: int
    category_names: tuple[str, ...]
    split_names: tuple[str, ...]
    sample_count: int
    train_sample_count: int
    input_size: tuple[int, int]
    batch_size: int
    max_epochs: int
    device: str
    gpu_count: int
    device_ids: tuple[int, ...]
    distributed_mode: str
    precision: str
    validation_split_name: str | None
    validation_sample_count: int
    parameter_count: int


@dataclass(frozen=True)
class _TrainingImports:
    """描述 YOLO 主线 detection 训练所需的第三方依赖对象。"""

    cv2: Any
    np: Any
    torch: Any
    COCO: Any | None
    COCOeval: Any | None


@dataclass(frozen=True)
class _ResolvedCocoSplit:
    """描述一个已经解析到本地绝对路径的 COCO split。"""

    name: str
    image_root: Path
    annotation_file: Path
    sample_count: int


@dataclass(frozen=True)
class _ResolvedTrainingSample:
    """描述一个训练样本及其完整检测标注。"""

    image_id: int
    image_path: Path
    image_width: int
    image_height: int
    annotations: tuple["_ResolvedTrainingAnnotation", ...]


@dataclass(frozen=True)
class _ResolvedTrainingAnnotation:
    """描述单个检测目标的原图 bbox 与类别。"""

    category_index: int
    category_id: int
    bbox_xyxy: tuple[float, float, float, float]


@dataclass(frozen=True)
class _PreparedTrainingTarget:
    """描述单张图片在当前训练输入尺寸下的目标。"""

    image_id: int
    image_width: int
    image_height: int
    boxes_xyxy: tuple[tuple[float, float, float, float], ...]
    category_indexes: tuple[int, ...]


@dataclass(frozen=True)
class _LoadedResumeState:
    """描述从 latest checkpoint 解析出的恢复训练状态。"""

    resume_epoch: int
    epoch_history: list[dict[str, object]]
    validation_history: list[dict[str, object]]
    evaluated_epochs: tuple[int, ...]
    best_metric_name: str
    best_metric_value: float | None
    best_checkpoint_state: dict[str, object] | None
    warm_start_summary: dict[str, object]


class YoloPrimaryTrainingPausedError(Exception):
    """表示训练在 epoch 边界按请求完成保存后进入 paused 状态。"""

    def __init__(self, savepoint: YoloPrimaryTrainingSavePoint) -> None:
        super().__init__("yolo primary detection training paused")
        self.savepoint = savepoint


class YoloPrimaryTrainingTerminatedError(Exception):
    """表示训练在 epoch 边界按请求终止。"""

    def __init__(self) -> None:
        super().__init__("yolo primary detection training terminated")


def run_yolo_primary_detection_training(
    request: YoloPrimaryDetectionTrainingExecutionRequest,
) -> YoloPrimaryDetectionTrainingExecutionResult:
    """执行一轮项目内 YOLO 主线 detection 共享训练。"""

    imports = _require_training_imports()
    manifest_payload = dict(request.manifest_payload)
    resolved_splits = _resolve_coco_splits(
        dataset_storage=request.dataset_storage,
        manifest_payload=manifest_payload,
    )
    train_split = _resolve_train_split(resolved_splits)
    validation_split = _resolve_validation_split(resolved_splits)
    input_size = _resolve_input_size(request.input_size)
    batch_size = max(1, int(request.batch_size or YOLO_PRIMARY_DEFAULT_BATCH_SIZE))
    max_epochs = max(1, int(request.max_epochs or YOLO_PRIMARY_DEFAULT_MAX_EPOCHS))
    evaluation_interval = max(
        1,
        int(request.evaluation_interval or YOLO_PRIMARY_DEFAULT_EVALUATION_INTERVAL),
    )
    extra_options = dict(request.extra_options or {})

    train_samples, category_names, category_ids = _load_training_samples(
        imports=imports,
        split=train_split,
    )
    validation_samples: tuple[_ResolvedTrainingSample, ...] = ()
    validation_category_ids: tuple[int, ...] = ()
    if validation_split is not None:
        validation_samples, validation_category_names, validation_category_ids = _load_training_samples(
            imports=imports,
            split=validation_split,
        )
        if validation_category_names != category_names:
            raise InvalidRequestError(
                "验证 split 的 categories 与训练 split 不一致",
                details={
                    "train_categories": list(category_names),
                    "validation_categories": list(validation_category_names),
                },
            )
        if validation_category_ids != category_ids:
            raise InvalidRequestError(
                "验证 split 的 category_id 映射与训练 split 不一致",
                details={
                    "train_category_ids": list(category_ids),
                    "validation_category_ids": list(validation_category_ids),
                },
            )
    if not train_samples:
        raise InvalidRequestError("训练 split 不包含可用样本")

    device, gpu_count, device_ids, distributed_mode, runtime_precision = _resolve_runtime(
        imports=imports,
        requested_gpu_count=request.gpu_count,
        requested_precision=request.precision,
    )
    learning_rate = _read_float_option(extra_options, "learning_rate", default=1e-3)
    weight_decay = _read_float_option(extra_options, "weight_decay", default=1e-4)
    class_loss_weight = _read_float_option(
        extra_options,
        "class_loss_weight",
        default=YOLO_PRIMARY_DEFAULT_CLASS_LOSS_WEIGHT,
    )
    box_loss_weight = _read_float_option(
        extra_options,
        "box_loss_weight",
        default=YOLO_PRIMARY_DEFAULT_BOX_LOSS_WEIGHT,
    )
    dfl_loss_weight = _read_float_option(
        extra_options,
        "dfl_loss_weight",
        default=YOLO_PRIMARY_DEFAULT_DFL_LOSS_WEIGHT,
    )
    evaluation_confidence_threshold = _read_float_option(
        extra_options,
        "evaluation_confidence_threshold",
        default=YOLO_PRIMARY_DEFAULT_EVAL_CONFIDENCE_THRESHOLD,
    )
    evaluation_nms_threshold = _read_float_option(
        extra_options,
        "evaluation_nms_threshold",
        default=YOLO_PRIMARY_DEFAULT_EVAL_NMS_THRESHOLD,
    )
    assign_topk = max(
        1,
        _read_int_option(extra_options, "assign_topk", default=YOLO_PRIMARY_DEFAULT_ASSIGN_TOPK),
    )
    assign_alpha = _read_float_option(
        extra_options,
        "assign_alpha",
        default=YOLO_PRIMARY_DEFAULT_ASSIGN_ALPHA,
    )
    assign_beta = _read_float_option(
        extra_options,
        "assign_beta",
        default=YOLO_PRIMARY_DEFAULT_ASSIGN_BETA,
    )
    min_lr_ratio = _read_float_option(
        extra_options,
        "min_lr_ratio",
        default=YOLO_PRIMARY_DEFAULT_MIN_LR_RATIO,
    )
    grad_clip_norm = _read_float_option(
        extra_options,
        "grad_clip_norm",
        default=YOLO_PRIMARY_DEFAULT_GRAD_CLIP_NORM,
    )
    validation_split_name = validation_split.name if validation_split is not None else None

    model = build_yolo_primary_detection_model(
        model_type=request.model_type,
        model_scale=request.model_scale,
        num_classes=len(category_names),
    )
    
    # 检测模型是否启用端到端训练
    is_end2end = getattr(model, "end2end", False)
    
    # 端到端训练的权重调度器
    e2e_o2m_weight = 0.8  # one2many 初始权重
    e2e_o2o_weight = 0.2  # one2one 初始权重
    e2e_o2m_initial = 0.8
    e2e_o2m_final = 0.1
    
    def update_e2e_weights(epoch: int, total_epochs: int) -> None:
        """更新端到端训练的分支权重。
        
        训练初期 one2many 主导（提供充足梯度），
        训练末期 one2one 主导（确保推理精度）。
        """
        nonlocal e2e_o2m_weight, e2e_o2o_weight
        if total_epochs <= 1:
            progress = 1.0
        else:
            progress = epoch / (total_epochs - 1)
        e2e_o2m_weight = e2e_o2m_initial + (e2e_o2m_final - e2e_o2m_initial) * progress
        e2e_o2o_weight = 1.0 - e2e_o2m_weight
    
    warm_start_summary = {
        "enabled": False,
        "source_model_version_id": None,
        "source_kind": None,
        "source_model_name": None,
        "source_model_scale": None,
        "load_summary": None,
    }
    if request.warm_start_checkpoint_path is not None:
        warm_start_summary = _load_warm_start_checkpoint(
            imports=imports,
            model=model,
            checkpoint_path=request.warm_start_checkpoint_path,
            source_summary=request.warm_start_source_summary or {},
        )

    parameter_count = sum(
        int(parameter.numel())
        for parameter in model.parameters()
    )
    optimizer = imports.torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    scheduler = imports.torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=max_epochs,
        eta_min=learning_rate * min_lr_ratio,
    )
    scaler_enabled = device.startswith("cuda") and runtime_precision == "fp16"
    amp_module = getattr(imports.torch, "amp", None)
    grad_scaler_cls = getattr(amp_module, "GradScaler", None) if amp_module is not None else None
    if grad_scaler_cls is not None:
        scaler = grad_scaler_cls("cuda", enabled=scaler_enabled)
    else:
        scaler = imports.torch.cuda.amp.GradScaler(enabled=scaler_enabled)
    resume_state: _LoadedResumeState | None = None
    if request.resume_checkpoint_path is not None:
        resume_state = _load_resume_checkpoint(
            imports=imports,
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            checkpoint_path=request.resume_checkpoint_path,
            expected_model_type=request.model_type,
            expected_model_scale=request.model_scale,
            expected_num_classes=len(category_names),
            expected_input_size=input_size,
            expected_batch_size=batch_size,
            expected_max_epochs=max_epochs,
            expected_precision=runtime_precision,
            expected_validation_split_name=validation_split_name,
            expected_evaluation_interval=evaluation_interval,
            expected_evaluation_confidence_threshold=(
                evaluation_confidence_threshold
                if validation_split is not None and bool(validation_samples)
                else None
            ),
            expected_evaluation_nms_threshold=(
                evaluation_nms_threshold
                if validation_split is not None and bool(validation_samples)
                else None
            ),
            expected_learning_rate=learning_rate,
            expected_weight_decay=weight_decay,
            expected_class_loss_weight=class_loss_weight,
            expected_box_loss_weight=box_loss_weight,
            expected_dfl_loss_weight=dfl_loss_weight,
            expected_assign_topk=assign_topk,
            expected_assign_alpha=assign_alpha,
            expected_assign_beta=assign_beta,
            expected_min_lr_ratio=min_lr_ratio,
            expected_grad_clip_norm=grad_clip_norm,
        )
        warm_start_summary = dict(resume_state.warm_start_summary)

    model.to(device)
    if runtime_precision == "fp16":
        model.half()
    if resume_state is not None:
        _move_optimizer_state_to_device(optimizer=optimizer, device=device)
    autocast_context = _build_autocast_context(
        imports=imports,
        device=device,
        runtime_precision=runtime_precision,
    )
    total_iterations = max_epochs * max(1, (len(train_samples) + batch_size - 1) // batch_size)
    metrics_history: list[dict[str, object]] = (
        [dict(item) for item in resume_state.epoch_history]
        if resume_state is not None
        else []
    )
    validation_history: list[dict[str, object]] = (
        [dict(item) for item in resume_state.validation_history]
        if resume_state is not None
        else []
    )
    evaluated_epochs: list[int] = (
        list(resume_state.evaluated_epochs)
        if resume_state is not None
        else []
    )
    best_metric_name = (
        resume_state.best_metric_name
        if resume_state is not None and resume_state.best_metric_name.strip()
        else ("map50_95" if validation_split is not None else "train_loss")
    )
    best_metric_value = (
        resume_state.best_metric_value
        if resume_state is not None and resume_state.best_metric_value is not None
        else (float("-inf") if validation_split is not None else float("inf"))
    )
    latest_checkpoint_bytes = b""
    best_checkpoint_bytes = (
        _build_checkpoint_bytes_from_state(
            imports=imports,
            checkpoint_state=resume_state.best_checkpoint_state,
        )
        if resume_state is not None and resume_state.best_checkpoint_state is not None
        else b""
    )
    resume_epoch = resume_state.resume_epoch if resume_state is not None else 0
    if resume_epoch >= max_epochs:
        raise InvalidRequestError(
            "resume checkpoint 已经达到或超过本次训练请求的最大 epoch",
            details={"resume_epoch": resume_epoch, "max_epochs": max_epochs},
        )
    global_iteration = resume_epoch * max(1, (len(train_samples) + batch_size - 1) // batch_size)

    for epoch in range(resume_epoch + 1, max_epochs + 1):
        # 更新端到端训练权重
        if is_end2end:
            update_e2e_weights(epoch - 1, max_epochs)
        
        shuffled_samples = list(train_samples)
        random.shuffle(shuffled_samples)
        epoch_losses = {"loss": 0.0, "class_loss": 0.0, "box_loss": 0.0, "dfl_loss": 0.0}
        if is_end2end:
            epoch_losses["one2many_loss"] = 0.0
            epoch_losses["one2one_loss"] = 0.0
        max_iterations = max(1, (len(shuffled_samples) + batch_size - 1) // batch_size)
        model.train()

        for iteration, sample_batch in enumerate(_iter_batches(shuffled_samples, batch_size), start=1):
            global_iteration += 1
            images, batch_targets = _build_training_batch(
                imports=imports,
                samples=sample_batch,
                input_size=input_size,
                device=device,
                runtime_precision=runtime_precision,
            )
            optimizer.zero_grad(set_to_none=True)
            with autocast_context():
                model_outputs = model(images)
                
                if is_end2end:
                    # 端到端训练：使用双分支损失
                    e2e_outputs = _unwrap_e2e_detection_outputs(model_outputs)
                    loss_components = _compute_e2e_detection_loss(
                        imports=imports,
                        model=model,
                        raw_outputs=e2e_outputs,
                        batch_targets=batch_targets,
                        num_classes=len(category_names),
                        class_loss_weight=class_loss_weight,
                        box_loss_weight=box_loss_weight,
                        dfl_loss_weight=dfl_loss_weight,
                        assign_topk=assign_topk,
                        assign_alpha=assign_alpha,
                        assign_beta=assign_beta,
                        e2e_o2m_weight=e2e_o2m_weight,
                        e2e_o2o_weight=e2e_o2o_weight,
                    )
                else:
                    # 标准训练：使用单分支损失
                    raw_outputs = _unwrap_detection_outputs(model_outputs)
                    loss_components = _compute_detection_loss(
                        imports=imports,
                        model=model,
                        raw_outputs=raw_outputs,
                        batch_targets=batch_targets,
                        num_classes=len(category_names),
                        class_loss_weight=class_loss_weight,
                        box_loss_weight=box_loss_weight,
                        dfl_loss_weight=dfl_loss_weight,
                        assign_topk=assign_topk,
                        assign_alpha=assign_alpha,
                        assign_beta=assign_beta,
                    )
                loss = loss_components["loss"]
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            if grad_clip_norm > 0:
                imports.torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip_norm)
            scaler.step(optimizer)
            scaler.update()

            for key in epoch_losses:
                if key in loss_components:
                    epoch_losses[key] += float(loss_components[key].detach().item())

            if request.batch_callback is not None:
                train_metrics_batch = {
                    "loss": float(loss_components["loss"].detach().item()),
                    "class_loss": float(loss_components["class_loss"].detach().item()),
                    "box_loss": float(loss_components["box_loss"].detach().item()),
                    "dfl_loss": float(loss_components["dfl_loss"].detach().item()),
                }
                if is_end2end:
                    train_metrics_batch["one2many_loss"] = float(loss_components["one2many_loss"].detach().item())
                    train_metrics_batch["one2one_loss"] = float(loss_components["one2one_loss"].detach().item())
                    train_metrics_batch["e2e_o2m_weight"] = e2e_o2m_weight
                    train_metrics_batch["e2e_o2o_weight"] = e2e_o2o_weight
                
                request.batch_callback(
                    YoloPrimaryTrainingBatchProgress(
                        epoch=epoch,
                        max_epochs=max_epochs,
                        iteration=iteration,
                        max_iterations=max_iterations,
                        global_iteration=global_iteration,
                        total_iterations=total_iterations,
                        input_size=input_size,
                        learning_rate=float(optimizer.param_groups[0]["lr"]),
                        train_metrics=train_metrics_batch,
                    )
                )

        train_metrics = {
            key: round(value / max_iterations, 6)
            for key, value in epoch_losses.items()
        }
        train_metrics["epoch"] = epoch
        metrics_history.append(train_metrics)

        validation_ran = (
            validation_split is not None
            and bool(validation_samples)
            and (epoch == max_epochs or epoch % evaluation_interval == 0)
        )
        validation_snapshot: dict[str, object] | None = None
        validation_metrics: dict[str, float] = {}
        current_metric_value: float | None = None
        if validation_ran:
            validation_snapshot = _evaluate_detection_model(
                imports=imports,
                model=model,
                samples=validation_samples,
                category_ids=category_ids,
                annotation_file=validation_split.annotation_file if validation_split is not None else None,
                input_size=input_size,
                batch_size=batch_size,
                device=device,
                runtime_precision=runtime_precision,
                num_classes=len(category_names),
                class_loss_weight=class_loss_weight,
                box_loss_weight=box_loss_weight,
                dfl_loss_weight=dfl_loss_weight,
                assign_topk=assign_topk,
                assign_alpha=assign_alpha,
                assign_beta=assign_beta,
                confidence_threshold=evaluation_confidence_threshold,
                nms_threshold=evaluation_nms_threshold,
            )
            validation_history.append(validation_snapshot)
            validation_metrics = {
                "loss": float(validation_snapshot["loss"]),
                "map50": float(validation_snapshot["map50"]),
                "map50_95": float(validation_snapshot["map50_95"]),
            }
            evaluated_epochs.append(epoch)
            current_metric_value = validation_metrics[best_metric_name]

        improved_best = False
        candidate_best_metric_value = best_metric_value
        if validation_ran and current_metric_value is not None:
            if current_metric_value >= best_metric_value:
                improved_best = True
                candidate_best_metric_value = current_metric_value
        elif train_metrics["loss"] <= best_metric_value:
            improved_best = True
            candidate_best_metric_value = train_metrics["loss"]

        scheduler.step()
        previous_best_checkpoint_state = (
            _load_checkpoint_state_from_bytes(imports=imports, checkpoint_bytes=best_checkpoint_bytes)
            if best_checkpoint_bytes
            else None
        )
        current_checkpoint_state = _build_checkpoint_state(
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
            model_type=request.model_type,
            model_scale=request.model_scale,
            category_names=category_names,
            input_size=input_size,
            batch_size=batch_size,
            max_epochs=max_epochs,
            epoch=epoch,
            precision=runtime_precision,
            validation_split_name=validation_split_name,
            evaluation_interval=evaluation_interval,
            evaluation_confidence_threshold=(
                evaluation_confidence_threshold
                if validation_split is not None and bool(validation_samples)
                else None
            ),
            evaluation_nms_threshold=(
                evaluation_nms_threshold
                if validation_split is not None and bool(validation_samples)
                else None
            ),
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            class_loss_weight=class_loss_weight,
            box_loss_weight=box_loss_weight,
            dfl_loss_weight=dfl_loss_weight,
            assign_topk=assign_topk,
            assign_alpha=assign_alpha,
            assign_beta=assign_beta,
            min_lr_ratio=min_lr_ratio,
            grad_clip_norm=grad_clip_norm,
            metrics_history=metrics_history,
            validation_history=validation_history,
            evaluated_epochs=tuple(evaluated_epochs),
            warm_start_summary=warm_start_summary,
            implementation_mode=request.implementation_mode,
            best_metric_name=best_metric_name,
            best_metric_value=candidate_best_metric_value,
            best_checkpoint_state=previous_best_checkpoint_state,
        )
        if improved_best:
            current_best_checkpoint_state = dict(current_checkpoint_state)
            current_best_checkpoint_state["best_checkpoint_state"] = None
            current_checkpoint_state["best_checkpoint_state"] = current_best_checkpoint_state
            best_metric_value = candidate_best_metric_value
            best_checkpoint_bytes = _build_checkpoint_bytes_from_state(
                imports=imports,
                checkpoint_state=current_best_checkpoint_state,
            )
        latest_checkpoint_bytes = _build_checkpoint_bytes_from_state(
            imports=imports,
            checkpoint_state=current_checkpoint_state,
        )

        control_command = None
        if request.epoch_callback is not None:
            control_command = request.epoch_callback(
                YoloPrimaryTrainingEpochProgress(
                    epoch=epoch,
                    max_epochs=max_epochs,
                    evaluation_interval=evaluation_interval,
                    validation_ran=validation_ran,
                    evaluated_epochs=tuple(evaluated_epochs),
                    train_metrics=train_metrics,
                    validation_metrics=validation_metrics,
                    train_metrics_snapshot={
                        "history": metrics_history,
                        "final_metrics": train_metrics,
                    },
                    validation_snapshot=validation_snapshot,
                    current_metric_name=best_metric_name,
                    current_metric_value=current_metric_value,
                    best_metric_name=best_metric_name,
                    best_metric_value=(
                        None
                        if (
                            (validation_split is not None and best_metric_value == float("-inf"))
                            or (validation_split is None and best_metric_value == float("inf"))
                        )
                        else round(best_metric_value, 6)
                    ),
                )
            )
        if control_command is not None and (
            control_command.save_checkpoint or control_command.pause_training
        ):
            savepoint = YoloPrimaryTrainingSavePoint(
                epoch=epoch,
                latest_checkpoint_bytes=latest_checkpoint_bytes,
                best_checkpoint_bytes=best_checkpoint_bytes or latest_checkpoint_bytes,
                best_metric_name=best_metric_name,
                best_metric_value=(
                    None
                    if (
                        (validation_split is not None and best_metric_value == float("-inf"))
                        or (validation_split is None and best_metric_value == float("inf"))
                    )
                    else round(best_metric_value, 6)
                ),
            )
            if request.savepoint_callback is not None:
                request.savepoint_callback(savepoint)
            if control_command.pause_training:
                raise YoloPrimaryTrainingPausedError(savepoint)
        if control_command is not None and control_command.terminate_training:
            raise YoloPrimaryTrainingTerminatedError()

    if not best_checkpoint_bytes:
        best_checkpoint_bytes = latest_checkpoint_bytes
    if validation_split is not None and best_metric_value == float("-inf"):
        best_metric_value = 0.0
    if validation_split is None and best_metric_value == float("inf"):
        best_metric_value = 0.0

    validation_metrics_payload = {
        "enabled": validation_split is not None and bool(validation_samples),
        "evaluation_interval": evaluation_interval,
        "split_name": validation_split.name if validation_split is not None else None,
        "sample_count": len(validation_samples),
        "confidence_threshold": (
            evaluation_confidence_threshold if validation_split is not None and bool(validation_samples) else None
        ),
        "nms_threshold": (
            evaluation_nms_threshold if validation_split is not None and bool(validation_samples) else None
        ),
        "best_metric_name": best_metric_name if validation_split is not None and bool(validation_samples) else None,
        "best_metric_value": (
            round(best_metric_value, 6)
            if validation_split is not None and bool(validation_samples)
            else None
        ),
        "evaluated_epochs": evaluated_epochs,
        "epoch_history": validation_history,
        "final_metrics": validation_history[-1] if validation_history else {},
    }
    metrics_payload = {
        "implementation_mode": request.implementation_mode,
        "device": device,
        "gpu_count": gpu_count,
        "device_ids": list(device_ids),
        "distributed_mode": distributed_mode,
        "precision": runtime_precision,
        "batch_size": batch_size,
        "max_epochs": max_epochs,
        "evaluation_interval": evaluation_interval,
        "input_size": list(input_size),
        "train_split_name": train_split.name,
        "validation_split_name": validation_split.name if validation_split is not None else None,
        "sample_count": sum(split.sample_count for split in resolved_splits),
        "train_sample_count": len(train_samples),
        "validation_sample_count": len(validation_samples),
        "category_names": list(category_names),
        "best_metric_name": best_metric_name,
        "best_metric_value": round(best_metric_value, 6),
        "epoch_history": metrics_history,
        "final_metrics": metrics_history[-1] if metrics_history else {},
        "parameter_count": parameter_count,
        "warm_start": warm_start_summary,
        "optimizer": {
            "name": "AdamW",
            "learning_rate": learning_rate,
            "weight_decay": weight_decay,
        },
        "scheduler": {
            "name": "CosineAnnealingLR",
            "min_lr_ratio": min_lr_ratio,
            "latest_learning_rate": float(optimizer.param_groups[0]["lr"]),
        },
        "evaluation": {
            "split_name": validation_split_name,
            "confidence_threshold": (
                evaluation_confidence_threshold
                if validation_split is not None and bool(validation_samples)
                else None
            ),
            "nms_threshold": (
                evaluation_nms_threshold
                if validation_split is not None and bool(validation_samples)
                else None
            ),
        },
        "loss_weights": {
            "class_loss_weight": class_loss_weight,
            "box_loss_weight": box_loss_weight,
            "dfl_loss_weight": dfl_loss_weight,
        },
        "assignment": {
            "assign_topk": assign_topk,
            "assign_alpha": assign_alpha,
            "assign_beta": assign_beta,
        },
        "gradient_control": {
            "grad_clip_norm": grad_clip_norm,
        },
    }
    return YoloPrimaryDetectionTrainingExecutionResult(
        checkpoint_bytes=best_checkpoint_bytes,
        latest_checkpoint_bytes=latest_checkpoint_bytes,
        metrics_payload=metrics_payload,
        validation_metrics_payload=validation_metrics_payload,
        warm_start_summary=warm_start_summary,
        implementation_mode=request.implementation_mode,
        best_metric_name=best_metric_name,
        best_metric_value=round(best_metric_value, 6),
        evaluation_interval=evaluation_interval,
        category_names=category_names,
        split_names=tuple(split.name for split in resolved_splits),
        sample_count=sum(split.sample_count for split in resolved_splits),
        train_sample_count=len(train_samples),
        input_size=input_size,
        batch_size=batch_size,
        max_epochs=max_epochs,
        device=device,
        gpu_count=gpu_count,
        device_ids=device_ids,
        distributed_mode=distributed_mode,
        precision=runtime_precision,
        validation_split_name=validation_split.name if validation_split is not None else None,
        validation_sample_count=len(validation_samples),
        parameter_count=parameter_count,
    )


def _require_training_imports() -> _TrainingImports:
    """导入 YOLO 主线 detection 训练所需依赖。"""

    try:
        import cv2
        import numpy as np
        import torch
    except Exception as error:  # pragma: no cover - 缺依赖时直接报配置错误
        raise ServiceConfigurationError(
            "当前环境缺少 YOLO 主线 detection 训练所需依赖",
            details={"error": str(error)},
        ) from error
    try:
        from pycocotools.coco import COCO
        from pycocotools.cocoeval import COCOeval
    except Exception:
        COCO = None
        COCOeval = None
    return _TrainingImports(cv2=cv2, np=np, torch=torch, COCO=COCO, COCOeval=COCOeval)


def _resolve_coco_splits(
    *,
    dataset_storage: LocalDatasetStorage,
    manifest_payload: dict[str, object],
) -> tuple[_ResolvedCocoSplit, ...]:
    """从导出 manifest 里解析可用的 COCO split。"""

    splits_payload = manifest_payload.get("splits")
    if not isinstance(splits_payload, list):
        raise InvalidRequestError("训练输入 manifest 缺少 splits 定义")
    resolved_splits: list[_ResolvedCocoSplit] = []
    for split_item in splits_payload:
        if not isinstance(split_item, dict):
            continue
        split_name = str(split_item.get("name") or "").strip()
        image_root = str(split_item.get("image_root") or "").strip()
        annotation_file = str(split_item.get("annotation_file") or "").strip()
        if not split_name or not image_root or not annotation_file:
            continue
        annotation_path = dataset_storage.resolve(annotation_file)
        image_root_path = dataset_storage.resolve(image_root)
        if not annotation_path.is_file():
            raise InvalidRequestError(
                "训练输入 split 缺少 annotation 文件",
                details={"split_name": split_name, "annotation_file": annotation_file},
            )
        if not image_root_path.is_dir():
            raise InvalidRequestError(
                "训练输入 split 缺少图片目录",
                details={"split_name": split_name, "image_root": image_root},
            )
        annotation_payload = json.loads(annotation_path.read_text(encoding="utf-8"))
        image_items = annotation_payload.get("images", [])
        sample_count = len(image_items) if isinstance(image_items, list) else 0
        resolved_splits.append(
            _ResolvedCocoSplit(
                name=split_name,
                image_root=image_root_path,
                annotation_file=annotation_path,
                sample_count=sample_count,
            )
        )
    if not resolved_splits:
        raise InvalidRequestError("训练输入 manifest 没有可用的 split")
    return tuple(resolved_splits)


def _resolve_train_split(resolved_splits: tuple[_ResolvedCocoSplit, ...]) -> _ResolvedCocoSplit:
    """优先解析 train split。"""

    for split in resolved_splits:
        if split.name.lower() == "train":
            return split
    return resolved_splits[0]


def _resolve_validation_split(
    resolved_splits: tuple[_ResolvedCocoSplit, ...],
) -> _ResolvedCocoSplit | None:
    """解析验证 split。"""

    validation_names = {"val", "valid", "validation", "test"}
    for split in resolved_splits:
        if split.name.lower() in validation_names:
            return split
    return None


def _load_training_samples(
    *,
    imports: _TrainingImports,
    split: _ResolvedCocoSplit,
) -> tuple[tuple[_ResolvedTrainingSample, ...], tuple[str, ...], tuple[int, ...]]:
    """把 COCO split 转成训练阶段可直接消费的样本列表。"""

    del imports
    annotation_payload = json.loads(split.annotation_file.read_text(encoding="utf-8"))
    categories_payload = annotation_payload.get("categories", [])
    images_payload = annotation_payload.get("images", [])
    annotations_payload = annotation_payload.get("annotations", [])
    if not isinstance(categories_payload, list) or not isinstance(images_payload, list):
        raise InvalidRequestError(
            "COCO annotation 文件结构不合法",
            details={"annotation_file": str(split.annotation_file)},
        )
    category_names: list[str] = []
    category_ids: list[int] = []
    category_id_to_index: dict[int, int] = {}
    for category_item in categories_payload:
        if not isinstance(category_item, dict):
            continue
        category_id = category_item.get("id")
        category_name = str(category_item.get("name") or "").strip()
        if not isinstance(category_id, int) or not category_name:
            continue
        category_id_to_index[category_id] = len(category_names)
        category_names.append(category_name)
        category_ids.append(category_id)
    if not category_names:
        raise InvalidRequestError("训练输入缺少有效的 categories")

    image_meta_by_id: dict[int, dict[str, object]] = {}
    for image_item in images_payload:
        if not isinstance(image_item, dict):
            continue
        image_id = image_item.get("id")
        file_name = str(image_item.get("file_name") or "").strip()
        width = image_item.get("width")
        height = image_item.get("height")
        if (
            not isinstance(image_id, int)
            or not file_name
            or not isinstance(width, int)
            or not isinstance(height, int)
            or width <= 0
            or height <= 0
        ):
            continue
        image_meta_by_id[image_id] = {
            "file_name": file_name,
            "width": width,
            "height": height,
            "annotations": [],
        }
    for annotation_item in annotations_payload if isinstance(annotations_payload, list) else ():
        if not isinstance(annotation_item, dict):
            continue
        image_id = annotation_item.get("image_id")
        category_id = annotation_item.get("category_id")
        bbox = annotation_item.get("bbox")
        image_meta = image_meta_by_id.get(image_id if isinstance(image_id, int) else -1)
        category_index = category_id_to_index.get(category_id if isinstance(category_id, int) else -1)
        if image_meta is None or category_index is None or not isinstance(bbox, list | tuple) or len(bbox) != 4:
            continue
        x, y, w, h = bbox
        if not all(isinstance(item, int | float) for item in (x, y, w, h)):
            continue
        if float(w) <= 0.0 or float(h) <= 0.0:
            continue
        width = int(image_meta["width"])
        height = int(image_meta["height"])
        x1 = max(0.0, min(float(x), float(width)))
        y1 = max(0.0, min(float(y), float(height)))
        x2 = max(0.0, min(float(x + w), float(width)))
        y2 = max(0.0, min(float(y + h), float(height)))
        if x2 <= x1 or y2 <= y1:
            continue
        image_meta["annotations"].append(
            _ResolvedTrainingAnnotation(
                category_index=category_index,
                category_id=int(category_id),
                bbox_xyxy=(x1, y1, x2, y2),
            )
        )

    resolved_samples: list[_ResolvedTrainingSample] = []
    for image_id, image_meta in image_meta_by_id.items():
        file_name = str(image_meta["file_name"])
        width = int(image_meta["width"])
        height = int(image_meta["height"])
        annotations = tuple(
            item
            for item in image_meta["annotations"]
            if isinstance(item, _ResolvedTrainingAnnotation)
        )
        image_path = split.image_root / file_name
        if not image_path.is_file():
            continue
        resolved_samples.append(
            _ResolvedTrainingSample(
                image_id=image_id,
                image_path=image_path,
                image_width=width,
                image_height=height,
                annotations=annotations,
            )
        )
    return tuple(resolved_samples), tuple(category_names), tuple(category_ids)


def _resolve_input_size(input_size: tuple[int, int] | None) -> tuple[int, int]:
    """解析训练输入尺寸。"""

    if input_size is None:
        return YOLO_PRIMARY_DEFAULT_INPUT_SIZE
    return tuple(int(item) for item in input_size)


def _resolve_runtime(
    *,
    imports: _TrainingImports,
    requested_gpu_count: int | None,
    requested_precision: str | None,
) -> tuple[str, int, tuple[int, ...], str, str]:
    """解析当前训练真正使用的运行时资源。"""

    del requested_gpu_count
    torch = imports.torch
    cuda_available = bool(torch.cuda.is_available())
    if cuda_available:
        runtime_precision = "fp16" if requested_precision == "fp16" else "fp32"
        return "cuda:0", 1, (0,), "single-process", runtime_precision
    return "cpu", 0, (), "single-process", "fp32"


def _load_warm_start_checkpoint(
    *,
    imports: _TrainingImports,
    model: Any,
    checkpoint_path: Path,
    source_summary: dict[str, object],
) -> dict[str, object]:
    """加载 warm start checkpoint 并返回摘要。"""

    load_summary = load_yolo_primary_checkpoint(
        imports=imports,
        model=model,
        checkpoint_path=checkpoint_path,
    )
    return {
        "enabled": True,
        "source_model_version_id": source_summary.get("source_model_version_id"),
        "source_kind": source_summary.get("source_kind"),
        "source_model_name": source_summary.get("source_model_name"),
        "source_model_scale": source_summary.get("source_model_scale"),
        "load_summary": load_summary,
    }


def _load_resume_checkpoint(
    *,
    imports: _TrainingImports,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any,
    checkpoint_path: Path,
    expected_model_type: str,
    expected_model_scale: str,
    expected_num_classes: int,
    expected_input_size: tuple[int, int],
    expected_batch_size: int,
    expected_max_epochs: int,
    expected_precision: str,
    expected_validation_split_name: str | None,
    expected_evaluation_interval: int,
    expected_evaluation_confidence_threshold: float | None,
    expected_evaluation_nms_threshold: float | None,
    expected_learning_rate: float,
    expected_weight_decay: float,
    expected_class_loss_weight: float,
    expected_box_loss_weight: float,
    expected_dfl_loss_weight: float,
    expected_assign_topk: int,
    expected_assign_alpha: float,
    expected_assign_beta: float,
    expected_min_lr_ratio: float,
    expected_grad_clip_norm: float,
) -> _LoadedResumeState:
    """从 latest checkpoint 恢复训练状态。"""

    checkpoint_payload = imports.torch.load(checkpoint_path, map_location="cpu")
    if not isinstance(checkpoint_payload, dict):
        raise InvalidRequestError("resume checkpoint 内容不合法")
    _validate_resume_checkpoint(
        checkpoint_payload=checkpoint_payload,
        expected_model_type=expected_model_type,
        expected_model_scale=expected_model_scale,
        expected_num_classes=expected_num_classes,
        expected_input_size=expected_input_size,
        expected_batch_size=expected_batch_size,
        expected_max_epochs=expected_max_epochs,
        expected_precision=expected_precision,
        expected_validation_split_name=expected_validation_split_name,
        expected_evaluation_interval=expected_evaluation_interval,
        expected_evaluation_confidence_threshold=expected_evaluation_confidence_threshold,
        expected_evaluation_nms_threshold=expected_evaluation_nms_threshold,
        expected_learning_rate=expected_learning_rate,
        expected_weight_decay=expected_weight_decay,
        expected_class_loss_weight=expected_class_loss_weight,
        expected_box_loss_weight=expected_box_loss_weight,
        expected_dfl_loss_weight=expected_dfl_loss_weight,
        expected_assign_topk=expected_assign_topk,
        expected_assign_alpha=expected_assign_alpha,
        expected_assign_beta=expected_assign_beta,
        expected_min_lr_ratio=expected_min_lr_ratio,
        expected_grad_clip_norm=expected_grad_clip_norm,
    )
    model.load_state_dict(dict(checkpoint_payload.get("model_state_dict") or {}))
    optimizer_state_dict = checkpoint_payload.get("optimizer_state_dict")
    if isinstance(optimizer_state_dict, dict):
        optimizer.load_state_dict(optimizer_state_dict)
    scheduler_state_dict = checkpoint_payload.get("scheduler_state_dict")
    if not isinstance(scheduler_state_dict, dict):
        raise InvalidRequestError("resume checkpoint 缺少 scheduler_state_dict")
    scheduler.load_state_dict(scheduler_state_dict)
    scaler_state_dict = checkpoint_payload.get("scaler_state_dict")
    if not isinstance(scaler_state_dict, dict):
        raise InvalidRequestError("resume checkpoint 缺少 scaler_state_dict")
    scaler.load_state_dict(scaler_state_dict)

    raw_resume_epoch = checkpoint_payload.get("epoch")
    resume_epoch = int(raw_resume_epoch) if isinstance(raw_resume_epoch, int) and raw_resume_epoch >= 0 else 0
    raw_best_metric_name = checkpoint_payload.get("best_metric_name")
    best_metric_name = (
        str(raw_best_metric_name)
        if isinstance(raw_best_metric_name, str) and raw_best_metric_name.strip()
        else "map50_95"
    )
    raw_best_metric_value = checkpoint_payload.get("best_metric_value")
    best_metric_value = (
        float(raw_best_metric_value)
        if isinstance(raw_best_metric_value, int | float)
        else None
    )
    warm_start_summary = checkpoint_payload.get("warm_start")
    return _LoadedResumeState(
        resume_epoch=resume_epoch,
        epoch_history=_normalize_history_items(checkpoint_payload.get("metrics_history")),
        validation_history=_normalize_history_items(checkpoint_payload.get("validation_history")),
        evaluated_epochs=_normalize_evaluated_epochs(checkpoint_payload.get("evaluated_epochs")),
        best_metric_name=best_metric_name,
        best_metric_value=best_metric_value,
        best_checkpoint_state=(
            dict(checkpoint_payload.get("best_checkpoint_state"))
            if isinstance(checkpoint_payload.get("best_checkpoint_state"), dict)
            else None
        ),
        warm_start_summary=(
            dict(warm_start_summary)
            if isinstance(warm_start_summary, dict)
            else {
                "enabled": False,
                "source_model_version_id": None,
                "source_kind": None,
                "source_model_name": None,
                "source_model_scale": None,
                "load_summary": None,
            }
        ),
    )


def _validate_resume_checkpoint(
    *,
    checkpoint_payload: dict[str, object],
    expected_model_type: str,
    expected_model_scale: str,
    expected_num_classes: int,
    expected_input_size: tuple[int, int],
    expected_batch_size: int,
    expected_max_epochs: int,
    expected_precision: str,
    expected_validation_split_name: str | None,
    expected_evaluation_interval: int,
    expected_evaluation_confidence_threshold: float | None,
    expected_evaluation_nms_threshold: float | None,
    expected_learning_rate: float,
    expected_weight_decay: float,
    expected_class_loss_weight: float,
    expected_box_loss_weight: float,
    expected_dfl_loss_weight: float,
    expected_assign_topk: int,
    expected_assign_alpha: float,
    expected_assign_beta: float,
    expected_min_lr_ratio: float,
    expected_grad_clip_norm: float,
) -> None:
    """校验恢复训练使用的 checkpoint 是否与当前请求匹配。"""

    checkpoint_model_type = checkpoint_payload.get("model_type")
    checkpoint_model_scale = checkpoint_payload.get("model_scale")
    checkpoint_category_names = checkpoint_payload.get("category_names")
    checkpoint_input_size = checkpoint_payload.get("input_size")
    checkpoint_batch_size = checkpoint_payload.get("batch_size")
    checkpoint_max_epochs = checkpoint_payload.get("max_epochs")
    checkpoint_precision = checkpoint_payload.get("precision")
    if checkpoint_model_type != expected_model_type:
        raise InvalidRequestError(
            "resume checkpoint 的 model_type 与当前训练请求不一致",
            details={
                "checkpoint_model_type": checkpoint_model_type,
                "expected_model_type": expected_model_type,
            },
        )
    if checkpoint_model_scale != expected_model_scale:
        raise InvalidRequestError(
            "resume checkpoint 的 model_scale 与当前训练请求不一致",
            details={
                "checkpoint_model_scale": checkpoint_model_scale,
                "expected_model_scale": expected_model_scale,
            },
        )
    if not isinstance(checkpoint_category_names, list) or len(checkpoint_category_names) != expected_num_classes:
        raise InvalidRequestError(
            "resume checkpoint 的类别数量与当前训练请求不一致",
            details={
                "checkpoint_class_count": (
                    len(checkpoint_category_names)
                    if isinstance(checkpoint_category_names, list)
                    else None
                ),
                "expected_class_count": expected_num_classes,
            },
        )
    if (
        not isinstance(checkpoint_input_size, list)
        or len(checkpoint_input_size) != 2
        or tuple(int(item) for item in checkpoint_input_size) != expected_input_size
    ):
        raise InvalidRequestError(
            "resume checkpoint 的 input_size 与当前训练请求不一致",
            details={
                "checkpoint_input_size": checkpoint_input_size,
                "expected_input_size": list(expected_input_size),
            },
        )
    if checkpoint_batch_size != expected_batch_size:
        raise InvalidRequestError(
            "resume checkpoint 的 batch_size 与当前训练请求不一致",
            details={
                "checkpoint_batch_size": checkpoint_batch_size,
                "expected_batch_size": expected_batch_size,
            },
        )
    if checkpoint_max_epochs != expected_max_epochs:
        raise InvalidRequestError(
            "resume checkpoint 的 max_epochs 与当前训练请求不一致",
            details={
                "checkpoint_max_epochs": checkpoint_max_epochs,
                "expected_max_epochs": expected_max_epochs,
            },
        )
    if checkpoint_precision != expected_precision:
        raise InvalidRequestError(
            "resume checkpoint 的 precision 与当前训练请求不一致",
            details={
                "checkpoint_precision": checkpoint_precision,
                "expected_precision": expected_precision,
            },
        )
    _validate_resume_validation_configuration(
        checkpoint_payload=checkpoint_payload,
        expected_validation_split_name=expected_validation_split_name,
        expected_evaluation_interval=expected_evaluation_interval,
        expected_evaluation_confidence_threshold=expected_evaluation_confidence_threshold,
        expected_evaluation_nms_threshold=expected_evaluation_nms_threshold,
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("learning_rate"),
        expected_value=expected_learning_rate,
        field_name="learning_rate",
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("weight_decay"),
        expected_value=expected_weight_decay,
        field_name="weight_decay",
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("class_loss_weight"),
        expected_value=expected_class_loss_weight,
        field_name="class_loss_weight",
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("box_loss_weight"),
        expected_value=expected_box_loss_weight,
        field_name="box_loss_weight",
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("dfl_loss_weight"),
        expected_value=expected_dfl_loss_weight,
        field_name="dfl_loss_weight",
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("assign_alpha"),
        expected_value=expected_assign_alpha,
        field_name="assign_alpha",
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("assign_beta"),
        expected_value=expected_assign_beta,
        field_name="assign_beta",
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("min_lr_ratio"),
        expected_value=expected_min_lr_ratio,
        field_name="min_lr_ratio",
    )
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_payload.get("grad_clip_norm"),
        expected_value=expected_grad_clip_norm,
        field_name="grad_clip_norm",
    )
    _assert_resume_required_int_matches(
        checkpoint_value=checkpoint_payload.get("assign_topk"),
        expected_value=expected_assign_topk,
        field_name="assign_topk",
    )


def _validate_resume_validation_configuration(
    *,
    checkpoint_payload: dict[str, object],
    expected_validation_split_name: str | None,
    expected_evaluation_interval: int,
    expected_evaluation_confidence_threshold: float | None,
    expected_evaluation_nms_threshold: float | None,
) -> None:
    """校验 resume checkpoint 中记录的验证配置是否与当前任务一致。"""

    checkpoint_validation_split_name = checkpoint_payload.get("validation_split_name")
    if checkpoint_validation_split_name != expected_validation_split_name:
        raise InvalidRequestError(
            "resume checkpoint 的 validation_split_name 与当前训练请求不一致",
            details={
                "checkpoint_validation_split_name": checkpoint_validation_split_name,
                "expected_validation_split_name": expected_validation_split_name,
            },
        )
    if expected_validation_split_name is None:
        return
    checkpoint_evaluation_interval = checkpoint_payload.get("evaluation_interval")
    if checkpoint_evaluation_interval != expected_evaluation_interval:
        raise InvalidRequestError(
            "resume checkpoint 的 evaluation_interval 与当前训练请求不一致",
            details={
                "checkpoint_evaluation_interval": checkpoint_evaluation_interval,
                "expected_evaluation_interval": expected_evaluation_interval,
            },
        )
    _assert_resume_optional_float_matches(
        checkpoint_value=checkpoint_payload.get("evaluation_confidence_threshold"),
        expected_value=expected_evaluation_confidence_threshold,
        field_name="evaluation_confidence_threshold",
    )
    _assert_resume_optional_float_matches(
        checkpoint_value=checkpoint_payload.get("evaluation_nms_threshold"),
        expected_value=expected_evaluation_nms_threshold,
        field_name="evaluation_nms_threshold",
    )


def _assert_resume_required_float_matches(
    *,
    checkpoint_value: object,
    expected_value: float,
    field_name: str,
) -> None:
    """断言 resume checkpoint 中的必填浮点配置与当前任务一致。"""

    if not isinstance(checkpoint_value, int | float) or not math.isclose(
        float(checkpoint_value),
        float(expected_value),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise InvalidRequestError(f"resume checkpoint 的 {field_name} 与当前训练请求不一致")


def _assert_resume_optional_float_matches(
    *,
    checkpoint_value: object,
    expected_value: float | None,
    field_name: str,
) -> None:
    """断言 resume checkpoint 中的可选浮点配置与当前任务一致。"""

    if expected_value is None:
        if checkpoint_value is not None:
            raise InvalidRequestError(f"resume checkpoint 的 {field_name} 与当前训练请求不一致")
        return
    _assert_resume_required_float_matches(
        checkpoint_value=checkpoint_value,
        expected_value=expected_value,
        field_name=field_name,
    )


def _assert_resume_required_int_matches(
    *,
    checkpoint_value: object,
    expected_value: int,
    field_name: str,
) -> None:
    """断言 resume checkpoint 中的必填整型配置与当前任务一致。"""

    if not isinstance(checkpoint_value, int) or int(checkpoint_value) != int(expected_value):
        raise InvalidRequestError(f"resume checkpoint 的 {field_name} 与当前训练请求不一致")


def _build_autocast_context(
    *,
    imports: _TrainingImports,
    device: str,
    runtime_precision: str,
) -> Callable[[], Any]:
    """构造训练阶段使用的 autocast 上下文工厂。"""

    torch = imports.torch
    use_fp16 = device.startswith("cuda") and runtime_precision == "fp16"
    autocast = getattr(torch, "autocast", None)
    if use_fp16 and callable(autocast):
        return lambda: autocast(device_type="cuda", dtype=torch.float16)
    return nullcontext


def _iter_batches(
    samples: list[_ResolvedTrainingSample],
    batch_size: int,
):
    """按 batch size 迭代样本。"""

    for batch_start in range(0, len(samples), batch_size):
        yield samples[batch_start : batch_start + batch_size]


def _build_training_batch(
    *,
    imports: _TrainingImports,
    samples: list[_ResolvedTrainingSample],
    input_size: tuple[int, int],
    device: str,
    runtime_precision: str,
) -> tuple[Any, tuple[_PreparedTrainingTarget, ...]]:
    """把一组样本拼成训练 batch。"""

    np_module = imports.np
    torch = imports.torch
    image_tensors: list[Any] = []
    prepared_targets: list[_PreparedTrainingTarget] = []
    for sample in samples:
        image = imports.cv2.imread(str(sample.image_path), imports.cv2.IMREAD_COLOR)
        if image is None:
            raise InvalidRequestError(
                "训练样本图片无法读取",
                details={"image_path": str(sample.image_path)},
            )
        resized = imports.cv2.resize(image, (input_size[1], input_size[0]), interpolation=imports.cv2.INTER_LINEAR)
        rgb_image = imports.cv2.cvtColor(resized, imports.cv2.COLOR_BGR2RGB)
        image_array = rgb_image.astype(np_module.float32) / 255.0
        image_array = np_module.transpose(image_array, (2, 0, 1))
        image_tensors.append(torch.from_numpy(image_array))
        scale_x = float(input_size[1]) / max(1.0, float(sample.image_width))
        scale_y = float(input_size[0]) / max(1.0, float(sample.image_height))
        resized_boxes: list[tuple[float, float, float, float]] = []
        resized_categories: list[int] = []
        for annotation in sample.annotations:
            x1, y1, x2, y2 = annotation.bbox_xyxy
            resized_x1 = max(0.0, min(x1 * scale_x, float(input_size[1])))
            resized_y1 = max(0.0, min(y1 * scale_y, float(input_size[0])))
            resized_x2 = max(0.0, min(x2 * scale_x, float(input_size[1])))
            resized_y2 = max(0.0, min(y2 * scale_y, float(input_size[0])))
            if resized_x2 <= resized_x1 or resized_y2 <= resized_y1:
                continue
            resized_boxes.append((resized_x1, resized_y1, resized_x2, resized_y2))
            resized_categories.append(annotation.category_index)
        prepared_targets.append(
            _PreparedTrainingTarget(
                image_id=sample.image_id,
                image_width=sample.image_width,
                image_height=sample.image_height,
                boxes_xyxy=tuple(resized_boxes),
                category_indexes=tuple(resized_categories),
            )
        )
    images = torch.stack(image_tensors, dim=0).to(device)
    if runtime_precision == "fp16":
        images = images.half()
    return images, tuple(prepared_targets)


def _unwrap_detection_outputs(outputs: Any) -> dict[str, Any]:
    """把 detection 训练输出规整成 one2many 结果。"""

    if isinstance(outputs, dict) and "boxes" in outputs and "scores" in outputs:
        return outputs
    if isinstance(outputs, dict) and "one2many" in outputs:
        one2many = outputs.get("one2many")
        if isinstance(one2many, dict) and "boxes" in one2many and "scores" in one2many:
            return one2many
    raise ServiceConfigurationError("当前 YOLO detection 训练输出结构不合法")


def _unwrap_e2e_detection_outputs(outputs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """把端到端检测训练输出拆分为 one2many 和 one2one 两个分支。

    Returns:
        (one2many_outputs, one2one_outputs): 两个分支的原始输出字典。
    """

    if not isinstance(outputs, dict):
        raise ServiceConfigurationError("端到端训练输出必须是字典")
    one2many = outputs.get("one2many")
    one2one = outputs.get("one2one")
    if not isinstance(one2many, dict) or "boxes" not in one2many or "scores" not in one2many:
        raise ServiceConfigurationError("端到端训练输出缺少有效的 one2many 分支")
    if not isinstance(one2one, dict) or "boxes" not in one2one or "scores" not in one2one:
        raise ServiceConfigurationError("端到端训练输出缺少有效的 one2one 分支")
    return one2many, one2one


def _compute_detection_loss(
    *,
    imports: _TrainingImports,
    model: Any,
    raw_outputs: dict[str, Any],
    batch_targets: tuple[_PreparedTrainingTarget, ...],
    num_classes: int,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    assign_topk2: int | None = None,
) -> dict[str, Any]:
    """按真实检测目标计算分类、框回归和 DFL 损失。

    Args:
        assign_topk2: 可选的二次精选参数，用于 E2E 训练的 one2one 分支。
    """

    torch = imports.torch
    detect_head = model.model[-1]
    prediction_bundle = _decode_detection_training_predictions(
        torch_module=torch,
        detect_head=detect_head,
        raw_outputs=raw_outputs,
    )
    class_logits = prediction_bundle["class_logits"]
    class_probabilities = class_logits.sigmoid()
    pred_boxes = prediction_bundle["boxes_xyxy"]
    distance_logits = prediction_bundle["distance_logits"]
    anchor_points = prediction_bundle["anchor_points"]
    stride_tensor = prediction_bundle["stride_tensor"]
    anchor_centers_xy = prediction_bundle["anchor_centers_xy"]
    reg_max = int(prediction_bundle["reg_max"])

    total_class_loss = class_logits.new_zeros(())
    total_box_loss = class_logits.new_zeros(())
    total_dfl_loss = class_logits.new_zeros(())
    total_foreground = 0
    total_target_score = class_logits.new_zeros(())

    for batch_index, target in enumerate(batch_targets):
        image_class_logits = class_logits[batch_index]
        image_class_probabilities = class_probabilities[batch_index]
        image_pred_boxes = pred_boxes[batch_index]
        target_scores = torch.zeros_like(image_class_logits)

        if target.boxes_xyxy:
            gt_boxes = torch.tensor(
                target.boxes_xyxy,
                device=image_pred_boxes.device,
                dtype=image_pred_boxes.dtype,
            )
            gt_classes = torch.tensor(
                target.category_indexes,
                device=image_pred_boxes.device,
                dtype=torch.long,
            )
            assignment = _assign_detection_targets(
                torch_module=torch,
                pred_boxes=image_pred_boxes,
                class_probabilities=image_class_probabilities,
                anchor_centers_xy=anchor_centers_xy,
                gt_boxes=gt_boxes,
                gt_classes=gt_classes,
                topk=assign_topk,
                alpha=assign_alpha,
                beta=assign_beta,
                topk2=assign_topk2,
            )
            if int(assignment["foreground_mask"].sum().item()) > 0:
                foreground_mask = assignment["foreground_mask"]
                assigned_gt_indices = assignment["assigned_gt_indices"][foreground_mask]
                quality_scores = assignment["quality_scores"][foreground_mask]
                target_scores[foreground_mask, gt_classes[assigned_gt_indices]] = quality_scores

                foreground_pred_boxes = image_pred_boxes[foreground_mask]
                foreground_gt_boxes = gt_boxes[assigned_gt_indices]
                iou_values = _box_iou_aligned(
                    torch_module=torch,
                    boxes1=foreground_pred_boxes,
                    boxes2=foreground_gt_boxes,
                ).clamp(0.0, 1.0)
                total_box_loss = total_box_loss + (1.0 - iou_values).sum()
                total_foreground += int(foreground_mask.sum().item())
                total_target_score = total_target_score + quality_scores.sum()

                foreground_anchor_points = anchor_points[foreground_mask]
                foreground_stride_tensor = stride_tensor[foreground_mask]
                target_distances = _bbox_xyxy_to_distances(
                    torch_module=torch,
                    boxes_xyxy=foreground_gt_boxes,
                    anchor_points=foreground_anchor_points,
                    stride_tensor=foreground_stride_tensor,
                    reg_max=reg_max,
                )
                if reg_max > 1:
                    foreground_distance_logits = distance_logits[batch_index][foreground_mask].view(-1, 4, reg_max)
                    total_dfl_loss = total_dfl_loss + _distribution_focal_loss(
                        torch_module=torch,
                        logits=foreground_distance_logits,
                        target=target_distances,
                    ).sum()
                else:
                    foreground_distance_logits = distance_logits[batch_index][foreground_mask].view(-1, 4)
                    total_dfl_loss = total_dfl_loss + torch.nn.functional.smooth_l1_loss(
                        torch.nn.functional.softplus(foreground_distance_logits),
                        target_distances,
                        reduction="sum",
                    )

        total_class_loss = total_class_loss + torch.nn.functional.binary_cross_entropy_with_logits(
            image_class_logits,
            target_scores,
            reduction="sum",
        )

    normalizer = total_target_score.clamp_min(1.0)
    class_loss = total_class_loss / normalizer
    foreground_normalizer = max(total_foreground, 1)
    box_loss = total_box_loss / foreground_normalizer
    dfl_loss = total_dfl_loss / foreground_normalizer
    total_loss = (
        class_loss * class_loss_weight
        + box_loss * box_loss_weight
        + dfl_loss * dfl_loss_weight
    )
    return {
        "loss": total_loss,
        "class_loss": class_loss,
        "box_loss": box_loss,
        "dfl_loss": dfl_loss,
    }


def _compute_e2e_detection_loss(
    *,
    imports: _TrainingImports,
    model: Any,
    raw_outputs: tuple[dict[str, Any], dict[str, Any]],
    batch_targets: tuple[_PreparedTrainingTarget, ...],
    num_classes: int,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    e2e_o2m_weight: float,
    e2e_o2o_weight: float,
    e2e_o2o_topk: int = 7,
    e2e_o2o_topk2: int = 1,
) -> dict[str, Any]:
    """计算端到端检测训练的双分支加权损失。

    E2E 训练同时优化两个分支：
    - one2many: 使用标准 TAL (topk=10) 分配，提供丰富的梯度信号
    - one2one: 使用精选 TAL (topk=7, topk2=1) 分配，生成高质量一对一标签用于推理

    损失通过可学习的权重调度器加权求和：
    total_loss = o2m_weight * one2many_loss + o2o_weight * one2one_loss

    权重在训练过程中动态调整：
    - 初期: o2m_weight=0.8, o2o_weight=0.2 (one2many 主导，提供充足梯度)
    - 末期: o2m_weight=0.1, o2o_weight=0.9 (one2one 主导，确保推理精度)
    """
    one2many_outputs, one2one_outputs = raw_outputs

    # 计算 one2many 分支损失（标准 TAL，topk=10）
    one2many_loss_components = _compute_detection_loss(
        imports=imports,
        model=model,
        raw_outputs=one2many_outputs,
        batch_targets=batch_targets,
        num_classes=num_classes,
        class_loss_weight=class_loss_weight,
        box_loss_weight=box_loss_weight,
        dfl_loss_weight=dfl_loss_weight,
        assign_topk=assign_topk,
        assign_alpha=assign_alpha,
        assign_beta=assign_beta,
    )

    # 计算 one2one 分支损失（精选 TAL，topk=7, topk2=1）
    one2one_loss_components = _compute_detection_loss(
        imports=imports,
        model=model,
        raw_outputs=one2one_outputs,
        batch_targets=batch_targets,
        num_classes=num_classes,
        class_loss_weight=class_loss_weight,
        box_loss_weight=box_loss_weight,
        dfl_loss_weight=dfl_loss_weight,
        assign_topk=e2e_o2o_topk,
        assign_alpha=assign_alpha,
        assign_beta=assign_beta,
        assign_topk2=e2e_o2o_topk2,
    )

    # 加权求和
    total_loss = (
        e2e_o2m_weight * one2many_loss_components["loss"]
        + e2e_o2o_weight * one2one_loss_components["loss"]
    )

    # 返回组合损失和两个分支的详细指标
    return {
        "loss": total_loss,
        "class_loss": one2one_loss_components["class_loss"],  # 日志只记录 one2one
        "box_loss": one2one_loss_components["box_loss"],
        "dfl_loss": one2one_loss_components["dfl_loss"],
        "one2many_loss": one2many_loss_components["loss"],
        "one2one_loss": one2one_loss_components["loss"],
        "e2e_o2m_weight": e2e_o2m_weight,
        "e2e_o2o_weight": e2e_o2o_weight,
    }


def _evaluate_detection_model(
    *,
    imports: _TrainingImports,
    model: Any,
    samples: tuple[_ResolvedTrainingSample, ...],
    category_ids: tuple[int, ...],
    annotation_file: Path | None,
    input_size: tuple[int, int],
    batch_size: int,
    device: str,
    runtime_precision: str,
    num_classes: int,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    confidence_threshold: float,
    nms_threshold: float,
) -> dict[str, object]:
    """在验证 split 上执行真实 detection loss 与 COCO mAP 评估。"""

    validation_losses = _evaluate_detection_validation_losses(
        imports=imports,
        model=model,
        samples=samples,
        input_size=input_size,
        batch_size=batch_size,
        device=device,
        runtime_precision=runtime_precision,
        num_classes=num_classes,
        class_loss_weight=class_loss_weight,
        box_loss_weight=box_loss_weight,
        dfl_loss_weight=dfl_loss_weight,
        assign_topk=assign_topk,
        assign_alpha=assign_alpha,
        assign_beta=assign_beta,
    )
    validation_map = _evaluate_validation_map(
        imports=imports,
        model=model,
        samples=samples,
        input_size=input_size,
        batch_size=batch_size,
        device=device,
        runtime_precision=runtime_precision,
        category_ids=category_ids,
        annotation_file=annotation_file,
        confidence_threshold=confidence_threshold,
        nms_threshold=nms_threshold,
    )
    return {
        "loss": round(float(validation_losses.get("loss", 0.0)), 6),
        "class_loss": round(float(validation_losses.get("class_loss", 0.0)), 6),
        "box_loss": round(float(validation_losses.get("box_loss", 0.0)), 6),
        "dfl_loss": round(float(validation_losses.get("dfl_loss", 0.0)), 6),
        "map50": round(float(validation_map.get("map50", 0.0)), 6),
        "map50_95": round(float(validation_map.get("map50_95", 0.0)), 6),
        "sample_count": len(samples),
    }


def _decode_detection_training_predictions(
    *,
    torch_module: Any,
    detect_head: Any,
    raw_outputs: dict[str, Any],
) -> dict[str, Any]:
    """把训练阶段原始输出解码成 loss 可直接消费的预测结构。"""

    distance_logits = raw_outputs["boxes"].permute(0, 2, 1).contiguous()
    if int(detect_head.reg_max) > 1:
        distances = detect_head.dfl(raw_outputs["boxes"])
    else:
        distances = torch_module.nn.functional.softplus(raw_outputs["boxes"])
    anchor_points, stride_tensor = _make_anchors(
        feature_maps=raw_outputs["feats"],
        strides=tuple(int(item) for item in detect_head.strides),
    )
    decoded_boxes = _dist2bbox_xyxy(
        distances=distances,
        anchor_points=anchor_points.unsqueeze(0),
        stride_tensor=stride_tensor.unsqueeze(0),
    )
    anchor_centers_xy = anchor_points * stride_tensor
    return {
        "distance_logits": distance_logits,
        "boxes_xyxy": decoded_boxes.permute(0, 2, 1).contiguous(),
        "class_logits": raw_outputs["scores"].permute(0, 2, 1).contiguous(),
        "anchor_points": anchor_points,
        "stride_tensor": stride_tensor,
        "anchor_centers_xy": anchor_centers_xy,
        "reg_max": int(detect_head.reg_max),
    }


def _assign_detection_targets(
    *,
    torch_module: Any,
    pred_boxes: Any,
    class_probabilities: Any,
    anchor_centers_xy: Any,
    gt_boxes: Any,
    gt_classes: Any,
    topk: int,
    alpha: float,
    beta: float,
    topk2: int | None = None,
) -> dict[str, Any]:
    """按 task-aligned 规则为当前图片分配正样本 anchor。

    Args:
        topk: 每个 gt 初始选择的候选 anchor 数量。
        topk2: 可选的二次精选参数。如果提供且 topk2 != topk，则在初始 topk 选择后
               进一步精选到 topk2 个 anchor，用于生成更高质量的一对一标签。
    """

    num_anchors = int(pred_boxes.shape[0])
    num_gt = int(gt_boxes.shape[0])
    if num_gt <= 0 or num_anchors <= 0:
        return {
            "foreground_mask": torch_module.zeros(num_anchors, dtype=torch_module.bool, device=pred_boxes.device),
            "assigned_gt_indices": torch_module.full(
                (num_anchors,),
                -1,
                dtype=torch_module.long,
                device=pred_boxes.device,
            ),
            "quality_scores": torch_module.zeros(num_anchors, dtype=pred_boxes.dtype, device=pred_boxes.device),
        }

    inside_mask = _build_anchor_inside_mask(
        torch_module=torch_module,
        anchor_centers_xy=anchor_centers_xy,
        gt_boxes=gt_boxes,
    )
    pair_iou = _box_iou_matrix(
        torch_module=torch_module,
        boxes1=gt_boxes,
        boxes2=pred_boxes,
    ).clamp(0.0, 1.0)
    gt_class_probabilities = class_probabilities[:, gt_classes].transpose(0, 1).clamp(0.0, 1.0)
    alignment_metric = (gt_class_probabilities.pow(alpha) * pair_iou.pow(beta)) * inside_mask.to(pair_iou.dtype)
    candidate_mask = torch_module.zeros_like(inside_mask)
    gt_centers = (gt_boxes[:, 0:2] + gt_boxes[:, 2:4]) * 0.5
    center_distances = torch_module.cdist(gt_centers, anchor_centers_xy)
    candidate_count = min(max(1, topk), num_anchors)

    for gt_index in range(num_gt):
        gt_metric = alignment_metric[gt_index]
        valid_indices = torch_module.nonzero(gt_metric > 0, as_tuple=False).squeeze(1)
        if int(valid_indices.numel()) == 0:
            fallback_index = int(torch_module.argmin(center_distances[gt_index]).item())
            candidate_mask[gt_index, fallback_index] = True
            alignment_metric[gt_index, fallback_index] = torch_module.maximum(
                alignment_metric[gt_index, fallback_index],
                alignment_metric.new_tensor(1e-4),
            )
            continue
        topk_count = min(candidate_count, int(valid_indices.numel()))
        topk_values, topk_indices = torch_module.topk(gt_metric, k=topk_count)
        valid_topk = topk_values > 0
        if bool(valid_topk.any()):
            candidate_mask[gt_index, topk_indices[valid_topk]] = True
        else:
            fallback_index = int(valid_indices[0].item())
            candidate_mask[gt_index, fallback_index] = True
            alignment_metric[gt_index, fallback_index] = torch_module.maximum(
                alignment_metric[gt_index, fallback_index],
                alignment_metric.new_tensor(1e-4),
            )

    # 如果提供了 topk2 且与 topk 不同，执行二次精选
    # 这是 E2E 训练中 one2one 分支的关键：从 topk 个候选中精选出 topk2 个最佳匹配
    if topk2 is not None and topk2 != topk:
        # 使用当前的 alignment_metric（已经过候选筛选）进行二次精选
        refined_metric = alignment_metric * candidate_mask.to(alignment_metric.dtype)
        refined_topk = min(max(1, topk2), num_anchors)
        # 对每个 gt 重新做 topk2 选择
        refined_candidate_mask = torch_module.zeros_like(candidate_mask)
        for gt_index in range(num_gt):
            gt_refined_metric = refined_metric[gt_index]
            valid_indices = torch_module.nonzero(gt_refined_metric > 0, as_tuple=False).squeeze(1)
            if int(valid_indices.numel()) == 0:
                # 没有有效候选，保持原候选
                refined_candidate_mask[gt_index] = candidate_mask[gt_index]
                continue
            refined_count = min(refined_topk, int(valid_indices.numel()))
            refined_values, refined_indices = torch_module.topk(gt_refined_metric, k=refined_count)
            valid_refined = refined_values > 0
            if bool(valid_refined.any()):
                refined_candidate_mask[gt_index, refined_indices[valid_refined]] = True
            else:
                refined_candidate_mask[gt_index] = candidate_mask[gt_index]
        candidate_mask = refined_candidate_mask
        # 更新 alignment_metric 以反映二次精选后的结果
        alignment_metric = alignment_metric * candidate_mask.to(alignment_metric.dtype)

    matched_metric = alignment_metric * candidate_mask.to(alignment_metric.dtype)
    quality_scores, assigned_gt_indices = matched_metric.max(dim=0)
    foreground_mask = quality_scores > 0
    if bool(foreground_mask.any()):
        matched_gt_indices = assigned_gt_indices[foreground_mask]
        max_metric_per_gt = matched_metric.max(dim=1).values.clamp_min(1e-6)
        normalized_scores = quality_scores[foreground_mask] / max_metric_per_gt[matched_gt_indices]
        quality_scores = quality_scores.clone()
        quality_scores[foreground_mask] = normalized_scores.clamp(0.0, 1.0)
    assigned_gt_indices = assigned_gt_indices.to(dtype=torch_module.long)
    assigned_gt_indices = assigned_gt_indices.where(
        foreground_mask,
        torch_module.full_like(assigned_gt_indices, -1),
    )
    return {
        "foreground_mask": foreground_mask,
        "assigned_gt_indices": assigned_gt_indices,
        "quality_scores": quality_scores,
    }


def _build_anchor_inside_mask(
    *,
    torch_module: Any,
    anchor_centers_xy: Any,
    gt_boxes: Any,
) -> Any:
    """判断 anchor center 是否落在 gt bbox 内部。"""

    center_x = anchor_centers_xy[:, 0].unsqueeze(0)
    center_y = anchor_centers_xy[:, 1].unsqueeze(0)
    return (
        (center_x >= gt_boxes[:, 0:1])
        & (center_x <= gt_boxes[:, 2:3])
        & (center_y >= gt_boxes[:, 1:2])
        & (center_y <= gt_boxes[:, 3:4])
    )


def _box_iou_matrix(
    *,
    torch_module: Any,
    boxes1: Any,
    boxes2: Any,
) -> Any:
    """计算两组 xyxy bbox 的两两 IoU。"""

    if int(boxes1.shape[0]) == 0 or int(boxes2.shape[0]) == 0:
        return torch_module.zeros(
            (int(boxes1.shape[0]), int(boxes2.shape[0])),
            device=boxes1.device,
            dtype=boxes1.dtype,
        )
    top_left = torch_module.maximum(boxes1[:, None, 0:2], boxes2[None, :, 0:2])
    bottom_right = torch_module.minimum(boxes1[:, None, 2:4], boxes2[None, :, 2:4])
    overlap = (bottom_right - top_left).clamp_min(0.0)
    intersection = overlap[..., 0] * overlap[..., 1]
    area1 = ((boxes1[:, 2] - boxes1[:, 0]).clamp_min(0.0) * (boxes1[:, 3] - boxes1[:, 1]).clamp_min(0.0)).unsqueeze(1)
    area2 = ((boxes2[:, 2] - boxes2[:, 0]).clamp_min(0.0) * (boxes2[:, 3] - boxes2[:, 1]).clamp_min(0.0)).unsqueeze(0)
    union = area1 + area2 - intersection
    return intersection / union.clamp_min(1e-6)


def _box_iou_aligned(
    *,
    torch_module: Any,
    boxes1: Any,
    boxes2: Any,
) -> Any:
    """计算一一对应的两组 bbox IoU。"""

    top_left = torch_module.maximum(boxes1[:, 0:2], boxes2[:, 0:2])
    bottom_right = torch_module.minimum(boxes1[:, 2:4], boxes2[:, 2:4])
    overlap = (bottom_right - top_left).clamp_min(0.0)
    intersection = overlap[:, 0] * overlap[:, 1]
    area1 = (boxes1[:, 2] - boxes1[:, 0]).clamp_min(0.0) * (boxes1[:, 3] - boxes1[:, 1]).clamp_min(0.0)
    area2 = (boxes2[:, 2] - boxes2[:, 0]).clamp_min(0.0) * (boxes2[:, 3] - boxes2[:, 1]).clamp_min(0.0)
    union = area1 + area2 - intersection
    return intersection / union.clamp_min(1e-6)


def _bbox_xyxy_to_distances(
    *,
    torch_module: Any,
    boxes_xyxy: Any,
    anchor_points: Any,
    stride_tensor: Any,
    reg_max: int,
) -> Any:
    """把正样本 gt bbox 转成 DFL 或 LTRB 回归目标。"""

    stride = stride_tensor.view(-1, 1).clamp_min(1e-6)
    scaled_boxes = boxes_xyxy / stride.repeat(1, 4)
    left = anchor_points[:, 0] - scaled_boxes[:, 0]
    top = anchor_points[:, 1] - scaled_boxes[:, 1]
    right = scaled_boxes[:, 2] - anchor_points[:, 0]
    bottom = scaled_boxes[:, 3] - anchor_points[:, 1]
    distances = torch_module.stack((left, top, right, bottom), dim=1).clamp_min(0.0)
    if reg_max > 1:
        return distances.clamp(max=float(reg_max) - 1.0001)
    return distances


def _distribution_focal_loss(
    *,
    torch_module: Any,
    logits: Any,
    target: Any,
) -> Any:
    """计算 DFL 损失。"""

    reg_max = int(logits.shape[2])
    target_left = target.clamp(0, reg_max - 1 - 0.01).floor().long()
    target_right = (target_left + 1).clamp(0, reg_max - 1)
    weight_left = target_right.to(target.dtype) - target
    weight_right = 1.0 - weight_left
    flat_logits = logits.reshape(-1, reg_max)
    loss_left = torch_module.nn.functional.cross_entropy(
        flat_logits,
        target_left.reshape(-1),
        reduction="none",
    )
    loss_right = torch_module.nn.functional.cross_entropy(
        flat_logits,
        target_right.reshape(-1),
        reduction="none",
    )
    combined = (
        loss_left * weight_left.reshape(-1)
        + loss_right * weight_right.reshape(-1)
    )
    return combined.view(-1, 4).sum(dim=1)


def _evaluate_detection_validation_losses(
    *,
    imports: _TrainingImports,
    model: Any,
    samples: tuple[_ResolvedTrainingSample, ...],
    input_size: tuple[int, int],
    batch_size: int,
    device: str,
    runtime_precision: str,
    num_classes: int,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
) -> dict[str, float]:
    """在验证集上统计真实 detection 验证损失。"""

    if not samples:
        return {"loss": 0.0, "class_loss": 0.0, "box_loss": 0.0, "dfl_loss": 0.0}

    torch = imports.torch
    autocast_context = _build_autocast_context(
        imports=imports,
        device=device,
        runtime_precision=runtime_precision,
    )
    previous_training_mode = bool(model.training)
    model.train()
    batch_norm_states = _freeze_batch_norm_modules(imports=imports, model=model)
    epoch_totals = {"loss": 0.0, "class_loss": 0.0, "box_loss": 0.0, "dfl_loss": 0.0}
    batch_count = 0
    try:
        with torch.no_grad():
            for batch_samples in _iter_batches(list(samples), batch_size):
                images, batch_targets = _build_training_batch(
                    imports=imports,
                    samples=batch_samples,
                    input_size=input_size,
                    device=device,
                    runtime_precision=runtime_precision,
                )
                with autocast_context():
                    raw_outputs = _unwrap_detection_outputs(model(images))
                    loss_components = _compute_detection_loss(
                        imports=imports,
                        model=model,
                        raw_outputs=raw_outputs,
                        batch_targets=batch_targets,
                        num_classes=num_classes,
                        class_loss_weight=class_loss_weight,
                        box_loss_weight=box_loss_weight,
                        dfl_loss_weight=dfl_loss_weight,
                        assign_topk=assign_topk,
                        assign_alpha=assign_alpha,
                        assign_beta=assign_beta,
                    )
                batch_count += 1
                for metric_name in epoch_totals:
                    epoch_totals[metric_name] += float(loss_components[metric_name].detach().item())
    finally:
        _restore_batch_norm_modules(batch_norm_states)
        model.train(previous_training_mode)
    if batch_count <= 0:
        return {"loss": 0.0, "class_loss": 0.0, "box_loss": 0.0, "dfl_loss": 0.0}
    return {
        metric_name: round(metric_total / batch_count, 6)
        for metric_name, metric_total in epoch_totals.items()
    }


def _evaluate_validation_map(
    *,
    imports: _TrainingImports,
    model: Any,
    samples: tuple[_ResolvedTrainingSample, ...],
    input_size: tuple[int, int],
    batch_size: int,
    device: str,
    runtime_precision: str,
    category_ids: tuple[int, ...],
    annotation_file: Path | None,
    confidence_threshold: float,
    nms_threshold: float,
) -> dict[str, float]:
    """执行一次真实 COCO mAP 评估。"""

    if not samples or annotation_file is None:
        return {"map50": 0.0, "map50_95": 0.0}
    if imports.COCO is None or imports.COCOeval is None:
        raise ServiceConfigurationError("当前环境缺少 pycocotools，无法执行 detection mAP 验证")

    torch = imports.torch
    previous_training_mode = bool(model.training)
    model.eval()
    detections: list[dict[str, object]] = []
    try:
        with torch.no_grad():
            for batch_samples in _iter_batches(list(samples), batch_size):
                images, batch_targets = _build_training_batch(
                    imports=imports,
                    samples=batch_samples,
                    input_size=input_size,
                    device=device,
                    runtime_precision=runtime_precision,
                )
                prediction_tensor = model(images)
                detections.extend(
                    _convert_primary_predictions_to_coco_detections(
                        imports=imports,
                        prediction_tensor=prediction_tensor,
                        batch_targets=batch_targets,
                        input_size=input_size,
                        category_ids=category_ids,
                        confidence_threshold=confidence_threshold,
                        nms_threshold=nms_threshold,
                    )
                )
    finally:
        model.train(previous_training_mode)

    if not detections:
        return {"map50": 0.0, "map50_95": 0.0}

    ground_truth = _load_coco_ground_truth_silently(
        imports=imports,
        annotation_file=annotation_file,
    )
    with redirect_stdout(io.StringIO()):
        coco_detections = ground_truth.loadRes(detections)
        coco_evaluator = imports.COCOeval(ground_truth, coco_detections, "bbox")
        coco_evaluator.evaluate()
        coco_evaluator.accumulate()
        coco_evaluator.summarize()
    return {
        "map50_95": float(coco_evaluator.stats[0]),
        "map50": float(coco_evaluator.stats[1]),
    }


def _convert_primary_predictions_to_coco_detections(
    *,
    imports: _TrainingImports,
    prediction_tensor: Any,
    batch_targets: tuple[_PreparedTrainingTarget, ...],
    input_size: tuple[int, int],
    category_ids: tuple[int, ...],
    confidence_threshold: float,
    nms_threshold: float,
) -> list[dict[str, object]]:
    """把主线 detection 预测结果转换为 COCO detection 列表。"""

    np_module = imports.np
    prediction_array = prediction_tensor.detach().cpu().numpy()
    postprocess_results = _postprocess_yolo_primary_prediction_array(
        prediction_array=prediction_array,
        np_module=np_module,
        num_classes=len(category_ids),
        score_threshold=confidence_threshold,
        nms_threshold=nms_threshold,
    )
    detections: list[dict[str, object]] = []
    for batch_index, result in enumerate(postprocess_results):
        if result is None:
            continue
        target = batch_targets[batch_index]
        scale_x = float(input_size[1]) / max(1.0, float(target.image_width))
        scale_y = float(input_size[0]) / max(1.0, float(target.image_height))
        for bbox, score, class_id in zip(
            result["boxes_xyxy"],
            result["scores"],
            result["class_ids"],
            strict=True,
        ):
            x1 = max(0.0, min(float(bbox[0]) / scale_x, float(target.image_width)))
            y1 = max(0.0, min(float(bbox[1]) / scale_y, float(target.image_height)))
            x2 = max(0.0, min(float(bbox[2]) / scale_x, float(target.image_width)))
            y2 = max(0.0, min(float(bbox[3]) / scale_y, float(target.image_height)))
            width = max(0.0, x2 - x1)
            height = max(0.0, y2 - y1)
            resolved_class_id = int(class_id)
            if width <= 0 or height <= 0 or resolved_class_id < 0 or resolved_class_id >= len(category_ids):
                continue
            detections.append(
                {
                    "image_id": target.image_id,
                    "category_id": category_ids[resolved_class_id],
                    "bbox": [x1, y1, width, height],
                    "score": float(score),
                }
            )
    return detections


def _postprocess_yolo_primary_prediction_array(
    *,
    prediction_array: Any,
    np_module: Any,
    num_classes: int,
    score_threshold: float,
    nms_threshold: float,
) -> list[dict[str, Any] | None]:
    """执行主线 detection 输出的阈值过滤与 NMS。"""

    normalized_prediction = np_module.asarray(prediction_array, dtype=np_module.float32)
    if normalized_prediction.ndim == 2:
        normalized_prediction = np_module.expand_dims(normalized_prediction, axis=0)
    if normalized_prediction.ndim < 3:
        raise InvalidRequestError(
            "YOLO 主线推理输出维度不合法",
            details={"shape": list(normalized_prediction.shape)},
        )
    if int(normalized_prediction.shape[2]) < 4 + num_classes:
        raise InvalidRequestError(
            "YOLO 主线推理输出通道数不足",
            details={
                "channel_count": int(normalized_prediction.shape[2]),
                "required_channel_count": 4 + num_classes,
            },
        )

    results: list[dict[str, Any] | None] = []
    for image_prediction in normalized_prediction:
        boxes = image_prediction[:, :4]
        class_scores = image_prediction[:, 4 : 4 + num_classes]
        if int(boxes.shape[0]) <= 0:
            results.append(None)
            continue
        best_scores = np_module.max(class_scores, axis=1)
        best_class_ids = np_module.argmax(class_scores, axis=1).astype(np_module.int32, copy=False)
        keep_mask = best_scores >= score_threshold
        boxes = boxes[keep_mask]
        best_scores = best_scores[keep_mask]
        best_class_ids = best_class_ids[keep_mask]
        if int(boxes.shape[0]) <= 0:
            results.append(None)
            continue
        keep_indices = batched_nms_indices(
            boxes=boxes,
            scores=best_scores,
            class_ids=best_class_ids,
            nms_threshold=nms_threshold,
            np_module=np_module,
        )
        if int(keep_indices.size) <= 0:
            results.append(None)
            continue
        results.append(
            {
                "boxes_xyxy": boxes[keep_indices],
                "scores": best_scores[keep_indices],
                "class_ids": best_class_ids[keep_indices],
            }
        )
    return results


def _load_coco_ground_truth_silently(
    *,
    imports: _TrainingImports,
    annotation_file: Path,
) -> Any:
    """静默加载 COCO ground truth。"""

    if imports.COCO is None:
        raise ServiceConfigurationError("当前环境缺少 pycocotools.COCO")
    with redirect_stdout(io.StringIO()):
        return imports.COCO(str(annotation_file))


def _freeze_batch_norm_modules(
    *,
    imports: _TrainingImports,
    model: Any,
) -> tuple[tuple[Any, bool], ...]:
    """在验证阶段冻结 BatchNorm 的统计更新。"""

    batch_norm_states: list[tuple[Any, bool]] = []
    for module in model.modules():
        if isinstance(module, imports.torch.nn.BatchNorm2d):
            batch_norm_states.append((module, bool(module.training)))
            module.eval()
    return tuple(batch_norm_states)


def _restore_batch_norm_modules(batch_norm_states: tuple[tuple[Any, bool], ...]) -> None:
    """恢复验证前 BatchNorm 的训练状态。"""

    for module, was_training in batch_norm_states:
        module.train(was_training)


def _normalize_history_items(value: object) -> list[dict[str, object]]:
    """把 checkpoint 中的指标历史归一成可继续追加的列表。"""

    if not isinstance(value, list):
        return []
    normalized_items: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, dict):
            normalized_items.append({str(key): current_value for key, current_value in item.items()})
    return normalized_items


def _normalize_evaluated_epochs(value: object) -> tuple[int, ...]:
    """把 checkpoint 中的验证 epoch 列表归一成整数元组。"""

    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, int) and item > 0)


def _move_optimizer_state_to_device(*, optimizer: Any, device: str) -> None:
    """把 optimizer 状态里的张量迁移到当前训练设备。"""

    for state in optimizer.state.values():
        if not isinstance(state, dict):
            continue
        for key, value in tuple(state.items()):
            if hasattr(value, "to"):
                state[key] = value.to(device=device)


def _build_checkpoint_state(
    *,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any,
    model_type: str,
    model_scale: str,
    category_names: tuple[str, ...],
    input_size: tuple[int, int],
    batch_size: int,
    max_epochs: int,
    epoch: int,
    precision: str,
    validation_split_name: str | None,
    evaluation_interval: int | None,
    evaluation_confidence_threshold: float | None,
    evaluation_nms_threshold: float | None,
    learning_rate: float,
    weight_decay: float,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    min_lr_ratio: float,
    grad_clip_norm: float,
    metrics_history: list[dict[str, object]],
    validation_history: list[dict[str, object]],
    evaluated_epochs: tuple[int, ...],
    warm_start_summary: dict[str, object],
    implementation_mode: str,
    best_metric_name: str,
    best_metric_value: float | None,
    best_checkpoint_state: dict[str, object] | None,
) -> dict[str, object]:
    """构建一个可直接序列化保存的项目内训练 checkpoint 状态。"""

    return {
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "scheduler_state_dict": scheduler.state_dict(),
        "scaler_state_dict": scaler.state_dict(),
        "model_type": model_type,
        "model_scale": model_scale,
        "category_names": list(category_names),
        "input_size": list(input_size),
        "batch_size": batch_size,
        "max_epochs": max_epochs,
        "epoch": epoch,
        "precision": precision,
        "validation_split_name": validation_split_name,
        "evaluation_interval": evaluation_interval,
        "evaluation_confidence_threshold": evaluation_confidence_threshold,
        "evaluation_nms_threshold": evaluation_nms_threshold,
        "learning_rate": learning_rate,
        "weight_decay": weight_decay,
        "class_loss_weight": class_loss_weight,
        "box_loss_weight": box_loss_weight,
        "dfl_loss_weight": dfl_loss_weight,
        "assign_topk": assign_topk,
        "assign_alpha": assign_alpha,
        "assign_beta": assign_beta,
        "min_lr_ratio": min_lr_ratio,
        "grad_clip_norm": grad_clip_norm,
        "metrics_history": metrics_history,
        "validation_history": validation_history,
        "evaluated_epochs": list(evaluated_epochs),
        "warm_start": warm_start_summary,
        "implementation_mode": implementation_mode,
        "best_metric_name": best_metric_name,
        "best_metric_value": best_metric_value,
        "best_checkpoint_state": best_checkpoint_state,
    }


def _build_checkpoint_bytes(
    *,
    imports: _TrainingImports,
    model: Any,
    optimizer: Any,
    scheduler: Any,
    scaler: Any,
    model_type: str,
    model_scale: str,
    category_names: tuple[str, ...],
    input_size: tuple[int, int],
    batch_size: int,
    max_epochs: int,
    epoch: int,
    precision: str,
    validation_split_name: str | None,
    evaluation_interval: int | None,
    evaluation_confidence_threshold: float | None,
    evaluation_nms_threshold: float | None,
    learning_rate: float,
    weight_decay: float,
    class_loss_weight: float,
    box_loss_weight: float,
    dfl_loss_weight: float,
    assign_topk: int,
    assign_alpha: float,
    assign_beta: float,
    min_lr_ratio: float,
    grad_clip_norm: float,
    metrics_history: list[dict[str, object]],
    validation_history: list[dict[str, object]],
    evaluated_epochs: tuple[int, ...],
    warm_start_summary: dict[str, object],
    implementation_mode: str,
    best_metric_name: str,
    best_metric_value: float | None,
    best_checkpoint_state: dict[str, object] | None,
) -> bytes:
    """把当前训练状态导出为项目内 checkpoint。"""

    checkpoint_state = _build_checkpoint_state(
        model=model,
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=scaler,
        model_type=model_type,
        model_scale=model_scale,
        category_names=category_names,
        input_size=input_size,
        batch_size=batch_size,
        max_epochs=max_epochs,
        epoch=epoch,
        precision=precision,
        validation_split_name=validation_split_name,
        evaluation_interval=evaluation_interval,
        evaluation_confidence_threshold=evaluation_confidence_threshold,
        evaluation_nms_threshold=evaluation_nms_threshold,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
        class_loss_weight=class_loss_weight,
        box_loss_weight=box_loss_weight,
        dfl_loss_weight=dfl_loss_weight,
        assign_topk=assign_topk,
        assign_alpha=assign_alpha,
        assign_beta=assign_beta,
        min_lr_ratio=min_lr_ratio,
        grad_clip_norm=grad_clip_norm,
        metrics_history=metrics_history,
        validation_history=validation_history,
        evaluated_epochs=evaluated_epochs,
        warm_start_summary=warm_start_summary,
        implementation_mode=implementation_mode,
        best_metric_name=best_metric_name,
        best_metric_value=best_metric_value,
        best_checkpoint_state=best_checkpoint_state,
    )
    buffer = io.BytesIO()
    imports.torch.save(checkpoint_state, buffer)
    return buffer.getvalue()


def _build_checkpoint_bytes_from_state(
    *,
    imports: _TrainingImports,
    checkpoint_state: dict[str, object] | None,
) -> bytes:
    """把已缓存的 checkpoint 状态重新编码成二进制。"""

    if checkpoint_state is None:
        return b""
    buffer = io.BytesIO()
    imports.torch.save(checkpoint_state, buffer)
    return buffer.getvalue()


def _load_checkpoint_state_from_bytes(
    *,
    imports: _TrainingImports,
    checkpoint_bytes: bytes,
) -> dict[str, object]:
    """从 checkpoint 二进制反序列化为字典状态。"""

    payload = imports.torch.load(io.BytesIO(checkpoint_bytes), map_location="cpu")
    if not isinstance(payload, dict):
        raise InvalidRequestError("checkpoint 内容不合法")
    return dict(payload)


def _read_float_option(
    extra_options: dict[str, object],
    key: str,
    *,
    default: float,
) -> float:
    """从 extra_options 里读取浮点数配置。"""

    value = extra_options.get(key, default)
    if not isinstance(value, int | float):
        raise InvalidRequestError(
            "训练 extra_options 中的数值配置不合法",
            details={"option_key": key, "value": value},
        )
    return float(value)


def _read_int_option(
    extra_options: dict[str, object],
    key: str,
    *,
    default: int,
) -> int:
    """从 extra_options 里读取整数字段。"""

    value = extra_options.get(key, default)
    if not isinstance(value, int):
        raise InvalidRequestError(
            "训练 extra_options 中的整数配置不合法",
            details={"option_key": key, "value": value},
        )
    return int(value)
