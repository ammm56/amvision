"""RF-DETR detection 训练执行模块。"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.models.rfdetr_model import (
    _box_cxcywh_to_xyxy,
    build_rfdetr_model,
    sigmoid_focal_loss,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


RFDETR_IMPL_MODE = "rfdetr-detection"

_RF_DEFAULT_INPUT_SIZE = (384, 384)
_RF_DEFAULT_BATCH_SIZE = 2
_RF_DEFAULT_MAX_EPOCHS = 1
_RF_DEFAULT_LR = 1e-4
_RF_DEFAULT_WEIGHT_DECAY = 1e-4
_RF_DEFAULT_CLASS_COST = 2.0
_RF_DEFAULT_BBOX_COST = 5.0
_RF_DEFAULT_GIOU_COST = 2.0
_RF_DEFAULT_CLASS_LOSS_WEIGHT = 1.0
_RF_DEFAULT_BBOX_LOSS_WEIGHT = 5.0
_RF_DEFAULT_GIOU_LOSS_WEIGHT = 2.0
_RF_FOCAL_ALPHA = 0.25
_RF_FOCAL_GAMMA = 2.0
_RF_COST_SANITIZE_MARGIN = 1.0


@dataclass(frozen=True)
class RfdetrTrainingBatchProgress:
    epoch: int
    max_epochs: int
    iteration: int
    max_iterations: int
    global_iteration: int
    total_iterations: int
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class RfdetrTrainingEpochProgress:
    epoch: int
    max_epochs: int
    learning_rate: float
    train_metrics: dict[str, float]


@dataclass(frozen=True)
class RfdetrTrainingSavePoint:
    latest_checkpoint_bytes: bytes
    train_metrics: dict[str, float]
    validation_metrics: dict[str, float]
    best_metric_value: float
    best_metric_name: str
    epoch: int
    learning_rate: float


@dataclass(frozen=True)
class RfdetrTrainingControlCommand:
    save_checkpoint: bool = False
    pause_training: bool = False
    terminate_training: bool = False


class RfdetrTrainingPausedError(Exception):
    """训练被暂停时抛出。"""


class RfdetrTrainingTerminatedError(Exception):
    """训练被终止时抛出。"""


@dataclass(frozen=True)
class RfdetrTrainingExecutionRequest:
    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    model_scale: str = "nano"
    batch_size: int = _RF_DEFAULT_BATCH_SIZE
    max_epochs: int = _RF_DEFAULT_MAX_EPOCHS
    input_size: tuple[int, int] | None = None
    precision: str = "fp32"
    resume_checkpoint_path: Path | None = None
    extra_options: dict[str, object] | None = None
    epoch_callback: Callable[
        [RfdetrTrainingEpochProgress],
        RfdetrTrainingControlCommand | None,
    ] | None = None
    savepoint_callback: Callable[[RfdetrTrainingSavePoint], None] | None = None


@dataclass(frozen=True)
class RfdetrTrainingExecutionResult:
    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    labels: tuple[str, ...]


@dataclass(frozen=True)
class _RfAnnotation:
    image_path: str
    boxes_xywh: list[list[float]]
    class_ids: list[int]


@dataclass(frozen=True)
class _RfImports:
    cv2: Any
    np: Any


def _require_rfdetr_training_imports() -> _RfImports:
    """导入 RF-DETR detection 训练需要的本地依赖。"""

    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ServiceConfigurationError(
            "RF-DETR detection 训练缺少必要依赖",
            details={"missing": str(exc)},
        ) from exc
    return _RfImports(cv2=cv2, np=np)


def _resolve_training_device(extra_options: dict[str, object] | None) -> str:
    """按请求解析训练设备。"""

    requested = str((extra_options or {}).get("device", "cpu")).strip().lower()
    if requested == "cuda" or requested.startswith("cuda:"):
        if torch.cuda.is_available():
            return requested
    return "cpu"


def _sanitize_cost_matrix(cost_matrix: torch.Tensor) -> torch.Tensor:
    """把非有限值替换成有限哨兵，避免 Hungarian 求解失败。"""

    finite_mask = torch.isfinite(cost_matrix)
    if finite_mask.all():
        return cost_matrix

    dtype_info = torch.finfo(cost_matrix.dtype)
    if finite_mask.any():
        finite_costs = cost_matrix[finite_mask]
        replacement_cost = (
            finite_costs.max()
            + finite_costs.abs().max()
            + _RF_COST_SANITIZE_MARGIN
        )
        if not torch.isfinite(replacement_cost):
            replacement_cost = cost_matrix.new_tensor(dtype_info.max)
        else:
            replacement_cost = torch.clamp(replacement_cost, max=dtype_info.max)
    else:
        replacement_cost = cost_matrix.new_tensor(dtype_info.max)

    sanitized_cost_matrix = cost_matrix.clone()
    sanitized_cost_matrix[~finite_mask] = replacement_cost
    return sanitized_cost_matrix


def _giou_loss_boxes(
    pred_boxes_xyxy: torch.Tensor,
    target_boxes_xyxy: torch.Tensor,
) -> torch.Tensor:
    """计算一组已配对框的平均 GIoU loss。"""

    pred_x1, pred_y1, pred_x2, pred_y2 = pred_boxes_xyxy.unbind(dim=1)
    target_x1, target_y1, target_x2, target_y2 = target_boxes_xyxy.unbind(dim=1)

    pred_area = (pred_x2 - pred_x1) * (pred_y2 - pred_y1)
    target_area = (target_x2 - target_x1) * (target_y2 - target_y1)

    inter_x1 = torch.max(pred_x1, target_x1)
    inter_y1 = torch.max(pred_y1, target_y1)
    inter_x2 = torch.min(pred_x2, target_x2)
    inter_y2 = torch.min(pred_y2, target_y2)
    inter_w = (inter_x2 - inter_x1).clamp(min=0)
    inter_h = (inter_y2 - inter_y1).clamp(min=0)
    inter_area = inter_w * inter_h

    union_area = pred_area + target_area - inter_area + 1e-7
    iou = inter_area / union_area

    outer_x1 = torch.min(pred_x1, target_x1)
    outer_y1 = torch.min(pred_y1, target_y1)
    outer_x2 = torch.max(pred_x2, target_x2)
    outer_y2 = torch.max(pred_y2, target_y2)
    outer_area = (outer_x2 - outer_x1) * (outer_y2 - outer_y1) + 1e-7
    giou = iou - (outer_area - union_area) / outer_area
    return 1.0 - giou.mean()


def _generalized_box_iou_batch(
    boxes1_xyxy: torch.Tensor,
    boxes2_xyxy: torch.Tensor,
) -> torch.Tensor:
    """批量计算成对框的 GIoU。"""

    area1 = (boxes1_xyxy[:, 2] - boxes1_xyxy[:, 0]) * (
        boxes1_xyxy[:, 3] - boxes1_xyxy[:, 1]
    )
    area2 = (boxes2_xyxy[:, 2] - boxes2_xyxy[:, 0]) * (
        boxes2_xyxy[:, 3] - boxes2_xyxy[:, 1]
    )

    left_top = torch.max(boxes1_xyxy[:, :2], boxes2_xyxy[:, :2])
    right_bottom = torch.min(boxes1_xyxy[:, 2:], boxes2_xyxy[:, 2:])
    inter_wh = (right_bottom - left_top).clamp(min=0)
    inter_area = inter_wh[:, 0] * inter_wh[:, 1]

    union_area = area1 + area2 - inter_area + 1e-7
    iou = inter_area / union_area

    outer_left_top = torch.min(boxes1_xyxy[:, :2], boxes2_xyxy[:, :2])
    outer_right_bottom = torch.max(boxes1_xyxy[:, 2:], boxes2_xyxy[:, 2:])
    outer_wh = (outer_right_bottom - outer_left_top).clamp(min=0)
    outer_area = outer_wh[:, 0] * outer_wh[:, 1] + 1e-7
    return iou - (outer_area - union_area) / outer_area


def _compute_pairwise_giou(
    boxes1_xyxy: torch.Tensor,
    boxes2_xyxy: torch.Tensor,
) -> torch.Tensor:
    """计算两组 `xyxy` 框的两两 GIoU 矩阵。"""

    query_count, _ = boxes1_xyxy.shape
    target_count, _ = boxes2_xyxy.shape
    expanded_boxes1 = (
        boxes1_xyxy.unsqueeze(1).expand(query_count, target_count, 4).contiguous().view(-1, 4)
    )
    expanded_boxes2 = (
        boxes2_xyxy.unsqueeze(0).expand(query_count, target_count, 4).contiguous().view(-1, 4)
    )
    pairwise_giou = _generalized_box_iou_batch(expanded_boxes1, expanded_boxes2)
    return pairwise_giou.view(query_count, target_count)


def _build_focal_class_cost(
    pred_logits: torch.Tensor,
    target_class_ids: torch.Tensor,
) -> torch.Tensor:
    """按 RF-DETR 参考 matcher 的 focal cost 计算分类代价。"""

    out_prob = pred_logits.sigmoid()
    neg_cost_class = (
        (1 - _RF_FOCAL_ALPHA)
        * (out_prob**_RF_FOCAL_GAMMA)
        * (-F.logsigmoid(-pred_logits))
    )
    pos_cost_class = (
        _RF_FOCAL_ALPHA
        * ((1 - out_prob) ** _RF_FOCAL_GAMMA)
        * (-F.logsigmoid(pred_logits))
    )
    return pos_cost_class[:, target_class_ids] - neg_cost_class[:, target_class_ids]


def _hungarian_match(
    pred_logits: torch.Tensor,
    pred_boxes: torch.Tensor,
    targets: list[dict[str, object]],
    class_cost_weight: float,
    bbox_cost_weight: float,
    giou_cost_weight: float,
    num_classes: int,
) -> list[tuple[torch.Tensor, torch.Tensor]]:
    """执行一批 RF-DETR detection Hungarian 匹配。"""

    from scipy.optimize import linear_sum_assignment

    batch_size, _, _ = pred_logits.shape
    matched_indices: list[tuple[torch.Tensor, torch.Tensor]] = []

    for batch_index in range(batch_size):
        target = targets[batch_index]
        target_class_ids = torch.as_tensor(
            target["class_ids"],
            dtype=torch.long,
            device=pred_logits.device,
        )
        if target_class_ids.numel() == 0:
            matched_indices.append(
                (
                    torch.empty(0, dtype=torch.long),
                    torch.empty(0, dtype=torch.long),
                )
            )
            continue

        target_boxes = torch.as_tensor(
            target["boxes"],
            dtype=torch.float32,
            device=pred_boxes.device,
        )
        query_logits = pred_logits[batch_index, :, :num_classes]
        query_boxes = pred_boxes[batch_index]

        cost_class = _build_focal_class_cost(query_logits, target_class_ids)
        cost_bbox = torch.cdist(query_boxes, target_boxes, p=1)
        cost_giou = -_compute_pairwise_giou(
            _box_cxcywh_to_xyxy(query_boxes),
            _box_cxcywh_to_xyxy(target_boxes),
        )

        total_cost = (
            class_cost_weight * cost_class
            + bbox_cost_weight * cost_bbox
            + giou_cost_weight * cost_giou
        )
        total_cost = _sanitize_cost_matrix(total_cost.float()).cpu()
        prediction_indices, target_indices = linear_sum_assignment(total_cost.numpy())
        matched_indices.append(
            (
                torch.as_tensor(prediction_indices, dtype=torch.long),
                torch.as_tensor(target_indices, dtype=torch.long),
            )
        )

    return matched_indices


def _compute_set_criterion_loss(
    pred_logits: torch.Tensor,
    pred_boxes: torch.Tensor,
    targets: list[dict[str, object]],
    matched: list[tuple[torch.Tensor, torch.Tensor]],
    num_classes: int,
    class_loss_weight: float,
    bbox_loss_weight: float,
    giou_loss_weight: float,
) -> dict[str, torch.Tensor]:
    """根据匹配结果计算 RF-DETR detection 训练 loss。"""

    device = pred_logits.device
    matched_box_count = sum(int(len(target_indices)) for _, target_indices in matched)
    normalizer = max(1, matched_box_count)

    loss_ce = torch.tensor(0.0, device=device)
    loss_bbox = torch.tensor(0.0, device=device)
    loss_giou = torch.tensor(0.0, device=device)

    for batch_index, (prediction_indices, target_indices) in enumerate(matched):
        if len(target_indices) == 0:
            continue

        src_logits = pred_logits[batch_index, prediction_indices]
        src_boxes = pred_boxes[batch_index, prediction_indices]
        matched_target_indexes = [int(target_index) for target_index in target_indices.tolist()]

        matched_class_ids = torch.as_tensor(
            [
                targets[batch_index]["class_ids"][target_index]
                for target_index in matched_target_indexes
            ],
            dtype=torch.long,
            device=device,
        )
        matched_target_boxes = torch.as_tensor(
            [
                targets[batch_index]["boxes"][target_index]
                for target_index in matched_target_indexes
            ],
            dtype=torch.float32,
            device=device,
        )

        target_class_onehot = torch.zeros(
            (len(prediction_indices), num_classes),
            dtype=src_logits.dtype,
            device=device,
        )
        target_class_onehot[
            torch.arange(len(prediction_indices), device=device),
            matched_class_ids,
        ] = 1.0

        loss_ce = loss_ce + sigmoid_focal_loss(
            src_logits[:, :num_classes],
            target_class_onehot,
        ) * len(prediction_indices)
        loss_bbox = loss_bbox + F.l1_loss(
            src_boxes,
            matched_target_boxes,
            reduction="sum",
        )
        loss_giou = loss_giou + _giou_loss_boxes(
            _box_cxcywh_to_xyxy(src_boxes),
            _box_cxcywh_to_xyxy(matched_target_boxes),
        ) * len(prediction_indices)

    return {
        "loss_ce": loss_ce / normalizer * class_loss_weight,
        "loss_bbox": loss_bbox / normalizer * bbox_loss_weight,
        "loss_giou": loss_giou / normalizer * giou_loss_weight,
    }


def run_rfdetr_training(
    request: RfdetrTrainingExecutionRequest,
) -> RfdetrTrainingExecutionResult:
    """执行一轮项目内 RF-DETR detection 训练。"""

    imports = _require_rfdetr_training_imports()
    device = _resolve_training_device(request.extra_options)
    input_size = request.input_size or _RF_DEFAULT_INPUT_SIZE

    labels, train_annotations, _ = _rf_load_manifest(
        request.dataset_storage,
        request.manifest_payload,
    )
    if not labels:
        raise InvalidRequestError("RF-DETR detection 训练 manifest 缺少合法类别")
    if not train_annotations:
        raise InvalidRequestError("RF-DETR detection 训练 manifest 缺少合法 train 样本")

    num_classes = len(labels)
    model = build_rfdetr_model(
        model_scale=request.model_scale,
        num_classes=num_classes,
    )
    model.to(device)

    extra_options = dict(request.extra_options or {})
    learning_rate = float(extra_options.get("learning_rate", _RF_DEFAULT_LR))
    weight_decay = float(extra_options.get("weight_decay", _RF_DEFAULT_WEIGHT_DECAY))
    batch_size = max(1, int(extra_options.get("batch_size", request.batch_size)))
    max_epochs = max(1, int(extra_options.get("max_epochs", request.max_epochs)))
    class_cost_weight = float(
        extra_options.get("class_cost", _RF_DEFAULT_CLASS_COST)
    )
    bbox_cost_weight = float(
        extra_options.get("bbox_cost", _RF_DEFAULT_BBOX_COST)
    )
    giou_cost_weight = float(
        extra_options.get("giou_cost", _RF_DEFAULT_GIOU_COST)
    )
    class_loss_weight = float(
        extra_options.get("class_loss_weight", _RF_DEFAULT_CLASS_LOSS_WEIGHT)
    )
    bbox_loss_weight = float(
        extra_options.get("bbox_loss_weight", _RF_DEFAULT_BBOX_LOSS_WEIGHT)
    )
    giou_loss_weight = float(
        extra_options.get("giou_loss_weight", _RF_DEFAULT_GIOU_LOSS_WEIGHT)
    )

    trainable_parameters = [
        parameter
        for parameter in model.parameters()
        if parameter.requires_grad
    ]
    optimizer = torch.optim.AdamW(
        trainable_parameters,
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    iterations_per_epoch = max(
        1,
        (len(train_annotations) + batch_size - 1) // batch_size,
    )
    total_iterations = max_epochs * iterations_per_epoch
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer,
        T_max=total_iterations,
        eta_min=learning_rate * 0.01,
    )

    metrics_history: list[dict[str, object]] = []
    latest_checkpoint_bytes = b""

    for epoch in range(max_epochs):
        model.train()
        epoch_class_loss = 0.0
        epoch_bbox_loss = 0.0
        epoch_giou_loss = 0.0
        epoch_iterations = 0

        for batch_start in range(0, len(train_annotations), batch_size):
            batch_annotations = train_annotations[batch_start:batch_start + batch_size]
            images, targets = _rf_build_batch(
                batch_annotations,
                input_size,
                device,
                imports,
            )
            if images is None:
                continue

            outputs = model(images)
            pred_logits = outputs["pred_logits"]
            pred_boxes = outputs["pred_boxes"]
            matched = _hungarian_match(
                pred_logits.detach(),
                pred_boxes.detach(),
                targets,
                class_cost_weight,
                bbox_cost_weight,
                giou_cost_weight,
                num_classes,
            )
            losses = _compute_set_criterion_loss(
                pred_logits,
                pred_boxes,
                targets,
                matched,
                num_classes,
                class_loss_weight,
                bbox_loss_weight,
                giou_loss_weight,
            )
            total_loss = (
                losses["loss_ce"]
                + losses["loss_bbox"]
                + losses["loss_giou"]
            )

            optimizer.zero_grad()
            total_loss.backward()
            optimizer.step()
            scheduler.step()

            epoch_class_loss += float(losses["loss_ce"].item())
            epoch_bbox_loss += float(losses["loss_bbox"].item())
            epoch_giou_loss += float(losses["loss_giou"].item())
            epoch_iterations += 1

        if epoch_iterations > 0:
            epoch_class_loss /= epoch_iterations
            epoch_bbox_loss /= epoch_iterations
            epoch_giou_loss /= epoch_iterations

        epoch_metrics = {
            "class_loss": round(epoch_class_loss, 6),
            "bbox_loss": round(epoch_bbox_loss, 6),
            "giou_loss": round(epoch_giou_loss, 6),
        }
        metrics_history.append({"epoch": epoch, **epoch_metrics})

        epoch_progress = RfdetrTrainingEpochProgress(
            epoch=epoch,
            max_epochs=max_epochs,
            learning_rate=float(scheduler.get_last_lr()[0]),
            train_metrics=epoch_metrics,
        )
        command = (
            request.epoch_callback(epoch_progress)
            if request.epoch_callback is not None
            else None
        )
        if command is not None and command.terminate_training:
            raise RfdetrTrainingTerminatedError()

        latest_checkpoint_bytes = _build_rfdetr_checkpoint_bytes(
            epoch=epoch,
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            metrics_history=metrics_history,
        )
        if command is not None and request.savepoint_callback is not None:
            request.savepoint_callback(
                RfdetrTrainingSavePoint(
                    latest_checkpoint_bytes=latest_checkpoint_bytes,
                    train_metrics=epoch_metrics,
                    validation_metrics={},
                    best_metric_value=0.0,
                    best_metric_name="val_loss",
                    epoch=epoch + 1,
                    learning_rate=float(scheduler.get_last_lr()[0]),
                )
            )
        if command is not None and command.pause_training:
            raise RfdetrTrainingPausedError()

    return RfdetrTrainingExecutionResult(
        best_metric_value=0.0,
        best_metric_name="val_loss",
        latest_checkpoint_bytes=latest_checkpoint_bytes,
        metrics_payload={"epoch_history": metrics_history},
        validation_metrics_payload={},
        labels=labels,
    )


def _build_rfdetr_checkpoint_bytes(
    *,
    epoch: int,
    model,
    optimizer,
    scheduler,
    metrics_history: list[dict[str, object]],
) -> bytes:
    """构建 RF-DETR detection 训练 checkpoint。"""

    checkpoint_buffer = io.BytesIO()
    torch.save(
        {
            "epoch": epoch + 1,
            "model_state_dict": model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "scheduler_state_dict": scheduler.state_dict(),
            "metrics_history": metrics_history,
        },
        checkpoint_buffer,
    )
    return checkpoint_buffer.getvalue()


def _rf_load_manifest(
    dataset_storage: LocalDatasetStorage,
    manifest: dict[str, object],
) -> tuple[tuple[str, ...], list[_RfAnnotation], list[_RfAnnotation]]:
    """从 COCO detection manifest 读取 RF-DETR detection 训练样本。"""

    splits = manifest.get("splits", [])
    categories_by_id: dict[int, str] = {}
    train_annotations: list[_RfAnnotation] = []
    val_annotations: list[_RfAnnotation] = []

    for split_payload in splits or []:
        if not isinstance(split_payload, dict):
            continue

        split_name = str(split_payload.get("name", ""))
        image_root = str(split_payload.get("image_root", ""))
        annotation_file = str(split_payload.get("annotation_file", ""))
        annotation_path = dataset_storage.resolve(annotation_file)
        if not annotation_path.is_file():
            continue

        annotation_payload = dataset_storage.read_json(annotation_file)
        if not isinstance(annotation_payload, dict):
            continue

        for category in annotation_payload.get("categories") or []:
            if isinstance(category, dict):
                categories_by_id[int(category.get("id", -1))] = str(
                    category.get("name", "")
                )

        image_file_names: dict[int, str] = {}
        for image_payload in annotation_payload.get("images") or []:
            if isinstance(image_payload, dict):
                image_file_names[int(image_payload.get("id", -1))] = str(
                    image_payload.get("file_name", "")
                )

        split_annotations: list[_RfAnnotation] = []
        for annotation in annotation_payload.get("annotations") or []:
            if not isinstance(annotation, dict):
                continue

            image_id = int(annotation.get("image_id", -1))
            image_file_name = image_file_names.get(image_id, "")
            if not image_file_name:
                continue

            bbox = annotation.get("bbox")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue

            split_annotations.append(
                _RfAnnotation(
                    image_path=str(dataset_storage.resolve(f"{image_root}/{image_file_name}")),
                    boxes_xywh=[bbox],
                    class_ids=[int(annotation.get("category_id", 0))],
                )
            )

        if split_name == "train":
            train_annotations = split_annotations
        elif split_name == "val":
            val_annotations = split_annotations

    sorted_categories = sorted(categories_by_id.items())
    category_id_mapping = {
        category_id: index
        for index, (category_id, _) in enumerate(sorted_categories)
    }
    labels = tuple(category_name for _, category_name in sorted_categories)

    return (
        labels,
        [
            _RfAnnotation(
                image_path=annotation.image_path,
                boxes_xywh=annotation.boxes_xywh,
                class_ids=[
                    category_id_mapping.get(category_id, 0)
                    for category_id in annotation.class_ids
                ],
            )
            for annotation in train_annotations
        ],
        [
            _RfAnnotation(
                image_path=annotation.image_path,
                boxes_xywh=annotation.boxes_xywh,
                class_ids=[
                    category_id_mapping.get(category_id, 0)
                    for category_id in annotation.class_ids
                ],
            )
            for annotation in val_annotations
        ],
    )


def _rf_build_batch(
    annotations: list[_RfAnnotation],
    input_size: tuple[int, int],
    device: str,
    imports: _RfImports,
) -> tuple[torch.Tensor | None, list[dict[str, object]]]:
    """构建一批 RF-DETR detection 训练输入。"""

    if not annotations:
        return None, []

    images: list[torch.Tensor] = []
    targets: list[dict[str, object]] = []
    target_width, target_height = input_size

    for annotation in annotations:
        image = imports.cv2.imread(annotation.image_path)
        if image is None:
            continue

        height, width = image.shape[:2]
        resized = imports.cv2.resize(
            image,
            (target_width, target_height),
            interpolation=imports.cv2.INTER_LINEAR,
        )
        image_tensor = (
            resized[:, :, ::-1]
            .transpose(2, 0, 1)
            .astype(imports.np.float32)
            / 255.0
        )
        images.append(torch.from_numpy(image_tensor).to(device).float())

        normalized_boxes = [
            [
                (x + box_width / 2) / width,
                (y + box_height / 2) / height,
                box_width / width,
                box_height / height,
            ]
            for x, y, box_width, box_height in annotation.boxes_xywh
        ]
        targets.append(
            {
                "boxes": normalized_boxes,
                "class_ids": annotation.class_ids,
            }
        )

    if not images:
        return None, []
    return torch.stack(images, dim=0), targets
