"""YOLOX COCO detection 评估工具。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from contextlib import redirect_stdout
from dataclasses import dataclass
import io
from pathlib import Path
from typing import Any

import numpy as np

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.yolox_core.data.datasets import (
    load_coco_ground_truth_silently,
)


@dataclass(frozen=True)
class CocoDetectionMetrics:
    """描述一次 COCO detection 评估结果。"""

    map50_95: float
    map50: float
    per_class_metrics: tuple[dict[str, object], ...]


def evaluate_coco_detections(
    *,
    coco_class: Any,
    cocoeval_class: Any,
    annotation_file: Path,
    detections: list[dict[str, object]],
    category_ids: tuple[int, ...],
    category_names: tuple[str, ...],
) -> CocoDetectionMetrics:
    """执行 COCO bbox mAP 评估。"""

    ground_truth = load_coco_ground_truth_silently(
        coco_class=coco_class,
        annotation_file=annotation_file,
    )
    if not detections:
        return CocoDetectionMetrics(
            map50_95=0.0,
            map50=0.0,
            per_class_metrics=build_zero_coco_per_class_metrics(
                ground_truth=ground_truth,
                category_ids=category_ids,
                category_names=category_names,
                detections=tuple(),
            ),
        )

    with redirect_stdout(io.StringIO()):
        coco_detections = ground_truth.loadRes(detections)
        coco_evaluator = cocoeval_class(ground_truth, coco_detections, "bbox")
        coco_evaluator.evaluate()
        coco_evaluator.accumulate()
        coco_evaluator.summarize()

    return CocoDetectionMetrics(
        map50_95=float(coco_evaluator.stats[0]),
        map50=float(coco_evaluator.stats[1]),
        per_class_metrics=build_coco_per_class_metrics(
            coco_evaluator=coco_evaluator,
            ground_truth=ground_truth,
            category_ids=category_ids,
            category_names=category_names,
            detections=tuple(detections),
        ),
    )


def collect_yolox_coco_detections(
    *,
    torch_module: Any,
    postprocess: Callable[..., list[object]],
    autocast_context_factory: Callable[..., Any],
    model: Any,
    loader: Any,
    device: str,
    precision: str,
    input_size: tuple[int, int],
    num_classes: int,
    category_ids: tuple[int, ...],
    score_threshold: float,
    nms_threshold: float,
) -> tuple[dict[str, object], ...]:
    """把 YOLOX 模型输出转换为 COCO detection 结果列表。"""

    detections: list[dict[str, object]] = []
    with torch_module.no_grad():
        for images, _targets, image_infos, image_ids in loader:
            images = images.to(device=device, dtype=torch_module.float32)
            with autocast_context_factory(
                torch_module=torch_module,
                device=device,
                precision=precision,
            ):
                raw_outputs = model(images)
            processed_outputs = postprocess(
                raw_outputs,
                num_classes,
                conf_thre=score_threshold,
                nms_thre=nms_threshold,
                class_agnostic=False,
            )
            detections.extend(
                convert_yolox_predictions_to_coco_detections(
                    predictions=processed_outputs,
                    image_infos=image_infos,
                    image_ids=image_ids,
                    input_size=input_size,
                    category_ids=category_ids,
                )
            )

    return tuple(detections)


def evaluate_yolox_coco_map(
    *,
    torch_module: Any,
    postprocess: Callable[..., list[object]],
    autocast_context_factory: Callable[..., Any],
    coco_class: Any,
    cocoeval_class: Any,
    model: Any,
    loader: Any,
    device: str,
    precision: str,
    input_size: tuple[int, int],
    num_classes: int,
    category_ids: tuple[int, ...],
    category_names: tuple[str, ...],
    annotation_file: Path,
    score_threshold: float,
    nms_threshold: float,
) -> CocoDetectionMetrics:
    """执行 YOLOX PyTorch 模型在 COCO detection split 上的 mAP 评估。"""

    if len(loader) == 0:
        return evaluate_coco_detections(
            coco_class=coco_class,
            cocoeval_class=cocoeval_class,
            annotation_file=annotation_file,
            detections=[],
            category_ids=category_ids,
            category_names=category_names,
        )

    was_training = bool(model.training)
    model.eval()
    try:
        detections = collect_yolox_coco_detections(
            torch_module=torch_module,
            postprocess=postprocess,
            autocast_context_factory=autocast_context_factory,
            model=model,
            loader=loader,
            device=device,
            precision=precision,
            input_size=input_size,
            num_classes=num_classes,
            category_ids=category_ids,
            score_threshold=score_threshold,
            nms_threshold=nms_threshold,
        )
    finally:
        model.train(was_training)

    return evaluate_coco_detections(
        coco_class=coco_class,
        cocoeval_class=cocoeval_class,
        annotation_file=annotation_file,
        detections=list(detections),
        category_ids=category_ids,
        category_names=category_names,
    )


def convert_yolox_predictions_to_coco_detections(
    *,
    predictions: list[object],
    image_infos: object,
    image_ids: object,
    input_size: tuple[int, int],
    category_ids: tuple[int, ...],
) -> list[dict[str, object]]:
    """把 YOLOX postprocess 输出转换为 COCO detection 结果。"""

    detections: list[dict[str, object]] = []
    for batch_index, prediction in enumerate(predictions):
        if prediction is None:
            continue
        image_height, image_width = _extract_batch_image_info(image_infos, batch_index)
        image_id = _extract_batch_image_id(image_ids, batch_index)
        resize_ratio = min(
            input_size[0] / max(1.0, float(image_height)),
            input_size[1] / max(1.0, float(image_width)),
        )
        if resize_ratio <= 0:
            continue

        prediction_tensor = prediction.detach().cpu()
        boxes = prediction_tensor[:, 0:4] / resize_ratio
        scores = prediction_tensor[:, 4] * prediction_tensor[:, 5]
        classes = prediction_tensor[:, 6]
        for row_index in range(prediction_tensor.shape[0]):
            class_index = int(classes[row_index].item())
            if class_index < 0 or class_index >= len(category_ids):
                continue

            x1, y1, x2, y2 = boxes[row_index].tolist()
            x1 = max(0.0, min(float(x1), float(image_width)))
            y1 = max(0.0, min(float(y1), float(image_height)))
            x2 = max(0.0, min(float(x2), float(image_width)))
            y2 = max(0.0, min(float(y2), float(image_height)))
            box_width = max(0.0, x2 - x1)
            box_height = max(0.0, y2 - y1)
            if box_width <= 0 or box_height <= 0:
                continue

            detections.append(
                {
                    "image_id": image_id,
                    "category_id": category_ids[class_index],
                    "bbox": [x1, y1, box_width, box_height],
                    "score": float(scores[row_index].item()),
                }
            )
    return detections


def build_coco_per_class_metrics(
    *,
    coco_evaluator: Any,
    ground_truth: Any,
    category_ids: tuple[int, ...],
    category_names: tuple[str, ...],
    detections: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    """从 COCOeval precision 张量中提取每类 AP 指标。"""

    precision = coco_evaluator.eval.get("precision")
    if not isinstance(precision, np.ndarray) or precision.ndim < 5:
        return build_zero_coco_per_class_metrics(
            ground_truth=ground_truth,
            category_ids=category_ids,
            category_names=category_names,
            detections=detections,
        )

    iou_thresholds = list(coco_evaluator.params.iouThrs)
    ap50_index = _resolve_iou_threshold_index(iou_thresholds, 0.5)
    detection_counts = _count_coco_detections_by_category(detections)
    metrics: list[dict[str, object]] = []
    for category_index, category_id in enumerate(category_ids):
        category_name = _resolve_category_name(category_names, category_index, category_id)
        class_precision = precision[:, :, category_index, 0, -1]
        valid_precision = class_precision[class_precision > -1]
        ap50_95 = float(valid_precision.mean()) if valid_precision.size else 0.0
        ap50_precision = precision[ap50_index, :, category_index, 0, -1]
        valid_ap50_precision = ap50_precision[ap50_precision > -1]
        ap50 = float(valid_ap50_precision.mean()) if valid_ap50_precision.size else 0.0
        metrics.append(
            {
                "category_id": category_id,
                "class_index": category_index,
                "class_name": category_name,
                "ground_truth_count": len(ground_truth.getAnnIds(catIds=[category_id])),
                "detection_count": detection_counts.get(category_id, 0),
                "ap50_95": round(ap50_95, 6),
                "ap50": round(ap50, 6),
            }
        )
    return tuple(metrics)


def build_zero_coco_per_class_metrics(
    *,
    ground_truth: Any,
    category_ids: tuple[int, ...],
    category_names: tuple[str, ...],
    detections: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    """构建 COCO 评估无有效检测结果时的 per-class metrics。"""

    detection_counts = _count_coco_detections_by_category(detections)
    return tuple(
        {
            "category_id": category_id,
            "class_index": class_index,
            "class_name": _resolve_category_name(category_names, class_index, category_id),
            "ground_truth_count": len(ground_truth.getAnnIds(catIds=[category_id])),
            "detection_count": detection_counts.get(category_id, 0),
            "ap50": 0.0,
            "ap50_95": 0.0,
        }
        for class_index, category_id in enumerate(category_ids)
    )


def _count_coco_detections_by_category(
    detections: tuple[dict[str, object], ...],
) -> Counter[int]:
    """统计 COCO detection 结果中每个 category_id 的预测数量。"""

    return Counter(
        int(detection["category_id"])
        for detection in detections
        if isinstance(detection.get("category_id"), int)
    )


def _resolve_category_name(
    category_names: tuple[str, ...],
    class_index: int,
    category_id: int,
) -> str:
    """按类别顺序读取类别名，缺失时生成稳定占位名。"""

    if class_index < len(category_names):
        return category_names[class_index]
    return f"class-{category_id}"


def _extract_batch_image_info(image_infos: object, batch_index: int) -> tuple[int, int]:
    """从 DataLoader 合并结果中读取单张图片的原图尺寸。"""

    if (
        isinstance(image_infos, list | tuple)
        and len(image_infos) == 2
        and all(hasattr(item, "__getitem__") for item in image_infos)
    ):
        return int(image_infos[0][batch_index]), int(image_infos[1][batch_index])
    if isinstance(image_infos, list | tuple) and len(image_infos) > batch_index:
        image_info = image_infos[batch_index]
        if isinstance(image_info, list | tuple) and len(image_info) == 2:
            return int(image_info[0]), int(image_info[1])
    raise ServiceConfigurationError("验证批次中的 image_infos 结构不合法")


def _extract_batch_image_id(image_ids: object, batch_index: int) -> int:
    """从 DataLoader 合并结果中读取单张图片的 image_id。"""

    if hasattr(image_ids, "__getitem__"):
        return int(image_ids[batch_index])
    raise ServiceConfigurationError("验证批次中的 image_ids 结构不合法")


def _resolve_iou_threshold_index(iou_thresholds: list[float], target: float) -> int:
    """查找最接近目标 IoU threshold 的索引。"""

    if not iou_thresholds:
        return 0
    return min(
        range(len(iou_thresholds)),
        key=lambda index: abs(float(iou_thresholds[index]) - target),
    )
