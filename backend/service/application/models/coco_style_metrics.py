"""COCO-style 评估指标工具。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class CocoStyleMetricResult:
    """描述一组 COCO-style AP 指标。"""

    ap50: float
    ap50_95: float
    per_class_metrics: list[dict[str, object]] = field(default_factory=list)


SimilarityFunc = Callable[[dict[str, object], dict[str, object]], float]


def compute_coco_style_ap(
    *,
    gt_items: list[dict[str, object]],
    pred_items: list[dict[str, object]],
    category_names: dict[int, str] | None = None,
    iou_thresholds: tuple[float, ...] = (
        0.5,
        0.55,
        0.6,
        0.65,
        0.7,
        0.75,
        0.8,
        0.85,
        0.9,
        0.95,
    ),
    similarity_func: SimilarityFunc,
) -> CocoStyleMetricResult:
    """按类别计算 COCO-style AP。

    该函数只负责 AP 插值和匹配流程；bbox、mask、OKS 或 rotated IoU
    的具体相似度由调用方传入。
    """

    if not gt_items:
        return CocoStyleMetricResult(ap50=0.0, ap50_95=0.0)

    categories = sorted(
        {
            int(item["category_id"])
            for item in gt_items
            if "category_id" in item
        },
    )
    per_class_metrics: list[dict[str, object]] = []
    ap50_values: list[float] = []
    ap50_95_values: list[float] = []

    for category_id in categories:
        class_gt = [
            item for item in gt_items
            if int(item.get("category_id", -1)) == category_id
        ]
        class_pred = [
            item for item in pred_items
            if int(item.get("category_id", -1)) == category_id
        ]
        if not class_gt:
            continue

        threshold_aps = [
            _compute_ap_at_threshold(
                gt_items=class_gt,
                pred_items=class_pred,
                threshold=threshold,
                similarity_func=similarity_func,
            )
            for threshold in iou_thresholds
        ]
        ap50 = threshold_aps[0] if threshold_aps else 0.0
        ap50_95 = sum(threshold_aps) / max(len(threshold_aps), 1)
        ap50_values.append(ap50)
        ap50_95_values.append(ap50_95)
        per_class_metrics.append(
            {
                "category_id": category_id,
                "category_name": (category_names or {}).get(category_id, str(category_id)),
                "gt_count": len(class_gt),
                "pred_count": len(class_pred),
                "ap50": ap50,
                "ap50_95": ap50_95,
            },
        )

    return CocoStyleMetricResult(
        ap50=sum(ap50_values) / max(len(ap50_values), 1),
        ap50_95=sum(ap50_95_values) / max(len(ap50_95_values), 1),
        per_class_metrics=per_class_metrics,
    )


def _compute_ap_at_threshold(
    *,
    gt_items: list[dict[str, object]],
    pred_items: list[dict[str, object]],
    threshold: float,
    similarity_func: SimilarityFunc,
) -> float:
    """计算单类别、单阈值下的 101 点插值 AP。"""

    if not gt_items or not pred_items:
        return 0.0

    gt_by_image: dict[int, list[tuple[int, dict[str, object]]]] = {}
    for global_gt_index, gt_item in enumerate(gt_items):
        image_id = int(gt_item.get("image_id", -1))
        gt_by_image.setdefault(image_id, []).append((global_gt_index, gt_item))

    matched_gt: set[int] = set()
    true_positives: list[int] = []
    false_positives: list[int] = []
    tp_count = 0
    fp_count = 0

    sorted_predictions = sorted(
        pred_items,
        key=lambda item: float(item.get("score", 0.0)),
        reverse=True,
    )
    for pred_item in sorted_predictions:
        image_id = int(pred_item.get("image_id", -1))
        best_score = 0.0
        best_gt_index = -1
        for global_gt_index, gt_item in gt_by_image.get(image_id, []):
            if global_gt_index in matched_gt:
                continue
            score = similarity_func(pred_item, gt_item)
            if score > best_score:
                best_score = score
                best_gt_index = global_gt_index
        if best_score >= threshold and best_gt_index >= 0:
            tp_count += 1
            matched_gt.add(best_gt_index)
        else:
            fp_count += 1
        true_positives.append(tp_count)
        false_positives.append(fp_count)

    if not true_positives:
        return 0.0

    precisions: list[float] = []
    recalls: list[float] = []
    for tp_value, fp_value in zip(true_positives, false_positives, strict=True):
        precisions.append(tp_value / max(tp_value + fp_value, 1))
        recalls.append(tp_value / max(len(gt_items), 1))

    interpolated: list[float] = []
    for index in range(101):
        recall_threshold = index / 100.0
        best_precision = 0.0
        for precision, recall in zip(precisions, recalls, strict=True):
            if recall >= recall_threshold and precision > best_precision:
                best_precision = precision
        interpolated.append(best_precision)
    return sum(interpolated) / 101.0


def bbox_iou_xyxy(
    box1: tuple[float, float, float, float] | list[float],
    box2: tuple[float, float, float, float] | list[float],
) -> float:
    """计算两个 xyxy bbox 的 IoU。"""

    x1 = max(float(box1[0]), float(box2[0]))
    y1 = max(float(box1[1]), float(box2[1]))
    x2 = min(float(box1[2]), float(box2[2]))
    y2 = min(float(box1[3]), float(box2[3]))
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area1 = max(0.0, float(box1[2]) - float(box1[0])) * max(0.0, float(box1[3]) - float(box1[1]))
    area2 = max(0.0, float(box2[2]) - float(box2[0])) * max(0.0, float(box2[3]) - float(box2[1]))
    return intersection / max(area1 + area2 - intersection, 1e-8)
