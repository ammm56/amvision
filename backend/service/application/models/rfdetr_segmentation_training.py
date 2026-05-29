"""RF-DETR segmentation 训练执行模块。"""

from __future__ import annotations

import io
from collections import defaultdict
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.rfdetr_model import (
    _box_cxcywh_to_xyxy,
    sigmoid_focal_loss,
)
from backend.service.application.models.rfdetr_training import (
    _giou_loss_boxes,
    _hungarian_match,
)
from backend.service.application.models.rfdetr_segmentation_model import (
    build_rfdetr_segmentation_model,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


RFDETR_SEGMENTATION_IMPLEMENTATION_MODE = "rfdetr-segmentation"
_RF_SEG_DEFAULT_INPUT = (384, 384)
_RF_SEG_DEFAULT_BATCH_SIZE = 1
_RF_SEG_DEFAULT_EPOCHS = 1
_RF_SEG_DEFAULT_LR = 1e-4
_RF_SEG_DEFAULT_WD = 1e-4
_RF_SEG_DEFAULT_MIN_LR = 0.01
_RF_SEG_DEFAULT_EVAL_INTERVAL = 1
_RF_SEG_DEFAULT_CLASS_COST = 2.0
_RF_SEG_DEFAULT_BBOX_COST = 5.0
_RF_SEG_DEFAULT_GIOU_COST = 2.0
_RF_SEG_DEFAULT_CLASS_WEIGHT = 1.0
_RF_SEG_DEFAULT_BBOX_WEIGHT = 5.0
_RF_SEG_DEFAULT_GIOU_WEIGHT = 2.0
_RF_SEG_DEFAULT_MASK_CE_WEIGHT = 5.0
_RF_SEG_DEFAULT_MASK_DICE_WEIGHT = 5.0


@dataclass(frozen=True)
class RfdetrSegmentationTrainingEpochProgress:
    """描述 RF-DETR segmentation 每个 epoch 的进度。"""

    epoch: int
    max_epochs: int
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class RfdetrSegmentationTrainingSavePoint:
    """描述 RF-DETR segmentation 保存点。"""

    latest_checkpoint_bytes: bytes
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    learning_rate: float


@dataclass(frozen=True)
class RfdetrSegmentationTrainingControlCommand:
    """描述训练控制命令。"""

    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


class RfdetrSegmentationTrainingPausedError(Exception):
    """训练被显式暂停。"""


class RfdetrSegmentationTrainingTerminatedError(Exception):
    """训练被显式终止。"""


@dataclass(frozen=True)
class RfdetrSegmentationTrainingExecutionRequest:
    """描述一次 RF-DETR segmentation 训练执行请求。"""

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_scale: str = "nano"
    batch_size: int = _RF_SEG_DEFAULT_BATCH_SIZE
    max_epochs: int = _RF_SEG_DEFAULT_EPOCHS
    input_size: tuple[int, int] | None = None
    precision: str = "fp32"
    resume_checkpoint_path: Path | None = None
    extra_options: dict[str, object] | None = None
    epoch_callback: Callable[
        [RfdetrSegmentationTrainingEpochProgress],
        RfdetrSegmentationTrainingControlCommand | None,
    ] | None = None
    savepoint_callback: Callable[
        [RfdetrSegmentationTrainingSavePoint],
        None,
    ] | None = None


@dataclass(frozen=True)
class RfdetrSegmentationTrainingExecutionResult:
    """描述一次 RF-DETR segmentation 训练执行结果。"""

    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    labels: tuple[str, ...]


@dataclass(frozen=True)
class _RfdetrSegmentationAnnotation:
    """描述一张训练图片对应的全部实例。"""

    image_path: str
    boxes_xywh: list[list[float]]
    class_ids: list[int]
    segmentations: list[list[list[float]] | None]


@dataclass(frozen=True)
class _RfdetrSegmentationResumeState:
    """描述恢复训练所需的 checkpoint 状态。"""

    model_state_dict: dict[str, object]
    optimizer_state_dict: dict[str, object]
    scheduler_state_dict: dict[str, object] | None
    metrics_history: list[dict[str, float]]
    validation_history: list[dict[str, float]]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    saved_batch_size: int
    saved_max_epochs: int
    saved_lr: float
    saved_weight_decay: float
    saved_class_cost: float
    saved_bbox_cost: float
    saved_giou_cost: float
    saved_class_weight: float
    saved_bbox_weight: float
    saved_giou_weight: float
    saved_mask_ce_weight: float
    saved_mask_dice_weight: float
    saved_eval_interval: int


def run_rfdetr_segmentation_training(
    request: RfdetrSegmentationTrainingExecutionRequest,
) -> RfdetrSegmentationTrainingExecutionResult:
    """执行一次 RF-DETR segmentation 训练。"""

    imports = _require_segmentation_training_imports()
    input_size = request.input_size or _RF_SEG_DEFAULT_INPUT
    device_name = _resolve_training_device(
        torch_module=imports.torch,
        extra_options=request.extra_options,
    )
    precision = request.precision
    labels, train_annotations, val_annotations = _load_segmentation_manifest(
        dataset_storage=request.dataset_storage,
        manifest=request.manifest_payload,
    )
    num_classes = len(labels)
    extra_options = dict(request.extra_options or {})
    learning_rate = float(extra_options.get("learning_rate", _RF_SEG_DEFAULT_LR))
    weight_decay = float(extra_options.get("weight_decay", _RF_SEG_DEFAULT_WD))
    min_lr_ratio = float(extra_options.get("min_lr_ratio", _RF_SEG_DEFAULT_MIN_LR))
    batch_size = max(1, int(extra_options.get("batch_size", request.batch_size)))
    max_epochs = max(1, int(extra_options.get("max_epochs", request.max_epochs)))
    evaluation_interval = max(
        1,
        int(extra_options.get("evaluation_interval", _RF_SEG_DEFAULT_EVAL_INTERVAL)),
    )
    class_cost = float(extra_options.get("class_cost", _RF_SEG_DEFAULT_CLASS_COST))
    bbox_cost = float(extra_options.get("bbox_cost", _RF_SEG_DEFAULT_BBOX_COST))
    giou_cost = float(extra_options.get("giou_cost", _RF_SEG_DEFAULT_GIOU_COST))
    class_weight = float(
        extra_options.get("class_loss_weight", _RF_SEG_DEFAULT_CLASS_WEIGHT)
    )
    bbox_weight = float(
        extra_options.get("bbox_loss_weight", _RF_SEG_DEFAULT_BBOX_WEIGHT)
    )
    giou_weight = float(
        extra_options.get("giou_loss_weight", _RF_SEG_DEFAULT_GIOU_WEIGHT)
    )
    mask_ce_weight = float(
        extra_options.get("mask_ce_loss_weight", _RF_SEG_DEFAULT_MASK_CE_WEIGHT)
    )
    mask_dice_weight = float(
        extra_options.get(
            "mask_dice_loss_weight",
            _RF_SEG_DEFAULT_MASK_DICE_WEIGHT,
        )
    )

    model = build_rfdetr_segmentation_model(
        model_scale=request.model_scale,
        num_classes=num_classes,
    )
    resume_state = _load_resume_state(request, imports)
    if resume_state is not None:
        _validate_resume_state(
            resume_state=resume_state,
            batch_size=batch_size,
            max_epochs=max_epochs,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            class_cost=class_cost,
            bbox_cost=bbox_cost,
            giou_cost=giou_cost,
            class_weight=class_weight,
            bbox_weight=bbox_weight,
            giou_weight=giou_weight,
            mask_ce_weight=mask_ce_weight,
            mask_dice_weight=mask_dice_weight,
            evaluation_interval=evaluation_interval,
        )

    model.to(device_name)
    trainable_parameters = [parameter for parameter in model.parameters() if parameter.requires_grad]
    optimizer = imports.torch.optim.AdamW(
        trainable_parameters,
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    total_iterations = max(1, max_epochs * max(1, (len(train_annotations) + batch_size - 1) // batch_size))
    scheduler = imports.torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=total_iterations,
        eta_min=learning_rate * min_lr_ratio,
    )

    epoch_history: list[dict[str, float]] = []
    validation_history: list[dict[str, float]] = []
    best_metric_value = 0.0
    best_metric_name = "val_mask_iou"
    start_epoch = 0
    if resume_state is not None:
        model.load_state_dict(
            _filter_state_dict(
                model_state_dict=model.state_dict(),
                loaded_state_dict=resume_state.model_state_dict,
            ),
            strict=False,
        )
        optimizer.load_state_dict(resume_state.optimizer_state_dict)
        if resume_state.scheduler_state_dict is not None:
            scheduler.load_state_dict(resume_state.scheduler_state_dict)
        epoch_history = list(resume_state.metrics_history)
        validation_history = list(resume_state.validation_history)
        best_metric_value = resume_state.best_metric_value
        best_metric_name = resume_state.best_metric_name
        start_epoch = resume_state.epoch

    latest_checkpoint_bytes = b""
    for epoch in range(start_epoch, max_epochs):
        model.train()
        epoch_metrics_accumulator = defaultdict(float)
        epoch_iterations = 0
        for batch_start in range(0, len(train_annotations), batch_size):
            batch_annotations = train_annotations[batch_start : batch_start + batch_size]
            batch = _build_training_batch(
                annotations=batch_annotations,
                input_size=input_size,
                device_name=device_name,
                precision=precision,
                imports=imports,
            )
            if batch is None:
                continue
            images, targets = batch
            with _autocast(imports.torch, precision, device_name):
                outputs = model(images)
                loss_dict = _compute_segmentation_set_loss(
                    outputs=outputs,
                    targets=targets,
                    num_classes=num_classes,
                    class_cost=class_cost,
                    bbox_cost=bbox_cost,
                    giou_cost=giou_cost,
                    class_weight=class_weight,
                    bbox_weight=bbox_weight,
                    giou_weight=giou_weight,
                    mask_ce_weight=mask_ce_weight,
                    mask_dice_weight=mask_dice_weight,
                )
                total_loss = (
                    loss_dict["loss_ce"]
                    + loss_dict["loss_bbox"]
                    + loss_dict["loss_giou"]
                    + loss_dict["loss_mask_ce"]
                    + loss_dict["loss_mask_dice"]
                )
            optimizer.zero_grad()
            total_loss.backward()
            optimizer.step()
            scheduler.step()
            epoch_iterations += 1
            for key, value in loss_dict.items():
                epoch_metrics_accumulator[key] += float(value.detach().item())
            epoch_metrics_accumulator["loss_total"] += float(total_loss.detach().item())

        if epoch_iterations > 0:
            epoch_metrics = {
                key: round(value / epoch_iterations, 6)
                for key, value in epoch_metrics_accumulator.items()
            }
        else:
            epoch_metrics = {
                "loss_total": 0.0,
                "loss_ce": 0.0,
                "loss_bbox": 0.0,
                "loss_giou": 0.0,
                "loss_mask_ce": 0.0,
                "loss_mask_dice": 0.0,
            }
        epoch_metrics["epoch"] = float(epoch)
        epoch_history.append(epoch_metrics)

        if (epoch + 1) % evaluation_interval == 0 or epoch + 1 == max_epochs:
            validation_metrics = _evaluate_segmentation_model(
                model=model,
                annotations=val_annotations,
                input_size=input_size,
                device_name=device_name,
                precision=precision,
                imports=imports,
            )
        else:
            validation_metrics = (
                dict(validation_history[-1])
                if validation_history
                else {"val_mask_iou": 0.0, "val_box_iou": 0.0}
            )
        validation_metrics["epoch"] = float(epoch)
        validation_history.append(validation_metrics)

        metric_value = float(validation_metrics.get(best_metric_name, 0.0))
        if metric_value >= best_metric_value:
            best_metric_value = metric_value

        epoch_progress = RfdetrSegmentationTrainingEpochProgress(
            epoch=epoch,
            max_epochs=max_epochs,
            learning_rate=float(scheduler.get_last_lr()[0]),
            train_metrics=epoch_metrics,
        )
        control_command = (
            request.epoch_callback(epoch_progress)
            if request.epoch_callback is not None
            else None
        )
        latest_checkpoint_bytes = _build_training_checkpoint(
            epoch=epoch,
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            epoch_history=epoch_history,
            validation_history=validation_history,
            best_metric_value=best_metric_value,
            best_metric_name=best_metric_name,
            batch_size=batch_size,
            max_epochs=max_epochs,
            learning_rate=learning_rate,
            weight_decay=weight_decay,
            class_cost=class_cost,
            bbox_cost=bbox_cost,
            giou_cost=giou_cost,
            class_weight=class_weight,
            bbox_weight=bbox_weight,
            giou_weight=giou_weight,
            mask_ce_weight=mask_ce_weight,
            mask_dice_weight=mask_dice_weight,
            evaluation_interval=evaluation_interval,
            imports=imports,
        )
        if control_command is not None and request.savepoint_callback is not None:
            request.savepoint_callback(
                RfdetrSegmentationTrainingSavePoint(
                    latest_checkpoint_bytes=latest_checkpoint_bytes,
                    train_metrics=epoch_metrics,
                    validation_metrics=validation_metrics,
                    best_metric_value=best_metric_value,
                    best_metric_name=best_metric_name,
                    epoch=epoch + 1,
                    learning_rate=float(scheduler.get_last_lr()[0]),
                )
            )
        if control_command is not None and control_command.terminate_training:
            raise RfdetrSegmentationTrainingTerminatedError()
        if control_command is not None and control_command.pause_training:
            raise RfdetrSegmentationTrainingPausedError()

    final_validation_metrics = validation_history[-1] if validation_history else {}
    return RfdetrSegmentationTrainingExecutionResult(
        best_metric_value=best_metric_value,
        best_metric_name=best_metric_name,
        latest_checkpoint_bytes=latest_checkpoint_bytes,
        metrics_payload={
            "final_metrics": epoch_history[-1] if epoch_history else {},
            "epoch_history": epoch_history,
            "scheduler": "CosineAnnealingLR",
        },
        validation_metrics_payload={
            "final_metrics": final_validation_metrics,
            "epoch_history": validation_history,
        },
        labels=labels,
    )


def _require_segmentation_training_imports() -> Any:
    try:
        import cv2
        import numpy as np
        import torch
    except ImportError as exc:
        raise ServiceConfigurationError(
            "RF-DETR segmentation 训练缺少必要依赖",
            details={"missing": str(exc)},
        ) from exc
    return type("_RfdetrSegmentationImports", (), {"cv2": cv2, "np": np, "torch": torch})()


def _resolve_training_device(
    *,
    torch_module: Any,
    extra_options: dict[str, object] | None,
) -> str:
    requested = str((extra_options or {}).get("device", "cpu")).strip().lower()
    if (requested == "cuda" or requested.startswith("cuda:")) and torch_module.cuda.is_available():
        return requested if ":" in requested else "cuda:0"
    return "cpu"


def _autocast(torch_module: Any, precision: str, device_name: str):
    if precision == "fp16" and device_name.startswith("cuda") and hasattr(torch_module, "amp"):
        return torch_module.amp.autocast(device_type="cuda")
    return nullcontext()


def _load_segmentation_manifest(
    *,
    dataset_storage: LocalDatasetStorage,
    manifest: dict[str, object],
) -> tuple[tuple[str, ...], list[_RfdetrSegmentationAnnotation], list[_RfdetrSegmentationAnnotation]]:
    splits = manifest.get("splits")
    if not isinstance(splits, list):
        raise InvalidRequestError("RF-DETR segmentation manifest 缺少合法 splits")
    all_categories: dict[int, str] = {}
    train_annotations: list[_RfdetrSegmentationAnnotation] = []
    val_annotations: list[_RfdetrSegmentationAnnotation] = []
    for split in splits:
        if not isinstance(split, dict):
            continue
        split_name = str(split.get("name", ""))
        image_root = str(split.get("image_root", ""))
        annotation_file = str(split.get("annotation_file", ""))
        annotation_path = dataset_storage.resolve(annotation_file)
        if not annotation_path.is_file():
            raise InvalidRequestError(f"标注文件不存在: {annotation_file}")
        payload = dataset_storage.read_json(annotation_file)
        if not isinstance(payload, dict):
            raise InvalidRequestError(f"标注格式无效: {annotation_file}")
        images_by_id: dict[int, dict[str, object]] = {}
        grouped_annotations: dict[int, list[dict[str, object]]] = defaultdict(list)
        for category in payload.get("categories") or []:
            if isinstance(category, dict):
                all_categories[int(category.get("id", -1))] = str(category.get("name", ""))
        for image in payload.get("images") or []:
            if isinstance(image, dict):
                images_by_id[int(image.get("id", -1))] = dict(image)
        for annotation in payload.get("annotations") or []:
            if not isinstance(annotation, dict):
                continue
            image_id = int(annotation.get("image_id", -1))
            if image_id in images_by_id:
                grouped_annotations[image_id].append(dict(annotation))

        split_annotations: list[_RfdetrSegmentationAnnotation] = []
        for image_id, image_info in images_by_id.items():
            image_annotations = grouped_annotations.get(image_id)
            if not image_annotations:
                continue
            file_name = str(image_info.get("file_name", ""))
            if not file_name:
                continue
            boxes_xywh: list[list[float]] = []
            class_ids: list[int] = []
            segmentations: list[list[list[float]] | None] = []
            for annotation in image_annotations:
                bbox = annotation.get("bbox")
                if not isinstance(bbox, list) or len(bbox) != 4:
                    continue
                boxes_xywh.append([float(item) for item in bbox])
                class_ids.append(int(annotation.get("category_id", 0)))
                segmentations.append(_extract_segmentation_polygons(annotation))
            if not boxes_xywh:
                continue
            split_annotations.append(
                _RfdetrSegmentationAnnotation(
                    image_path=str(dataset_storage.resolve(f"{image_root}/{file_name}")),
                    boxes_xywh=boxes_xywh,
                    class_ids=class_ids,
                    segmentations=segmentations,
                )
            )
        if split_name == "train":
            train_annotations = split_annotations
        elif split_name == "val":
            val_annotations = split_annotations

    sorted_categories = sorted(all_categories.items(), key=lambda item: item[0])
    category_id_to_index = {category_id: index for index, (category_id, _) in enumerate(sorted_categories)}
    labels = tuple(name for _, name in sorted_categories)
    return (
        labels,
        [
            _RfdetrSegmentationAnnotation(
                image_path=item.image_path,
                boxes_xywh=item.boxes_xywh,
                class_ids=[category_id_to_index.get(class_id, 0) for class_id in item.class_ids],
                segmentations=item.segmentations,
            )
            for item in train_annotations
        ],
        [
            _RfdetrSegmentationAnnotation(
                image_path=item.image_path,
                boxes_xywh=item.boxes_xywh,
                class_ids=[category_id_to_index.get(class_id, 0) for class_id in item.class_ids],
                segmentations=item.segmentations,
            )
            for item in val_annotations
        ],
    )


def _extract_segmentation_polygons(annotation: dict[str, object]) -> list[list[float]] | None:
    segmentation = annotation.get("segmentation")
    if not isinstance(segmentation, list) or not segmentation:
        return None
    if isinstance(segmentation[0], list):
        return [
            [float(item) for item in polygon]
            for polygon in segmentation
            if isinstance(polygon, list) and len(polygon) >= 6
        ] or None
    return None


def _build_training_batch(
    *,
    annotations: list[_RfdetrSegmentationAnnotation],
    input_size: tuple[int, int],
    device_name: str,
    precision: str,
    imports: Any,
) -> tuple[torch.Tensor, list[dict[str, object]]] | None:
    if not annotations:
        return None
    input_height, input_width = input_size
    images: list[torch.Tensor] = []
    targets: list[dict[str, object]] = []
    for annotation in annotations:
        image = imports.cv2.imread(annotation.image_path)
        if image is None:
            continue
        original_height, original_width = image.shape[:2]
        resized_image = imports.cv2.resize(
            image,
            (input_width, input_height),
            interpolation=imports.cv2.INTER_LINEAR,
        )
        image_tensor = resized_image[:, :, ::-1].transpose(2, 0, 1).astype(imports.np.float32) / 255.0
        tensor = imports.torch.from_numpy(image_tensor).to(device_name).float()
        if precision == "fp16":
            tensor = tensor.half()
        images.append(tensor)

        target_boxes: list[list[float]] = []
        target_class_ids: list[int] = []
        target_masks: list[imports.np.ndarray] = []
        for bbox, class_id, segmentation in zip(
            annotation.boxes_xywh,
            annotation.class_ids,
            annotation.segmentations,
            strict=True,
        ):
            x, y, width, height = bbox
            cx = (float(x) + float(width) / 2.0) / max(1.0, float(original_width))
            cy = (float(y) + float(height) / 2.0) / max(1.0, float(original_height))
            normalized_width = float(width) / max(1.0, float(original_width))
            normalized_height = float(height) / max(1.0, float(original_height))
            target_boxes.append([cx, cy, normalized_width, normalized_height])
            target_class_ids.append(int(class_id))
            target_masks.append(
                _rasterize_segmentation_mask(
                    cv2_module=imports.cv2,
                    np_module=imports.np,
                    segmentation=segmentation,
                    image_width=original_width,
                    image_height=original_height,
                    output_size=input_size,
                )
            )
        target_dict: dict[str, object] = {
            "boxes": imports.torch.tensor(
                target_boxes,
                dtype=imports.torch.float32,
                device=device_name,
            ),
            "class_ids": imports.torch.tensor(
                target_class_ids,
                dtype=imports.torch.long,
                device=device_name,
            ),
            "masks": imports.torch.from_numpy(
                imports.np.stack(target_masks, axis=0)
                if target_masks
                else imports.np.zeros((0, input_height, input_width), dtype=imports.np.float32)
            ).to(device_name).float(),
        }
        targets.append(target_dict)

    if not images:
        return None
    return imports.torch.stack(images, dim=0), targets


def _rasterize_segmentation_mask(
    *,
    cv2_module: Any,
    np_module: Any,
    segmentation: list[list[float]] | None,
    image_width: int,
    image_height: int,
    output_size: tuple[int, int],
) -> Any:
    mask = np_module.zeros((image_height, image_width), dtype=np_module.uint8)
    if segmentation:
        for polygon in segmentation:
            if len(polygon) < 6:
                continue
            points = np_module.asarray(polygon, dtype=np_module.float32).reshape(-1, 2)
            points = np_module.round(points).astype(np_module.int32)
            cv2_module.fillPoly(mask, [points], 1)
    resized_mask = cv2_module.resize(
        mask,
        (int(output_size[1]), int(output_size[0])),
        interpolation=cv2_module.INTER_NEAREST,
    )
    return resized_mask.astype(np_module.float32)


def _compute_segmentation_set_loss(
    *,
    outputs: dict[str, torch.Tensor],
    targets: list[dict[str, object]],
    num_classes: int,
    class_cost: float,
    bbox_cost: float,
    giou_cost: float,
    class_weight: float,
    bbox_weight: float,
    giou_weight: float,
    mask_ce_weight: float,
    mask_dice_weight: float,
) -> dict[str, torch.Tensor]:
    pred_logits = outputs["pred_logits"]
    pred_boxes = outputs["pred_boxes"]
    pred_masks = outputs["pred_masks"]
    matched_indices = _hungarian_match(
        pred_logits.detach(),
        pred_boxes.detach(),
        [
            {
                "boxes": [box.tolist() for box in target["boxes"]],
                "class_ids": [int(item) for item in target["class_ids"].tolist()],
            }
            for target in targets
        ],
        class_cost,
        bbox_cost,
        giou_cost,
        num_classes,
    )
    loss_ce = torch.tensor(0.0, device=pred_logits.device)
    loss_bbox = torch.tensor(0.0, device=pred_logits.device)
    loss_giou = torch.tensor(0.0, device=pred_logits.device)
    loss_mask_ce = torch.tensor(0.0, device=pred_logits.device)
    loss_mask_dice = torch.tensor(0.0, device=pred_logits.device)
    matched_count = 0

    for batch_index, (prediction_indices, target_indices) in enumerate(matched_indices):
        if int(target_indices.numel()) == 0:
            continue
        matched_count += int(target_indices.numel())
        source_logits = pred_logits[batch_index, prediction_indices, :num_classes]
        source_boxes = pred_boxes[batch_index, prediction_indices]
        source_masks = pred_masks[batch_index, prediction_indices]
        target_classes = targets[batch_index]["class_ids"][target_indices]
        target_boxes = targets[batch_index]["boxes"][target_indices]
        target_masks = targets[batch_index]["masks"][target_indices]

        target_class_onehot = torch.zeros_like(source_logits)
        target_class_onehot.scatter_(1, target_classes.unsqueeze(1), 1.0)
        loss_ce = loss_ce + sigmoid_focal_loss(source_logits, target_class_onehot)
        loss_bbox = loss_bbox + F.l1_loss(source_boxes, target_boxes, reduction="sum")
        loss_giou = loss_giou + _giou_loss_boxes(
            _box_cxcywh_to_xyxy(source_boxes),
            _box_cxcywh_to_xyxy(target_boxes),
        )

        resized_target_masks = F.interpolate(
            target_masks.unsqueeze(1),
            size=source_masks.shape[-2:],
            mode="nearest",
        ).squeeze(1)
        loss_mask_ce = loss_mask_ce + F.binary_cross_entropy_with_logits(
            source_masks,
            resized_target_masks,
            reduction="mean",
        )
        loss_mask_dice = loss_mask_dice + _dice_loss(
            source_masks,
            resized_target_masks,
        )

    normalizer = max(1, matched_count)
    return {
        "loss_ce": (loss_ce / normalizer) * class_weight,
        "loss_bbox": (loss_bbox / normalizer) * bbox_weight,
        "loss_giou": (loss_giou / normalizer) * giou_weight,
        "loss_mask_ce": (loss_mask_ce / normalizer) * mask_ce_weight,
        "loss_mask_dice": (loss_mask_dice / normalizer) * mask_dice_weight,
    }


def _dice_loss(
    logits: torch.Tensor,
    targets: torch.Tensor,
) -> torch.Tensor:
    probabilities = logits.sigmoid()
    probabilities = probabilities.flatten(1)
    targets = targets.flatten(1)
    numerator = 2.0 * (probabilities * targets).sum(dim=1)
    denominator = probabilities.sum(dim=1) + targets.sum(dim=1)
    loss = 1.0 - (numerator + 1.0) / (denominator + 1.0)
    return loss.mean()


def _evaluate_segmentation_model(
    *,
    model: torch.nn.Module,
    annotations: list[_RfdetrSegmentationAnnotation],
    input_size: tuple[int, int],
    device_name: str,
    precision: str,
    imports: Any,
) -> dict[str, float]:
    if not annotations:
        return {"val_mask_iou": 0.0, "val_box_iou": 0.0}
    model.eval()
    total_mask_iou = 0.0
    total_box_iou = 0.0
    sample_count = 0
    with imports.torch.no_grad():
        for annotation in annotations[:8]:
            batch = _build_training_batch(
                annotations=[annotation],
                input_size=input_size,
                device_name=device_name,
                precision=precision,
                imports=imports,
            )
            if batch is None:
                continue
            images, targets = batch
            with _autocast(imports.torch, precision, device_name):
                outputs = model(images)
            target_sizes = imports.torch.tensor(
                [[float(input_size[0]), float(input_size[1])]],
                device=images.device,
            )
            processed = model.postprocess(outputs, target_sizes)
            if processed["scores"].shape[1] == 0 or targets[0]["boxes"].shape[0] == 0:
                sample_count += 1
                continue
            best_prediction_index = int(processed["scores"][0].argmax().item())
            predicted_box = processed["boxes_xyxy"][0, best_prediction_index : best_prediction_index + 1]
            predicted_mask = processed["masks"][0, best_prediction_index : best_prediction_index + 1]
            target_box = _box_cxcywh_to_xyxy(targets[0]["boxes"][:1])
            target_box = _scale_xyxy_to_pixels(target_box, input_size)
            target_mask = F.interpolate(
                targets[0]["masks"][:1].unsqueeze(1),
                size=predicted_mask.shape[-2:],
                mode="nearest",
            ).squeeze(1)
            total_box_iou += float(
                _pairwise_box_iou(predicted_box, target_box).mean().item()
            )
            total_mask_iou += float(
                _pairwise_mask_iou(
                    predicted_mask.sigmoid() > 0.5,
                    target_mask > 0.5,
                ).mean().item()
            )
            sample_count += 1
    model.train()
    divisor = max(1, sample_count)
    return {
        "val_mask_iou": round(total_mask_iou / divisor, 6),
        "val_box_iou": round(total_box_iou / divisor, 6),
    }


def _pairwise_box_iou(boxes1: torch.Tensor, boxes2: torch.Tensor) -> torch.Tensor:
    x1 = torch.max(boxes1[:, None, 0], boxes2[None, :, 0])
    y1 = torch.max(boxes1[:, None, 1], boxes2[None, :, 1])
    x2 = torch.min(boxes1[:, None, 2], boxes2[None, :, 2])
    y2 = torch.min(boxes1[:, None, 3], boxes2[None, :, 3])
    inter = (x2 - x1).clamp(min=0) * (y2 - y1).clamp(min=0)
    area1 = (boxes1[:, 2] - boxes1[:, 0]).clamp(min=0) * (boxes1[:, 3] - boxes1[:, 1]).clamp(min=0)
    area2 = (boxes2[:, 2] - boxes2[:, 0]).clamp(min=0) * (boxes2[:, 3] - boxes2[:, 1]).clamp(min=0)
    return inter / (area1[:, None] + area2[None, :] - inter + 1e-7)


def _pairwise_mask_iou(pred_masks: torch.Tensor, gt_masks: torch.Tensor) -> torch.Tensor:
    pred_flat = pred_masks.reshape(pred_masks.shape[0], -1).float()
    gt_flat = gt_masks.reshape(gt_masks.shape[0], -1).float()
    inter = pred_flat @ gt_flat.transpose(0, 1)
    area_pred = pred_flat.sum(dim=1, keepdim=True)
    area_gt = gt_flat.sum(dim=1, keepdim=True).transpose(0, 1)
    return inter / (area_pred + area_gt - inter + 1e-7)


def _scale_xyxy_to_pixels(
    boxes_xyxy: torch.Tensor,
    image_size: tuple[int, int],
) -> torch.Tensor:
    image_height, image_width = image_size
    scale = torch.tensor(
        [float(image_width), float(image_height), float(image_width), float(image_height)],
        device=boxes_xyxy.device,
        dtype=boxes_xyxy.dtype,
    )
    return boxes_xyxy * scale


def _build_training_checkpoint(
    *,
    epoch: int,
    model: torch.nn.Module,
    optimizer: Any,
    scheduler: Any,
    epoch_history: list[dict[str, float]],
    validation_history: list[dict[str, float]],
    best_metric_value: float,
    best_metric_name: str,
    batch_size: int,
    max_epochs: int,
    learning_rate: float,
    weight_decay: float,
    class_cost: float,
    bbox_cost: float,
    giou_cost: float,
    class_weight: float,
    bbox_weight: float,
    giou_weight: float,
    mask_ce_weight: float,
    mask_dice_weight: float,
    evaluation_interval: int,
    imports: Any,
) -> bytes:
    payload = {
        "epoch": epoch + 1,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "scheduler_state_dict": scheduler.state_dict() if scheduler is not None else None,
        "metrics_history": epoch_history,
        "validation_history": validation_history,
        "best_metric_value": best_metric_value,
        "best_metric_name": best_metric_name,
        "saved_batch_size": batch_size,
        "saved_max_epochs": max_epochs,
        "saved_lr": learning_rate,
        "saved_weight_decay": weight_decay,
        "saved_class_cost": class_cost,
        "saved_bbox_cost": bbox_cost,
        "saved_giou_cost": giou_cost,
        "saved_class_weight": class_weight,
        "saved_bbox_weight": bbox_weight,
        "saved_giou_weight": giou_weight,
        "saved_mask_ce_weight": mask_ce_weight,
        "saved_mask_dice_weight": mask_dice_weight,
        "saved_eval_interval": evaluation_interval,
    }
    buffer = io.BytesIO()
    imports.torch.save(payload, buffer)
    return buffer.getvalue()


def _load_resume_state(
    request: RfdetrSegmentationTrainingExecutionRequest,
    imports: Any,
) -> _RfdetrSegmentationResumeState | None:
    if (
        request.resume_checkpoint_path is None
        or not request.resume_checkpoint_path.is_file()
    ):
        return None
    checkpoint = imports.torch.load(
        str(request.resume_checkpoint_path),
        map_location="cpu",
        weights_only=False,
    )
    return _RfdetrSegmentationResumeState(
        model_state_dict=checkpoint.get("model_state_dict", {}),
        optimizer_state_dict=checkpoint.get("optimizer_state_dict", {}),
        scheduler_state_dict=checkpoint.get("scheduler_state_dict"),
        metrics_history=checkpoint.get("metrics_history", []),
        validation_history=checkpoint.get("validation_history", []),
        best_metric_value=float(checkpoint.get("best_metric_value", 0.0)),
        best_metric_name=str(checkpoint.get("best_metric_name", "val_mask_iou")),
        epoch=int(checkpoint.get("epoch", 0)),
        saved_batch_size=int(checkpoint.get("saved_batch_size", 0)),
        saved_max_epochs=int(checkpoint.get("saved_max_epochs", 0)),
        saved_lr=float(checkpoint.get("saved_lr", 0.0)),
        saved_weight_decay=float(checkpoint.get("saved_weight_decay", 0.0)),
        saved_class_cost=float(checkpoint.get("saved_class_cost", 0.0)),
        saved_bbox_cost=float(checkpoint.get("saved_bbox_cost", 0.0)),
        saved_giou_cost=float(checkpoint.get("saved_giou_cost", 0.0)),
        saved_class_weight=float(checkpoint.get("saved_class_weight", 0.0)),
        saved_bbox_weight=float(checkpoint.get("saved_bbox_weight", 0.0)),
        saved_giou_weight=float(checkpoint.get("saved_giou_weight", 0.0)),
        saved_mask_ce_weight=float(checkpoint.get("saved_mask_ce_weight", 0.0)),
        saved_mask_dice_weight=float(checkpoint.get("saved_mask_dice_weight", 0.0)),
        saved_eval_interval=int(checkpoint.get("saved_eval_interval", 0)),
    )


def _validate_resume_state(
    *,
    resume_state: _RfdetrSegmentationResumeState,
    batch_size: int,
    max_epochs: int,
    learning_rate: float,
    weight_decay: float,
    class_cost: float,
    bbox_cost: float,
    giou_cost: float,
    class_weight: float,
    bbox_weight: float,
    giou_weight: float,
    mask_ce_weight: float,
    mask_dice_weight: float,
    evaluation_interval: int,
) -> None:
    mismatches: list[str] = []
    if resume_state.saved_batch_size != batch_size:
        mismatches.append("batch_size")
    if resume_state.saved_max_epochs != max_epochs:
        mismatches.append("max_epochs")
    if abs(resume_state.saved_lr - learning_rate) > 1e-8:
        mismatches.append("learning_rate")
    if abs(resume_state.saved_weight_decay - weight_decay) > 1e-8:
        mismatches.append("weight_decay")
    if abs(resume_state.saved_class_cost - class_cost) > 1e-8:
        mismatches.append("class_cost")
    if abs(resume_state.saved_bbox_cost - bbox_cost) > 1e-8:
        mismatches.append("bbox_cost")
    if abs(resume_state.saved_giou_cost - giou_cost) > 1e-8:
        mismatches.append("giou_cost")
    if abs(resume_state.saved_class_weight - class_weight) > 1e-8:
        mismatches.append("class_loss_weight")
    if abs(resume_state.saved_bbox_weight - bbox_weight) > 1e-8:
        mismatches.append("bbox_loss_weight")
    if abs(resume_state.saved_giou_weight - giou_weight) > 1e-8:
        mismatches.append("giou_loss_weight")
    if abs(resume_state.saved_mask_ce_weight - mask_ce_weight) > 1e-8:
        mismatches.append("mask_ce_loss_weight")
    if abs(resume_state.saved_mask_dice_weight - mask_dice_weight) > 1e-8:
        mismatches.append("mask_dice_loss_weight")
    if resume_state.saved_eval_interval != evaluation_interval:
        mismatches.append("evaluation_interval")
    if mismatches:
        raise InvalidRequestError(
            "resume 请求的训练参数与 checkpoint 不一致",
            details={"mismatches": mismatches},
        )


def _filter_state_dict(
    *,
    model_state_dict: dict[str, torch.Tensor],
    loaded_state_dict: dict[str, object],
) -> dict[str, object]:
    filtered: dict[str, object] = {}
    for key, value in loaded_state_dict.items():
        current = model_state_dict.get(key)
        if current is not None and hasattr(value, "shape") and current.shape == value.shape:
            filtered[key] = value
    return filtered


__all__ = [
    "RFDETR_SEGMENTATION_IMPLEMENTATION_MODE",
    "RfdetrSegmentationTrainingControlCommand",
    "RfdetrSegmentationTrainingEpochProgress",
    "RfdetrSegmentationTrainingExecutionRequest",
    "RfdetrSegmentationTrainingExecutionResult",
    "RfdetrSegmentationTrainingPausedError",
    "RfdetrSegmentationTrainingSavePoint",
    "RfdetrSegmentationTrainingTerminatedError",
    "run_rfdetr_segmentation_training",
]
