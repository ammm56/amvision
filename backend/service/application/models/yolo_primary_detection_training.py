"""YOLO 主线 detection 共享训练执行模块。"""

from __future__ import annotations

import io
import json
import random
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolo_primary_detection_model import (
    build_yolo_primary_detection_model,
    load_yolo_primary_checkpoint,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


YOLO_PRIMARY_BOOTSTRAP_IMPLEMENTATION_MODE = "yolo-primary-detection-bootstrap"
YOLO_PRIMARY_DEFAULT_INPUT_SIZE = (640, 640)
YOLO_PRIMARY_DEFAULT_BATCH_SIZE = 1
YOLO_PRIMARY_DEFAULT_MAX_EPOCHS = 1
YOLO_PRIMARY_DEFAULT_EVALUATION_INTERVAL = 5


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
class YoloPrimaryDetectionTrainingExecutionRequest:
    """描述一次 YOLO 主线 detection 共享训练执行请求。"""

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_scale: str
    model_type: str = "yolov8"
    implementation_mode: str = YOLO_PRIMARY_BOOTSTRAP_IMPLEMENTATION_MODE
    evaluation_interval: int | None = None
    max_epochs: int | None = None
    batch_size: int | None = None
    gpu_count: int | None = None
    precision: str | None = None
    warm_start_checkpoint_path: Path | None = None
    warm_start_source_summary: dict[str, object] | None = None
    input_size: tuple[int, int] | None = None
    extra_options: dict[str, object] | None = None
    batch_callback: Callable[[YoloPrimaryTrainingBatchProgress], None] | None = None
    epoch_callback: Callable[[YoloPrimaryTrainingEpochProgress], None] | None = None


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


@dataclass(frozen=True)
class _ResolvedCocoSplit:
    """描述一个已经解析到本地绝对路径的 COCO split。"""

    name: str
    image_root: Path
    annotation_file: Path
    sample_count: int


@dataclass(frozen=True)
class _ResolvedTrainingSample:
    """描述一个训练样本需要的最小信息。"""

    image_path: Path
    class_presence: tuple[int, ...]
    mean_box_xyxy: tuple[float, float, float, float]
    has_boxes: bool


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

    train_samples, category_names = _load_training_samples(
        imports=imports,
        split=train_split,
    )
    validation_samples: tuple[_ResolvedTrainingSample, ...] = ()
    if validation_split is not None:
        validation_samples, validation_category_names = _load_training_samples(
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
    if not train_samples:
        raise InvalidRequestError("训练 split 不包含可用样本")

    device, gpu_count, device_ids, distributed_mode, runtime_precision = _resolve_runtime(
        imports=imports,
        requested_gpu_count=request.gpu_count,
        requested_precision=request.precision,
    )
    learning_rate = _read_float_option(extra_options, "learning_rate", default=1e-3)
    weight_decay = _read_float_option(extra_options, "weight_decay", default=1e-4)
    box_loss_weight = _read_float_option(extra_options, "box_loss_weight", default=0.05)
    score_penalty_weight = _read_float_option(extra_options, "score_penalty_weight", default=0.01)

    model = build_yolo_primary_detection_model(
        model_type=request.model_type,
        model_scale=request.model_scale,
        num_classes=len(category_names),
    )
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
    model.to(device)
    if runtime_precision == "fp16":
        model.half()
    optimizer = imports.torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    autocast_context = _build_autocast_context(
        imports=imports,
        device=device,
        runtime_precision=runtime_precision,
    )
    total_iterations = max_epochs * max(1, (len(train_samples) + batch_size - 1) // batch_size)
    global_iteration = 0
    metrics_history: list[dict[str, object]] = []
    validation_history: list[dict[str, object]] = []
    evaluated_epochs: list[int] = []
    best_metric_name = "class_presence_accuracy" if validation_split is not None else "train_loss"
    best_metric_value = float("-inf") if validation_split is not None else float("inf")
    latest_checkpoint_bytes = b""
    best_checkpoint_bytes = b""

    for epoch in range(1, max_epochs + 1):
        shuffled_samples = list(train_samples)
        random.shuffle(shuffled_samples)
        epoch_losses = {"loss": 0.0, "class_loss": 0.0, "box_loss": 0.0, "score_penalty": 0.0}
        max_iterations = max(1, (len(shuffled_samples) + batch_size - 1) // batch_size)
        model.train()

        for iteration, sample_batch in enumerate(_iter_batches(shuffled_samples, batch_size), start=1):
            global_iteration += 1
            images, class_targets, box_targets, box_masks = _build_training_batch(
                imports=imports,
                samples=sample_batch,
                input_size=input_size,
                num_classes=len(category_names),
                device=device,
                runtime_precision=runtime_precision,
            )
            optimizer.zero_grad(set_to_none=True)
            with autocast_context():
                raw_outputs = _unwrap_detection_outputs(model(images))
                loss_components = _compute_bootstrap_loss(
                    imports=imports,
                    model=model,
                    raw_outputs=raw_outputs,
                    class_targets=class_targets,
                    box_targets=box_targets,
                    box_masks=box_masks,
                    input_size=input_size,
                    box_loss_weight=box_loss_weight,
                    score_penalty_weight=score_penalty_weight,
                )
                loss = loss_components["loss"]
            loss.backward()
            optimizer.step()

            for key in epoch_losses:
                epoch_losses[key] += float(loss_components[key].detach().item())

            if request.batch_callback is not None:
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
                        train_metrics={
                            "loss": float(loss_components["loss"].detach().item()),
                            "class_loss": float(loss_components["class_loss"].detach().item()),
                            "box_loss": float(loss_components["box_loss"].detach().item()),
                        },
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
                input_size=input_size,
                batch_size=batch_size,
                device=device,
                runtime_precision=runtime_precision,
                box_loss_weight=box_loss_weight,
                score_penalty_weight=score_penalty_weight,
            )
            validation_history.append(validation_snapshot)
            validation_metrics = {
                "loss": float(validation_snapshot["loss"]),
                "class_presence_accuracy": float(validation_snapshot["class_presence_accuracy"]),
                "present_class_recall": float(validation_snapshot["present_class_recall"]),
            }
            evaluated_epochs.append(epoch)
            current_metric_value = validation_metrics[best_metric_name]

        latest_checkpoint_bytes = _build_checkpoint_bytes(
            imports=imports,
            model=model,
            model_type=request.model_type,
            model_scale=request.model_scale,
            category_names=category_names,
            input_size=input_size,
            epoch=epoch,
            precision=runtime_precision,
            metrics_history=metrics_history,
            validation_history=validation_history,
            warm_start_summary=warm_start_summary,
            implementation_mode=request.implementation_mode,
        )
        if validation_ran and current_metric_value is not None:
            if current_metric_value >= best_metric_value:
                best_metric_value = current_metric_value
                best_checkpoint_bytes = latest_checkpoint_bytes
        elif train_metrics["loss"] <= best_metric_value:
            best_metric_value = train_metrics["loss"]
            best_checkpoint_bytes = latest_checkpoint_bytes

        if request.epoch_callback is not None:
            request.epoch_callback(
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
        "evaluated_epochs": evaluated_epochs,
        "history": validation_history,
        "final_metrics": validation_history[-1] if validation_history else {},
    }
    metrics_payload = {
        "implementation_mode": request.implementation_mode,
        "history": metrics_history,
        "final_metrics": metrics_history[-1] if metrics_history else {},
        "learning_rate": learning_rate,
        "weight_decay": weight_decay,
        "loss_weights": {
            "box_loss_weight": box_loss_weight,
            "score_penalty_weight": score_penalty_weight,
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
    """导入 YOLOv8 bootstrap 训练所需依赖。"""

    try:
        import cv2
        import numpy as np
        import torch
    except Exception as error:  # pragma: no cover - 缺依赖时直接报配置错误
        raise ServiceConfigurationError(
            "当前环境缺少 YOLOv8 bootstrap 训练所需依赖",
            details={"error": str(error)},
        ) from error
    return _TrainingImports(cv2=cv2, np=np, torch=torch)


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
) -> tuple[tuple[_ResolvedTrainingSample, ...], tuple[str, ...]]:
    """把 COCO split 转成训练阶段可直接消费的样本列表。"""

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
    category_id_to_index: dict[int, int] = {}
    for category_index, category_item in enumerate(categories_payload):
        if not isinstance(category_item, dict):
            continue
        category_id = category_item.get("id")
        category_name = str(category_item.get("name") or "").strip()
        if not isinstance(category_id, int) or not category_name:
            continue
        category_id_to_index[category_id] = len(category_names)
        category_names.append(category_name)
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
            "boxes": [],
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
        image_meta["boxes"].append((float(x), float(y), float(w), float(h), category_index))

    resolved_samples: list[_ResolvedTrainingSample] = []
    for image_id, image_meta in image_meta_by_id.items():
        del image_id
        file_name = str(image_meta["file_name"])
        width = int(image_meta["width"])
        height = int(image_meta["height"])
        boxes = list(image_meta["boxes"])
        image_path = split.image_root / file_name
        if not image_path.is_file():
            continue
        class_presence = [0] * len(category_names)
        box_values: list[tuple[float, float, float, float]] = []
        for x, y, w, h, category_index in boxes:
            class_presence[category_index] = 1
            x1 = max(0.0, min(x / width, 1.0))
            y1 = max(0.0, min(y / height, 1.0))
            x2 = max(0.0, min((x + w) / width, 1.0))
            y2 = max(0.0, min((y + h) / height, 1.0))
            box_values.append((x1, y1, x2, y2))
        mean_box = (
            tuple(
                float(sum(item[index] for item in box_values) / len(box_values))
                for index in range(4)
            )
            if box_values
            else (0.0, 0.0, 0.0, 0.0)
        )
        resolved_samples.append(
            _ResolvedTrainingSample(
                image_path=image_path,
                class_presence=tuple(class_presence),
                mean_box_xyxy=mean_box,
                has_boxes=bool(box_values),
            )
        )
    return tuple(resolved_samples), tuple(category_names)


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
    num_classes: int,
    device: str,
    runtime_precision: str,
) -> tuple[Any, Any, Any, Any]:
    """把一组样本拼成训练 batch。"""

    np_module = imports.np
    torch = imports.torch
    image_tensors: list[Any] = []
    class_targets: list[Any] = []
    box_targets: list[Any] = []
    box_masks: list[Any] = []
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
        class_targets.append(torch.tensor(sample.class_presence, dtype=torch.float32))
        box_targets.append(torch.tensor(sample.mean_box_xyxy, dtype=torch.float32))
        box_masks.append(torch.tensor(1.0 if sample.has_boxes else 0.0, dtype=torch.float32))
    images = torch.stack(image_tensors, dim=0).to(device)
    if runtime_precision == "fp16":
        images = images.half()
    class_target_tensor = torch.stack(class_targets, dim=0).to(device)
    box_target_tensor = torch.stack(box_targets, dim=0).to(device)
    box_mask_tensor = torch.stack(box_masks, dim=0).to(device)
    if class_target_tensor.shape[1] != num_classes:
        raise ServiceConfigurationError(
            "训练 batch 的类别维度与模型类别数不一致",
            details={
                "class_count": int(class_target_tensor.shape[1]),
                "num_classes": num_classes,
            },
        )
    return images, class_target_tensor, box_target_tensor, box_mask_tensor


def _unwrap_detection_outputs(outputs: Any) -> dict[str, Any]:
    """把 detection 训练输出规整成 one2many 结果。"""

    if isinstance(outputs, dict) and "boxes" in outputs and "scores" in outputs:
        return outputs
    if isinstance(outputs, dict) and "one2many" in outputs:
        one2many = outputs.get("one2many")
        if isinstance(one2many, dict) and "boxes" in one2many and "scores" in one2many:
            return one2many
    raise ServiceConfigurationError("当前 YOLO detection 训练输出结构不合法")


def _compute_bootstrap_loss(
    *,
    imports: _TrainingImports,
    model: Any,
    raw_outputs: dict[str, Any],
    class_targets: Any,
    box_targets: Any,
    box_masks: Any,
    input_size: tuple[int, int],
    box_loss_weight: float,
    score_penalty_weight: float,
) -> dict[str, Any]:
    """计算 bootstrap 训练阶段使用的代理损失。"""

    torch = imports.torch
    detect_head = model.model[-1]
    class_logits = raw_outputs["scores"].amax(dim=2)
    class_loss = torch.nn.functional.binary_cross_entropy_with_logits(class_logits, class_targets)

    decoded_boxes = detect_head._decode_boxes(raw_outputs)
    normalization = torch.tensor(
        [input_size[1], input_size[0], input_size[1], input_size[0]],
        device=decoded_boxes.device,
        dtype=decoded_boxes.dtype,
    ).view(1, 4, 1)
    normalized_boxes = decoded_boxes / normalization
    anchor_weights = raw_outputs["scores"].sigmoid().amax(dim=1)
    anchor_weights = anchor_weights / anchor_weights.sum(dim=1, keepdim=True).clamp_min(1e-6)
    weighted_boxes = (normalized_boxes * anchor_weights.unsqueeze(1)).sum(dim=2)
    box_distance = torch.abs(weighted_boxes - box_targets).mean(dim=1)
    box_loss = ((box_distance * box_masks).sum() / box_masks.sum().clamp_min(1.0)) * box_loss_weight

    score_penalty = raw_outputs["scores"].sigmoid().mean() * score_penalty_weight
    total_loss = class_loss + box_loss + score_penalty
    return {
        "loss": total_loss,
        "class_loss": class_loss,
        "box_loss": box_loss,
        "score_penalty": score_penalty,
    }


def _evaluate_detection_model(
    *,
    imports: _TrainingImports,
    model: Any,
    samples: tuple[_ResolvedTrainingSample, ...],
    input_size: tuple[int, int],
    batch_size: int,
    device: str,
    runtime_precision: str,
    box_loss_weight: float,
    score_penalty_weight: float,
) -> dict[str, object]:
    """在验证 split 上计算 bootstrap 指标。"""

    torch = imports.torch
    autocast_context = _build_autocast_context(
        imports=imports,
        device=device,
        runtime_precision=runtime_precision,
    )
    previous_training_mode = bool(model.training)
    model.train()
    total_loss = 0.0
    total_class_matches = 0.0
    total_class_count = 0.0
    total_true_positive = 0.0
    total_positive = 0.0
    batch_count = 0
    with torch.no_grad():
        for batch_samples in _iter_batches(list(samples), batch_size):
            images, class_targets, box_targets, box_masks = _build_training_batch(
                imports=imports,
                samples=batch_samples,
                input_size=input_size,
                num_classes=len(batch_samples[0].class_presence),
                device=device,
                runtime_precision=runtime_precision,
            )
            with autocast_context():
                raw_outputs = _unwrap_detection_outputs(model(images))
                loss_components = _compute_bootstrap_loss(
                    imports=imports,
                    model=model,
                    raw_outputs=raw_outputs,
                    class_targets=class_targets,
                    box_targets=box_targets,
                    box_masks=box_masks,
                    input_size=input_size,
                    box_loss_weight=box_loss_weight,
                    score_penalty_weight=score_penalty_weight,
                )
            batch_count += 1
            total_loss += float(loss_components["loss"].detach().item())
            predicted_presence = raw_outputs["scores"].amax(dim=2).sigmoid() >= 0.5
            class_matches = predicted_presence.eq(class_targets >= 0.5)
            total_class_matches += float(class_matches.float().sum().item())
            total_class_count += float(class_matches.numel())
            true_positive = (predicted_presence & (class_targets >= 0.5)).float().sum()
            total_true_positive += float(true_positive.item())
            total_positive += float((class_targets >= 0.5).float().sum().item())
    model.train(previous_training_mode)
    class_presence_accuracy = total_class_matches / max(total_class_count, 1.0)
    present_class_recall = total_true_positive / max(total_positive, 1.0)
    return {
        "loss": round(total_loss / max(batch_count, 1), 6),
        "class_presence_accuracy": round(class_presence_accuracy, 6),
        "present_class_recall": round(present_class_recall, 6),
        "sample_count": len(samples),
    }


def _build_checkpoint_bytes(
    *,
    imports: _TrainingImports,
    model: Any,
    model_type: str,
    model_scale: str,
    category_names: tuple[str, ...],
    input_size: tuple[int, int],
    epoch: int,
    precision: str,
    metrics_history: list[dict[str, object]],
    validation_history: list[dict[str, object]],
    warm_start_summary: dict[str, object],
    implementation_mode: str,
) -> bytes:
    """把当前训练状态导出为项目内 checkpoint。"""

    buffer = io.BytesIO()
    imports.torch.save(
        {
            "model_state_dict": model.state_dict(),
            "model_type": model_type,
            "model_scale": model_scale,
            "category_names": list(category_names),
            "input_size": list(input_size),
            "epoch": epoch,
            "precision": precision,
            "metrics_history": metrics_history,
            "validation_history": validation_history,
            "warm_start": warm_start_summary,
            "implementation_mode": implementation_mode,
        },
        buffer,
    )
    return buffer.getvalue()


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
