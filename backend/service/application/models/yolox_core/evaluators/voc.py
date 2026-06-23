"""YOLOX VOC detection 原生评估工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from backend.service.application.models.yolox_core.data.datasets.voc import (
    VocDetectionExportDataset,
)
from backend.service.application.models.yolox_core.evaluators.coco import (
    collect_yolox_coco_detections,
)


DEFAULT_VOC_IOU_THRESHOLDS: tuple[float, ...] = tuple(
    round(float(value), 2)
    for value in np.linspace(0.5, 0.95, int(round((0.95 - 0.5) / 0.05)) + 1)
)


@dataclass(frozen=True)
class VocDetectionMetrics:
    """描述一次 VOC detection 评估结果。"""

    map50_95: float
    map50: float
    per_class_metrics: tuple[dict[str, object], ...]


def evaluate_voc_detections(
    *,
    dataset: VocDetectionExportDataset,
    detections: list[dict[str, object]],
    category_names: tuple[str, ...],
    iou_thresholds: tuple[float, ...] = DEFAULT_VOC_IOU_THRESHOLDS,
    use_07_metric: bool = False,
) -> VocDetectionMetrics:
    """按 VOC 规则评估 detection 结果。

    本项目直接在内存中计算 VOC AP，不再把 VOC DatasetExport 先转换成
    COCO-style ground truth。训练标签和模型输出均按 YOLOX 的 0-based
    `xyxy` 坐标处理，IoU 面积计算仍使用 VOC 的 inclusive 规则。
    """

    if not iou_thresholds:
        iou_thresholds = (0.5,)

    metrics: list[dict[str, object]] = []
    class_ap50_values: list[float] = []
    class_ap50_95_values: list[float] = []
    for class_index, class_name in enumerate(dataset.category_names):
        ap_by_threshold: dict[float, float] = {}
        rec_by_threshold: dict[float, np.ndarray] = {}
        prec_by_threshold: dict[float, np.ndarray] = {}
        for threshold in iou_thresholds:
            rec, prec, ap = evaluate_voc_class_detections(
                dataset=dataset,
                detections=detections,
                class_index=class_index,
                class_name=class_name,
                iou_threshold=float(threshold),
                use_07_metric=use_07_metric,
            )
            ap_by_threshold[float(threshold)] = float(ap)
            rec_by_threshold[float(threshold)] = rec
            prec_by_threshold[float(threshold)] = prec

        ap50 = float(ap_by_threshold.get(0.5, next(iter(ap_by_threshold.values()), 0.0)))
        ap50_95 = float(np.mean(list(ap_by_threshold.values()))) if ap_by_threshold else 0.0
        ground_truth_count = _count_voc_ground_truth(dataset=dataset, class_name=class_name)
        detection_count = _count_voc_detections(detections=detections, class_index=class_index)
        metrics.append(
            {
                "category_id": class_index,
                "class_index": class_index,
                "class_name": _resolve_category_name(category_names, class_index, class_name),
                "ground_truth_count": ground_truth_count,
                "detection_count": detection_count,
                "ap50_95": round(ap50_95, 6),
                "ap50": round(ap50, 6),
                "recall50": round(float(rec_by_threshold.get(0.5, np.array([0.0]))[-1]), 6)
                if rec_by_threshold.get(0.5, np.array([])).size
                else 0.0,
                "precision50": round(float(prec_by_threshold.get(0.5, np.array([0.0]))[-1]), 6)
                if prec_by_threshold.get(0.5, np.array([])).size
                else 0.0,
                "metric": "voc-python",
            }
        )
        class_ap50_values.append(ap50)
        class_ap50_95_values.append(ap50_95)

    return VocDetectionMetrics(
        map50_95=round(float(np.mean(class_ap50_95_values)) if class_ap50_95_values else 0.0, 6),
        map50=round(float(np.mean(class_ap50_values)) if class_ap50_values else 0.0, 6),
        per_class_metrics=tuple(metrics),
    )


def evaluate_yolox_voc_map(
    *,
    torch_module: Any,
    postprocess: Any,
    autocast_context_factory: Any,
    model: Any,
    loader: Any,
    device: str,
    precision: str,
    input_size: tuple[int, int],
    num_classes: int,
    dataset: VocDetectionExportDataset,
    category_names: tuple[str, ...],
    score_threshold: float,
    nms_threshold: float,
) -> VocDetectionMetrics:
    """执行 YOLOX PyTorch 模型在 VOC detection split 上的原生 VOC 评估。"""

    if len(loader) == 0:
        return evaluate_voc_detections(
            dataset=dataset,
            detections=[],
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
            category_ids=dataset.category_ids,
            score_threshold=score_threshold,
            nms_threshold=nms_threshold,
        )
    finally:
        model.train(was_training)

    return evaluate_voc_detections(
        dataset=dataset,
        detections=[dict(item) for item in detections],
        category_names=category_names,
    )


def evaluate_voc_class_detections(
    *,
    dataset: VocDetectionExportDataset,
    detections: list[dict[str, object]],
    class_index: int,
    class_name: str,
    iou_threshold: float,
    use_07_metric: bool,
) -> tuple[np.ndarray, np.ndarray, float]:
    """评估单个 VOC 类别在一个 IoU threshold 下的 AP。"""

    class_records = _build_voc_class_records(dataset=dataset, class_name=class_name)
    positive_count = sum(int(np.logical_not(record["difficult"]).sum()) for record in class_records.values())
    class_detections = _filter_voc_class_detections(
        detections=detections,
        class_index=class_index,
    )
    if positive_count <= 0 or not class_detections:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64), 0.0

    confidence = np.array([item[1] for item in class_detections], dtype=np.float64)
    sorted_indices = np.argsort(-confidence)
    sorted_detections = [class_detections[index] for index in sorted_indices]
    true_positive = np.zeros(len(sorted_detections), dtype=np.float64)
    false_positive = np.zeros(len(sorted_detections), dtype=np.float64)

    for detection_index, (image_id, _score, box) in enumerate(sorted_detections):
        record = class_records.get(image_id)
        if record is None:
            false_positive[detection_index] = 1.0
            continue

        gt_boxes = record["bbox"]
        max_overlap = -np.inf
        max_index = -1
        if gt_boxes.size > 0:
            overlaps = _voc_inclusive_iou(box, gt_boxes)
            max_overlap = float(np.max(overlaps))
            max_index = int(np.argmax(overlaps))

        if max_overlap > iou_threshold and max_index >= 0:
            difficult = record["difficult"]
            detected = record["detected"]
            if not bool(difficult[max_index]):
                if not bool(detected[max_index]):
                    true_positive[detection_index] = 1.0
                    detected[max_index] = True
                else:
                    false_positive[detection_index] = 1.0
        else:
            false_positive[detection_index] = 1.0

    false_positive = np.cumsum(false_positive)
    true_positive = np.cumsum(true_positive)
    recall = true_positive / float(positive_count)
    precision = true_positive / np.maximum(
        true_positive + false_positive,
        np.finfo(np.float64).eps,
    )
    ap = voc_ap(recall, precision, use_07_metric=use_07_metric)
    return recall, precision, float(ap)


def voc_ap(rec: np.ndarray, prec: np.ndarray, *, use_07_metric: bool = False) -> float:
    """根据 VOC precision / recall 曲线计算 AP。"""

    if rec.size == 0 or prec.size == 0:
        return 0.0
    if use_07_metric:
        ap = 0.0
        for threshold in np.arange(0.0, 1.1, 0.1):
            if np.sum(rec >= threshold) == 0:
                precision_at_threshold = 0.0
            else:
                precision_at_threshold = float(np.max(prec[rec >= threshold]))
            ap += precision_at_threshold / 11.0
        return float(ap)

    recall = np.concatenate(([0.0], rec, [1.0]))
    precision = np.concatenate(([0.0], prec, [0.0]))
    for index in range(precision.size - 1, 0, -1):
        precision[index - 1] = np.maximum(precision[index - 1], precision[index])
    changed_indices = np.where(recall[1:] != recall[:-1])[0]
    return float(np.sum((recall[changed_indices + 1] - recall[changed_indices]) * precision[changed_indices + 1]))


def _build_voc_class_records(
    *,
    dataset: VocDetectionExportDataset,
    class_name: str,
) -> dict[int, dict[str, np.ndarray]]:
    """构建单类别 VOC ground truth 记录。"""

    records: dict[int, dict[str, np.ndarray]] = {}
    for sample in dataset.samples:
        boxes: list[tuple[float, float, float, float]] = []
        difficult: list[bool] = []
        for object_item in dataset.read_voc_objects(sample.annotation_file):
            if object_item.name != class_name:
                continue
            boxes.append(object_item.bbox_xyxy)
            difficult.append(object_item.difficult)
        records[sample.image_id] = {
            "bbox": np.array(boxes, dtype=np.float64),
            "difficult": np.array(difficult, dtype=bool),
            "detected": np.zeros(len(boxes), dtype=bool),
        }
    return records


def _filter_voc_class_detections(
    *,
    detections: list[dict[str, object]],
    class_index: int,
) -> list[tuple[int, float, np.ndarray]]:
    """筛选并规范化单类别 VOC detection 结果。"""

    class_detections: list[tuple[int, float, np.ndarray]] = []
    for detection in detections:
        if int(detection.get("category_id", -1)) != class_index:
            continue
        raw_bbox = detection.get("bbox")
        if not isinstance(raw_bbox, list | tuple) or len(raw_bbox) != 4:
            continue
        x, y, width, height = (float(value) for value in raw_bbox)
        if width <= 0.0 or height <= 0.0:
            continue
        class_detections.append(
            (
                int(detection.get("image_id", -1)),
                float(detection.get("score", 0.0)),
                np.array([x, y, x + width, y + height], dtype=np.float64),
            )
        )
    return class_detections


def _voc_inclusive_iou(box: np.ndarray, gt_boxes: np.ndarray) -> np.ndarray:
    """按 VOC inclusive 面积规则计算单框和多个 GT 框的 IoU。"""

    inter_x1 = np.maximum(gt_boxes[:, 0], box[0])
    inter_y1 = np.maximum(gt_boxes[:, 1], box[1])
    inter_x2 = np.minimum(gt_boxes[:, 2], box[2])
    inter_y2 = np.minimum(gt_boxes[:, 3], box[3])
    inter_width = np.maximum(inter_x2 - inter_x1 + 1.0, 0.0)
    inter_height = np.maximum(inter_y2 - inter_y1 + 1.0, 0.0)
    intersection = inter_width * inter_height
    box_area = (box[2] - box[0] + 1.0) * (box[3] - box[1] + 1.0)
    gt_area = (gt_boxes[:, 2] - gt_boxes[:, 0] + 1.0) * (gt_boxes[:, 3] - gt_boxes[:, 1] + 1.0)
    union = box_area + gt_area - intersection
    return intersection / np.maximum(union, np.finfo(np.float64).eps)


def _count_voc_ground_truth(*, dataset: VocDetectionExportDataset, class_name: str) -> int:
    """统计单类别非 difficult ground truth 数量。"""

    count = 0
    for sample in dataset.samples:
        for object_item in dataset.read_voc_objects(sample.annotation_file):
            if object_item.name == class_name and not object_item.difficult:
                count += 1
    return count


def _count_voc_detections(
    *,
    detections: list[dict[str, object]],
    class_index: int,
) -> int:
    """统计单类别 detection 数量。"""

    return sum(1 for detection in detections if int(detection.get("category_id", -1)) == class_index)


def _resolve_category_name(
    category_names: tuple[str, ...],
    class_index: int,
    fallback: str,
) -> str:
    """按类别顺序读取类别名，缺失时回退到 VOC 类别名。"""

    if class_index < len(category_names):
        return category_names[class_index]
    return fallback
