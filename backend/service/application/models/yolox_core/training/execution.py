"""YOLOX detection 训练执行 core。"""

from __future__ import annotations

import gc
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.models.yolox_core.cfg import (
    resolve_yolox_input_size,
)
from backend.service.application.models.yolox_core.data.datasets import (
    CocoDetectionExportDataset as _CocoDetectionExportDataset,
    VocDetectionExportDataset as _VocDetectionExportDataset,
    YoloXDetectionDataset as _CoreYoloXDetectionDataset,
    YoloXDetectionSplit as _CoreYoloXDetectionSplit,
    build_yolox_detection_dataset as _build_yolox_detection_dataset,
    get_yolox_detection_evaluation_annotation_file as _get_yolox_detection_evaluation_annotation_file,
)
from backend.service.application.models.yolox_core.data.datasets import (
    resolve_train_split as _core_resolve_train_split,
)
from backend.service.application.models.yolox_core.data.datasets import (
    resolve_validation_split as _core_resolve_validation_split,
)
from backend.service.application.models.yolox_core.data.datasets import (
    resolve_yolox_detection_splits as _core_resolve_yolox_detection_splits,
)
from backend.service.application.models.yolox_core.dependencies import (
    YoloXCoreDependencies,
    require_yolox_core_dependencies,
)
from backend.service.application.models.yolox_core.evaluators import (
    evaluate_yolox_coco_map,
    evaluate_yolox_voc_map,
    evaluate_yolox_validation_losses,
)
from backend.service.application.models.yolox_core.models.build import (
    build_yolox_detection_model,
)
from backend.service.application.models.yolox_core.training.trainer import (
    YOLOX_DEFAULT_TRAIN_ENABLE_MIXUP,
    YOLOX_DEFAULT_TRAIN_FLIP_PROB,
    YOLOX_DEFAULT_TRAIN_HSV_PROB,
    YOLOX_DEFAULT_TRAIN_MIXUP_PROB,
    YOLOX_DEFAULT_TRAIN_MOSAIC_PROB,
    YOLOX_DEFAULT_TRAIN_MULTISCALE_RANGE,
    YOLOX_CORE_DEFAULT_BATCH_SIZE,
    YOLOX_CORE_DEFAULT_EVAL_CONFIDENCE_THRESHOLD,
    YOLOX_CORE_DEFAULT_EVAL_NMS_THRESHOLD,
    YOLOX_CORE_DEFAULT_EVALUATION_INTERVAL,
    YOLOX_CORE_DEFAULT_MAX_EPOCHS,
    YOLOX_DETECTION_CORE_IMPLEMENTATION_MODE,
    YOLOX_REFERENCE_DEFAULT_DEGREES,
    YOLOX_REFERENCE_DEFAULT_EMA_ENABLED,
    YOLOX_REFERENCE_DEFAULT_MAX_LABELS,
    YOLOX_REFERENCE_DEFAULT_MIXUP_SCALE,
    YOLOX_REFERENCE_DEFAULT_MOSAIC_SCALE,
    YOLOX_REFERENCE_DEFAULT_SHEAR,
    YOLOX_REFERENCE_DEFAULT_TRANSLATE,
    YoloXTrainingBatchProgress,
    YoloXTrainingControlCommand,
    YoloXTrainingEpochProgress,
    YoloXTrainingLoopRequest,
    YoloXTrainingSavePoint,
    build_yolox_lr_scheduler,
    build_yolox_model_ema,
    run_yolox_training_loop,
)
from backend.service.application.models.yolox_core.training.trainer import (
    LoadedYoloXResumeState as _LoadedResumeState,
)
from backend.service.application.models.yolox_core.training.trainer import (
    build_yolox_autocast_context as _build_autocast_context,
)
from backend.service.application.models.yolox_core.training.trainer import (
    build_yolox_optimizer as _build_optimizer,
)
from backend.service.application.models.yolox_core.training.trainer import (
    load_yolox_resume_checkpoint as _load_resume_checkpoint,
)
from backend.service.application.models.yolox_core.training.trainer import (
    resolve_yolox_training_schedule_options as _resolve_training_schedule_options,
)
from backend.service.application.models.yolox_core.weights import (
    load_yolox_warm_start_checkpoint,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class YoloXDetectionTrainingExecutionRequest:
    """描述一次最小 YOLOX detection 训练执行请求。

    字段：
    - dataset_storage：本地文件存储服务。
    - manifest_payload：DatasetExport manifest 内容。
    - model_scale：当前训练使用的 model scale。
    - evaluation_interval：每隔多少个 epoch 执行一次真实验证评估；为空时使用默认值。
    - max_epochs：最大训练 epoch 数；为空时使用最小默认值。
    - batch_size：训练 batch size；为空时使用最小默认值。
    - gpu_count：当前只接受 1；为空时按单 GPU 或 CPU 回退。
    - precision：请求使用的训练 precision。
    - warm_start_checkpoint_path：warm start checkpoint 的绝对路径。
    - resume_checkpoint_path：恢复训练使用的 latest checkpoint 绝对路径。
    - warm_start_source_summary：warm start 来源摘要。
    - input_size：训练输入尺寸；为空时使用最小默认值。
    - extra_options：附加训练选项。
    - batch_callback：每个 batch 完成后的 heartbeat 回调。
    - epoch_callback：每轮训练结束后的进度回写回调；返回值可携带 save/pause 控制命令。
    - savepoint_callback：当训练收到手动保存或暂停请求时回传当前 savepoint。
    """

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_scale: str
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
    batch_callback: Callable[["YoloXTrainingBatchProgress"], None] | None = None
    epoch_callback: Callable[
        ["YoloXTrainingEpochProgress"],
        "YoloXTrainingControlCommand | None",
    ] | None = None
    savepoint_callback: Callable[["YoloXTrainingSavePoint"], None] | None = None


@dataclass(frozen=True)
class YoloXDetectionTrainingExecutionResult:
    """描述一次最小 YOLOX detection 训练执行结果。

    字段：
    - checkpoint_bytes：训练生成的 checkpoint 二进制内容。
    - latest_checkpoint_bytes：训练结束时的最新 checkpoint 二进制内容。
    - metrics_payload：训练指标摘要。
    - validation_metrics_payload：验证指标摘要。
    - warm_start_summary：warm start 加载摘要。
    - implementation_mode：当前训练执行模式标识。
    - best_metric_name：最佳指标名称。
    - best_metric_value：最佳指标值。
    - evaluation_interval：真实验证评估周期。
    - category_names：训练使用的类别名列表。
    - split_names：manifest 中可见的 split 列表。
    - sample_count：manifest 中记录的总样本数。
    - train_sample_count：实际参与训练的样本数。
    - input_size：实际训练输入尺寸。
    - batch_size：实际训练 batch size。
    - max_epochs：实际训练 epoch 数。
    - device：实际训练使用的 device。
    - gpu_count：实际参与训练的 GPU 数量。
    - device_ids：实际参与训练的 GPU 编号列表。
    - distributed_mode：当前训练的设备并行模式。
    - precision：实际训练使用的 precision。
    - validation_split_name：当前训练使用的验证 split 名称。
    - validation_sample_count：实际参与验证的样本数。
    - parameter_count：模型参数总量。
    """

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


_YoloXDetectionDataset = _CoreYoloXDetectionDataset
_ResolvedYoloXDetectionSplit = _CoreYoloXDetectionSplit


@dataclass(frozen=True)
class _ResolvedTrainingRuntime:
    """描述当前训练请求解析后的运行时资源。

    字段：
    - device：训练主 device。
    - gpu_count：实际参与训练的 GPU 数量。
    - device_ids：实际参与训练的 GPU 编号列表。
    - distributed_mode：当前训练的设备并行模式。
    """

    device: str
    gpu_count: int
    device_ids: tuple[int, ...]
    distributed_mode: str


class YoloXTrainingPausedError(Exception):
    """表示训练在 epoch 边界按请求完成保存后进入 paused 状态。"""

    def __init__(self, savepoint: YoloXTrainingSavePoint) -> None:
        """初始化暂停异常。

        参数：
        - savepoint：暂停前最后一次导出的 savepoint。
        """

        super().__init__("yolox training paused")
        self.savepoint = savepoint


class YoloXTrainingTerminatedError(Exception):
    """表示训练在 epoch 边界按请求终止。"""

    def __init__(self) -> None:
        """初始化终止异常。"""

        super().__init__("yolox training terminated")


def run_yolox_detection_training_execution(
    request: YoloXDetectionTrainingExecutionRequest,
) -> YoloXDetectionTrainingExecutionResult:
    """执行 YOLOX detection 训练链路。

    参数：
    - request：训练执行请求。

    返回：
    - 训练执行结果。
    """

    imports = require_yolox_core_dependencies()
    manifest_payload = dict(request.manifest_payload)
    resolved_splits = _resolve_yolox_detection_splits(request.dataset_storage, manifest_payload)
    train_split = _resolve_train_split(resolved_splits)
    input_size = _resolve_input_size(request.input_size)
    current_input_size = input_size
    batch_size = max(1, request.batch_size or YOLOX_CORE_DEFAULT_BATCH_SIZE)
    max_epochs = max(1, request.max_epochs or YOLOX_CORE_DEFAULT_MAX_EPOCHS)
    extra_options = dict(request.extra_options or {})
    evaluation_interval = max(
        1,
        request.evaluation_interval
        or _read_int_option(
            extra_options,
            "evaluation_interval",
            default=YOLOX_CORE_DEFAULT_EVALUATION_INTERVAL,
        ),
    )
    runtime = _resolve_training_runtime(
        imports=imports,
        requested_gpu_count=request.gpu_count,
        extra_options=extra_options,
    )
    precision = _resolve_precision(
        imports=imports,
        requested_precision=request.precision,
        device=runtime.device,
        extra_options=extra_options,
    )
    flip_prob = _read_float_option(
        extra_options,
        "flip_prob",
        default=YOLOX_DEFAULT_TRAIN_FLIP_PROB,
    )
    hsv_prob = _read_float_option(
        extra_options,
        "hsv_prob",
        default=YOLOX_DEFAULT_TRAIN_HSV_PROB,
    )
    max_labels = _read_int_option(
        extra_options,
        "max_labels",
        default=YOLOX_REFERENCE_DEFAULT_MAX_LABELS,
    )
    mosaic_prob = _read_float_option(
        extra_options,
        "mosaic_prob",
        default=YOLOX_DEFAULT_TRAIN_MOSAIC_PROB,
    )
    mixup_prob = _read_float_option(
        extra_options,
        "mixup_prob",
        default=YOLOX_DEFAULT_TRAIN_MIXUP_PROB,
    )
    degrees = _read_float_option(
        extra_options,
        "degrees",
        default=YOLOX_REFERENCE_DEFAULT_DEGREES,
    )
    translate = _read_float_option(
        extra_options,
        "translate",
        default=YOLOX_REFERENCE_DEFAULT_TRANSLATE,
    )
    mosaic_scale = _read_float_pair_option(
        extra_options,
        "mosaic_scale",
        default=YOLOX_REFERENCE_DEFAULT_MOSAIC_SCALE,
    )
    mixup_scale = _read_float_pair_option(
        extra_options,
        "mixup_scale",
        default=YOLOX_REFERENCE_DEFAULT_MIXUP_SCALE,
    )
    shear = _read_float_option(
        extra_options,
        "shear",
        default=YOLOX_REFERENCE_DEFAULT_SHEAR,
    )
    enable_mixup = _read_bool_option(
        extra_options,
        "enable_mixup",
        default=YOLOX_DEFAULT_TRAIN_ENABLE_MIXUP,
    )
    num_workers = _read_int_option(extra_options, "num_workers", default=0)
    random_seed = _read_int_option(extra_options, "seed", default=0)
    multiscale_range = max(
        0,
        _read_int_option(
            extra_options,
            "multiscale_range",
            default=YOLOX_DEFAULT_TRAIN_MULTISCALE_RANGE,
        ),
    )
    ema_enabled = _read_bool_option(
        extra_options,
        "ema",
        default=YOLOX_REFERENCE_DEFAULT_EMA_ENABLED,
    )
    warmup_epochs, no_aug_epochs, min_lr_ratio = _resolve_training_schedule_options(
        extra_options=extra_options,
        max_epochs=max_epochs,
    )
    evaluation_confidence_threshold = _read_float_option(
        extra_options,
        "evaluation_confidence_threshold",
        default=YOLOX_CORE_DEFAULT_EVAL_CONFIDENCE_THRESHOLD,
    )
    evaluation_nms_threshold = _read_float_option(
        extra_options,
        "evaluation_nms_threshold",
        default=YOLOX_CORE_DEFAULT_EVAL_NMS_THRESHOLD,
    )
    imports.torch.manual_seed(random_seed)
    if runtime.device.startswith("cuda"):
        imports.torch.cuda.manual_seed_all(random_seed)

    train_base_dataset = _build_yolox_detection_dataset(
        split=train_split,
        input_size=input_size,
        imports=imports,
        flip_prob=flip_prob,
        hsv_prob=hsv_prob,
        max_labels=max_labels,
    )
    mosaic_augmentation_enabled = mosaic_prob > 0.0
    use_augmentation_data_pipeline = mosaic_augmentation_enabled or multiscale_range > 0
    if mosaic_augmentation_enabled:
        train_dataset = imports.MosaicDetection(
            dataset=train_base_dataset,
            img_size=input_size,
            mosaic=True,
            preproc=imports.TrainTransform(
                max_labels=max_labels,
                flip_prob=flip_prob,
                hsv_prob=hsv_prob,
            ),
            degrees=degrees,
            translate=translate,
            mosaic_scale=mosaic_scale,
            mixup_scale=mixup_scale,
            shear=shear,
            enable_mixup=enable_mixup,
            mosaic_prob=mosaic_prob,
            mixup_prob=mixup_prob,
        )
    else:
        train_dataset = train_base_dataset

    if use_augmentation_data_pipeline:
        train_batch_sampler = imports.YoloBatchSampler(
            imports.InfiniteSampler(len(train_dataset), seed=random_seed),
            batch_size,
            False,
            mosaic=mosaic_augmentation_enabled,
            input_dimension=input_size,
        )
        train_loader = imports.torch.utils.data.DataLoader(
            train_dataset,
            batch_sampler=train_batch_sampler,
            num_workers=num_workers,
            pin_memory=runtime.device.startswith("cuda"),
            worker_init_fn=(imports.worker_init_reset_seed if num_workers > 0 else None),
        )
    else:
        train_loader = imports.torch.utils.data.DataLoader(
            train_dataset,
            batch_size=batch_size,
            shuffle=True,
            num_workers=num_workers,
            pin_memory=runtime.device.startswith("cuda"),
            drop_last=False,
            worker_init_fn=(imports.worker_init_reset_seed if num_workers > 0 else None),
        )
    if len(train_loader) == 0:
        raise InvalidRequestError("训练输入中没有可消费的 batch")

    validation_split = _resolve_validation_split(
        resolved_splits,
        train_split_name=train_split.name,
    )
    validation_dataset: _YoloXDetectionDataset | None = None
    validation_loader = None
    warm_start_summary: dict[str, object] = {"enabled": False}
    resume_state: _LoadedResumeState | None = None
    if validation_split is not None:
        validation_dataset = _build_yolox_detection_dataset(
            split=validation_split,
            input_size=input_size,
            imports=imports,
            flip_prob=0.0,
            hsv_prob=0.0,
            max_labels=max_labels,
        )
        validation_loader = imports.torch.utils.data.DataLoader(
            validation_dataset,
            batch_size=batch_size,
            shuffle=False,
            num_workers=num_workers,
            pin_memory=runtime.device.startswith("cuda"),
            drop_last=False,
        )
    validation_split_name = validation_split.name if validation_split is not None else None
    train_category_names = train_base_dataset.category_names

    base_model = build_yolox_detection_model(
        torch_module=imports.torch,
        model_scale=request.model_scale,
        num_classes=len(train_category_names),
    )
    if request.resume_checkpoint_path is None and request.warm_start_checkpoint_path is not None:
        warm_start_summary = load_yolox_warm_start_checkpoint(
            torch_module=imports.torch,
            model=base_model,
            checkpoint_path=request.warm_start_checkpoint_path,
            source_summary=dict(request.warm_start_source_summary or {}),
        )
    base_model.to(runtime.device)
    optimizer = _build_optimizer(torch_module=imports.torch, model=base_model, batch_size=batch_size)
    if request.resume_checkpoint_path is not None:
        resume_state = _load_resume_checkpoint(
            torch_module=imports.torch,
            model=base_model,
            optimizer=optimizer,
            checkpoint_path=request.resume_checkpoint_path,
            expected_category_names=train_category_names,
            expected_model_scale=request.model_scale,
            expected_input_size=input_size,
            expected_precision=precision,
            expected_validation_split_name=validation_split_name,
            expected_evaluation_interval=evaluation_interval,
            expected_evaluation_confidence_threshold=(
                evaluation_confidence_threshold if validation_loader is not None else None
            ),
            expected_evaluation_nms_threshold=(
                evaluation_nms_threshold if validation_loader is not None else None
            ),
        )
        warm_start_summary = dict(resume_state.warm_start_summary)
        if resume_state.resume_epoch >= max_epochs:
            raise InvalidRequestError(
                "resume checkpoint 已经达到当前任务的最大 epoch，不能继续训练",
                details={
                    "resume_epoch": resume_state.resume_epoch,
                    "max_epochs": max_epochs,
                },
            )
    training_model = base_model
    training_model.train()
    parameter_count = sum(parameter.numel() for parameter in base_model.parameters())
    scheduler = build_yolox_lr_scheduler(
        scheduler_class=imports.LRScheduler,
        train_loader_length=len(train_loader),
        batch_size=batch_size,
        max_epochs=max_epochs,
        warmup_epochs=warmup_epochs,
        no_aug_epochs=no_aug_epochs,
        min_lr_ratio=min_lr_ratio,
    )
    use_fp16 = precision == "fp16" and runtime.device.startswith("cuda")
    grad_scaler_device = "cuda" if runtime.device.startswith("cuda") else "cpu"
    grad_scaler = imports.torch.amp.GradScaler(grad_scaler_device, enabled=use_fp16)
    model_ema = build_yolox_model_ema(
        ema_class=imports.ModelEMA,
        model=training_model,
        enabled=ema_enabled,
    )

    def _release_current_training_objects() -> None:
        """释放本次训练中的大对象引用。"""

        nonlocal base_model, grad_scaler, model_ema, optimizer, scheduler, training_model
        nonlocal train_base_dataset, train_dataset, train_loader, validation_dataset
        nonlocal validation_loader
        model_ema = None
        training_model = None
        base_model = None
        optimizer = None
        scheduler = None
        grad_scaler = None
        train_loader = None
        validation_loader = None
        train_dataset = None
        train_base_dataset = None
        validation_dataset = None
        release_yolox_training_runtime_resources(
            imports=imports,
            runtime=runtime,
        )

    total_sample_count = sum(split.sample_count for split in resolved_splits)
    train_sample_count = len(train_base_dataset)
    validation_sample_count = len(validation_dataset) if validation_dataset is not None else 0
    epoch_history: list[dict[str, object]] = []
    validation_epoch_history: list[dict[str, object]] = []
    best_metric_name = "val_map50_95" if validation_loader is not None else "train_total_loss"
    best_metric_value: float | None = None if validation_loader is not None else float("inf")
    best_checkpoint_state: dict[str, object] | None = None
    start_epoch = 0
    if resume_state is not None:
        epoch_history = [dict(item) for item in resume_state.epoch_history]
        validation_epoch_history = [dict(item) for item in resume_state.validation_history]
        best_metric_name = resume_state.best_metric_name or best_metric_name
        best_metric_value = resume_state.best_metric_value
        best_checkpoint_state = (
            dict(resume_state.best_checkpoint_state)
            if resume_state.best_checkpoint_state is not None
            else None
        )
        start_epoch = max(0, resume_state.resume_epoch)

    def _evaluate_current_validation_model(evaluation_model: Any) -> dict[str, float]:
        """执行当前 epoch 需要的 YOLOX validation loss 和 COCO mAP。"""

        if validation_loader is None:
            return {}
        validation_metrics = evaluate_yolox_validation_losses(
            torch_module=imports.torch,
            autocast_context_factory=_build_autocast_context,
            model=evaluation_model,
            loader=validation_loader,
            device=runtime.device,
            precision=precision,
        )
        if isinstance(validation_dataset, _CocoDetectionExportDataset):
            detection_metrics = evaluate_yolox_coco_map(
                torch_module=imports.torch,
                postprocess=imports.postprocess,
                autocast_context_factory=_build_autocast_context,
                coco_class=imports.COCO,
                cocoeval_class=imports.COCOeval,
                model=evaluation_model,
                loader=validation_loader,
                device=runtime.device,
                precision=precision,
                input_size=input_size,
                num_classes=len(train_category_names),
                category_ids=validation_dataset.category_ids,
                category_names=train_category_names,
                annotation_file=_get_yolox_detection_evaluation_annotation_file(validation_dataset),
                score_threshold=evaluation_confidence_threshold,
                nms_threshold=evaluation_nms_threshold,
            )
        elif isinstance(validation_dataset, _VocDetectionExportDataset):
            detection_metrics = evaluate_yolox_voc_map(
                torch_module=imports.torch,
                postprocess=imports.postprocess,
                autocast_context_factory=_build_autocast_context,
                model=evaluation_model,
                loader=validation_loader,
                device=runtime.device,
                precision=precision,
                input_size=input_size,
                num_classes=len(train_category_names),
                dataset=validation_dataset,
                category_names=train_category_names,
                score_threshold=evaluation_confidence_threshold,
                nms_threshold=evaluation_nms_threshold,
            )
        else:
            raise TypeError(f"不支持的 YOLOX validation dataset 类型: {type(validation_dataset)!r}")
        validation_metrics.update(
            {
                "map50": detection_metrics.map50,
                "map50_95": detection_metrics.map50_95,
            }
        )
        return validation_metrics

    try:
        loop_result = run_yolox_training_loop(
            YoloXTrainingLoopRequest(
                torch_module=imports.torch,
                base_model=base_model,
                training_model=training_model,
                train_dataset=train_dataset,
                train_loader=train_loader,
                validation_loader=validation_loader,
                optimizer=optimizer,
                scheduler=scheduler,
                grad_scaler=grad_scaler,
                model_ema=model_ema,
                validation_evaluator=(
                    _evaluate_current_validation_model
                    if validation_loader is not None
                    else None
                ),
                batch_callback=request.batch_callback,
                epoch_callback=request.epoch_callback,
                savepoint_callback=request.savepoint_callback,
                device=runtime.device,
                gpu_count=runtime.gpu_count,
                device_ids=runtime.device_ids,
                distributed_mode=runtime.distributed_mode,
                precision=precision,
                input_size=input_size,
                current_input_size=current_input_size,
                batch_size=batch_size,
                max_epochs=max_epochs,
                evaluation_interval=evaluation_interval,
                train_split_name=train_split.name,
                validation_split_name=validation_split_name,
                validation_sample_count=validation_sample_count,
                total_sample_count=total_sample_count,
                train_sample_count=train_sample_count,
                train_category_names=train_category_names,
                model_scale=request.model_scale,
                parameter_count=int(parameter_count),
                warm_start_summary=warm_start_summary,
                start_epoch=start_epoch,
                epoch_history=epoch_history,
                validation_epoch_history=validation_epoch_history,
                best_metric_name=best_metric_name,
                best_metric_value=best_metric_value,
                best_checkpoint_state=best_checkpoint_state,
                no_aug_epochs=no_aug_epochs,
                multiscale_range=multiscale_range,
                random_seed=random_seed,
                evaluation_confidence_threshold=evaluation_confidence_threshold,
                evaluation_nms_threshold=evaluation_nms_threshold,
            )
        )
    except Exception:
        _release_current_training_objects()
        raise

    if loop_result.status == "terminated":
        _release_current_training_objects()
        raise YoloXTrainingTerminatedError()

    if loop_result.status == "paused":
        savepoint = loop_result.savepoint
        if savepoint is None:
            _release_current_training_objects()
            raise ServiceConfigurationError("YOLOX 训练暂停时没有生成 savepoint")
        _release_current_training_objects()
        raise YoloXTrainingPausedError(savepoint)

    if (
        loop_result.checkpoint_bytes is None
        or loop_result.latest_checkpoint_bytes is None
        or loop_result.metrics_payload is None
        or loop_result.validation_metrics_payload is None
        or loop_result.best_metric_value is None
    ):
        _release_current_training_objects()
        raise ServiceConfigurationError("YOLOX 训练没有生成有效结果")

    execution_result = YoloXDetectionTrainingExecutionResult(
        checkpoint_bytes=loop_result.checkpoint_bytes,
        latest_checkpoint_bytes=loop_result.latest_checkpoint_bytes,
        metrics_payload=dict(loop_result.metrics_payload),
        validation_metrics_payload=dict(loop_result.validation_metrics_payload),
        warm_start_summary=warm_start_summary,
        implementation_mode=YOLOX_DETECTION_CORE_IMPLEMENTATION_MODE,
        best_metric_name=loop_result.best_metric_name,
        best_metric_value=loop_result.best_metric_value,
        evaluation_interval=evaluation_interval,
        category_names=train_category_names,
        split_names=tuple(split.name for split in resolved_splits),
        sample_count=total_sample_count,
        train_sample_count=train_sample_count,
        input_size=input_size,
        batch_size=batch_size,
        max_epochs=max_epochs,
        device=runtime.device,
        gpu_count=runtime.gpu_count,
        device_ids=runtime.device_ids,
        distributed_mode=runtime.distributed_mode,
        precision=precision,
        validation_split_name=validation_split.name if validation_split is not None else None,
        validation_sample_count=len(validation_dataset) if validation_dataset is not None else 0,
        parameter_count=int(parameter_count),
    )
    _release_current_training_objects()
    return execution_result


def release_yolox_training_runtime_resources(
    *,
    imports: YoloXCoreDependencies,
    runtime: _ResolvedTrainingRuntime | None,
) -> None:
    """释放一次训练执行后遗留的 Python 对象与 CUDA cache。

    参数：
    - imports：当前训练依赖对象集合。
    - runtime：本次训练解析出的运行时信息；为空时只执行 Python 侧回收。
    """

    gc.collect()
    if runtime is None or not runtime.device.startswith("cuda"):
        return
    cuda_module = getattr(imports.torch, "cuda", None)
    if cuda_module is None or not callable(getattr(cuda_module, "is_available", None)):
        return
    if not cuda_module.is_available():
        return
    empty_cache = getattr(cuda_module, "empty_cache", None)
    if callable(empty_cache):
        empty_cache()
    ipc_collect = getattr(cuda_module, "ipc_collect", None)
    if callable(ipc_collect):
        ipc_collect()


def _resolve_yolox_detection_splits(
    dataset_storage: LocalDatasetStorage,
    manifest_payload: dict[str, object],
) -> tuple[_ResolvedYoloXDetectionSplit, ...]:
    """从 YOLOX detection manifest 中解析本地 split 路径。"""

    return _core_resolve_yolox_detection_splits(dataset_storage, manifest_payload)


def _resolve_train_split(
    resolved_splits: tuple[_ResolvedYoloXDetectionSplit, ...],
) -> _ResolvedYoloXDetectionSplit:
    """优先解析训练链路要使用的 train split。"""

    return _core_resolve_train_split(resolved_splits)


def _resolve_validation_split(
    resolved_splits: tuple[_ResolvedYoloXDetectionSplit, ...],
    *,
    train_split_name: str,
) -> _ResolvedYoloXDetectionSplit | None:
    """优先解析训练链路要使用的验证 split。

    参数：
    - resolved_splits：当前 manifest 中可用的全部 split。
    - train_split_name：已经选定的训练 split 名称。

    返回：
    - _ResolvedYoloXDetectionSplit | None：优先返回 val、valid、validation；
      缺失时回退 test；再缺失时回退第一个非训练 split。
    """

    return _core_resolve_validation_split(
        resolved_splits,
        train_split_name=train_split_name,
    )


def _resolve_input_size(input_size: tuple[int, int] | None) -> tuple[int, int]:
    """解析并校验训练输入尺寸。"""

    return resolve_yolox_input_size(input_size)


def _resolve_training_runtime(
    *,
    imports: YoloXCoreDependencies,
    requested_gpu_count: int | None,
    extra_options: dict[str, object],
) -> _ResolvedTrainingRuntime:
    """解析当前训练应使用的设备资源。"""

    requested_device = _read_str_option(extra_options, "device")
    if requested_device == "cpu":
        if requested_gpu_count is not None:
            raise InvalidRequestError("CPU 训练不能同时指定 gpu_count")
        return _ResolvedTrainingRuntime(
            device="cpu",
            gpu_count=0,
            device_ids=(),
            distributed_mode="single-device",
        )

    if not imports.torch.cuda.is_available():
        if requested_gpu_count is not None:
            raise InvalidRequestError("当前运行环境没有可用 GPU，不能指定 gpu_count")
        return _ResolvedTrainingRuntime(
            device="cpu",
            gpu_count=0,
            device_ids=(),
            distributed_mode="single-device",
        )

    available_gpu_count = int(imports.torch.cuda.device_count())
    gpu_count = requested_gpu_count or _read_int_option(extra_options, "gpu_count", default=1)
    if gpu_count < 1:
        raise InvalidRequestError("gpu_count 必须大于 0")
    if gpu_count > 1:
        raise InvalidRequestError(
            "当前版本只支持单 GPU 训练，gpu_count 必须为 1",
            details={"requested_gpu_count": gpu_count},
        )
    if gpu_count > available_gpu_count:
        raise InvalidRequestError(
            "指定的 gpu_count 超过了本机可用 GPU 数量",
            details={
                "requested_gpu_count": gpu_count,
                "available_gpu_count": available_gpu_count,
            },
        )

    start_device_index = 0
    if requested_device is not None and requested_device.startswith("cuda:"):
        raw_device_index = requested_device.split(":", 1)[1]
        if not raw_device_index.isdigit():
            raise InvalidRequestError(
                "device 必须是 cpu、cuda 或 cuda:<index>",
                details={"device": requested_device},
            )
        start_device_index = int(raw_device_index)
        if start_device_index + 1 > available_gpu_count:
            raise InvalidRequestError(
                "指定的 device 超出了本机可用 GPU 范围",
                details={
                    "device": requested_device,
                    "available_gpu_count": available_gpu_count,
                },
            )

    device_ids = (start_device_index,)
    distributed_mode = "single-device"
    return _ResolvedTrainingRuntime(
        device=f"cuda:{device_ids[0]}",
        gpu_count=gpu_count,
        device_ids=device_ids,
        distributed_mode=distributed_mode,
    )


def _resolve_precision(
    *,
    imports: YoloXCoreDependencies,
    requested_precision: str | None,
    device: str,
    extra_options: dict[str, object],
) -> str:
    """解析当前训练应使用的 precision。"""

    precision = requested_precision or _read_str_option(extra_options, "precision") or "fp32"
    if precision not in {"fp8", "fp16", "fp32"}:
        raise InvalidRequestError(
            "precision 必须是 fp8、fp16 或 fp32",
            details={"precision": precision},
        )
    if precision == "fp8":
        raise InvalidRequestError("当前 YOLOX core 训练暂不支持 fp8，当前可用值为 fp16 或 fp32")
    if precision == "fp16" and not device.startswith("cuda"):
        raise InvalidRequestError("fp16 训练需要 CUDA 环境")
    if precision == "fp16" and not hasattr(imports.torch, "autocast"):
        raise ServiceConfigurationError("当前 torch 版本缺少 autocast，无法执行 fp16 训练")
    return precision


def _read_bool_option(extra_options: dict[str, object], key: str, *, default: bool) -> bool:
    """从 extra_options 中读取可选布尔值。"""

    value = extra_options.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        normalized_value = value.strip().lower()
        if normalized_value in {"1", "true", "yes", "on"}:
            return True
        if normalized_value in {"0", "false", "no", "off"}:
            return False
    return default


def _read_float_pair_option(
    extra_options: dict[str, object],
    key: str,
    *,
    default: tuple[float, float],
) -> tuple[float, float]:
    """从 extra_options 中读取长度为 2 的浮点区间。"""

    value = extra_options.get(key)
    if isinstance(value, list | tuple) and len(value) == 2:
        left, right = value
        if isinstance(left, int | float) and isinstance(right, int | float):
            return float(left), float(right)
    return default


def _read_float_option(extra_options: dict[str, object], key: str, *, default: float) -> float:
    """从 extra_options 中读取可选浮点数。"""

    value = extra_options.get(key)
    if isinstance(value, int | float):
        return float(value)
    return default


def _read_int_option(extra_options: dict[str, object], key: str, *, default: int) -> int:
    """从 extra_options 中读取可选整数。"""

    value = extra_options.get(key)
    if isinstance(value, int):
        return value
    return default


def _read_str_option(extra_options: dict[str, object], key: str) -> str | None:
    """从 extra_options 中读取可选字符串。"""

    value = extra_options.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


