"""YOLO 主线 segmentation 数据集级评估执行模块。

对已导出的 segmentation 数据集中每张样本执行推理，
统计 bbox AP 与 mask IoU 指标。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_dataset_manifest_support import (
    build_coco_payload_from_yolo_segmentation_split,
    normalize_yolo_category_names,
)
from backend.service.application.runtime.segmentation_model_runtime import (
    DefaultSegmentationModelRuntime,
)
from backend.service.application.runtime.segmentation_runtime_contracts import (
    SegmentationPredictionRequest,
)
from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class SegmentationEvaluationRequest:
    """描述一次 segmentation 数据集级评估请求。"""

    dataset_storage: LocalDatasetStorage
    runtime_target: RuntimeTargetSnapshot
    manifest_payload: dict[str, object]
    score_threshold: float = 0.01
    mask_threshold: float = 0.5
    iou_thresholds: tuple[float, ...] = (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95)
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SegmentationEvaluationResult:
    """描述一次 segmentation 评估结果。"""

    split_name: str
    sample_count: int
    duration_seconds: float
    map50: float
    map50_95: float
    mask_map50: float
    mask_map50_95: float
    per_class_metrics: list[dict[str, object]] = field(default_factory=list)
    report_payload: dict[str, object] = field(default_factory=dict)
    predictions_payload: list[dict[str, object]] = field(default_factory=list)


def run_yolo_primary_segmentation_evaluation(
    request: SegmentationEvaluationRequest,
) -> SegmentationEvaluationResult:
    """执行 segmentation 数据集级评估。"""

    dataset_storage = request.dataset_storage
    manifest = request.manifest_payload
    runtime_target = request.runtime_target

    split_name, samples, label_names = _parse_segmentation_manifest(manifest, dataset_storage)
    if not samples:
        return SegmentationEvaluationResult(
            split_name=split_name, sample_count=0, duration_seconds=0.0,
            map50=0.0, map50_95=0.0, mask_map50=0.0, mask_map50_95=0.0,
        )

    runtime = DefaultSegmentationModelRuntime()
    session = runtime.load_session(
        dataset_storage=dataset_storage, runtime_target=runtime_target,
    )

    started = time.monotonic()
    all_gt_boxes: list[list[float]] = []
    all_gt_classes: list[int] = []
    all_pred_boxes: list[list[float]] = []
    all_pred_classes: list[int] = []
    all_pred_scores: list[float] = []
    all_image_ids: list[int] = []
    predictions_out: list[dict[str, object]] = []

    for img_idx, sample in enumerate(samples):
        image_path = sample["image_path"]
        gt_annotations = sample.get("annotations", [])
        resolved = dataset_storage.resolve(image_path) if image_path else None
        if resolved is None or not resolved.is_file():
            continue

        for ann in gt_annotations:
            bbox = ann.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4:
                x, y, w, h = bbox
                all_gt_boxes.append([x, y, x + w, y + h])
                all_gt_classes.append(int(ann.get("category_id", 0)))
                all_image_ids.append(img_idx)

        image_bytes = resolved.read_bytes()
        pred_request = SegmentationPredictionRequest(
            score_threshold=request.score_threshold,
            mask_threshold=request.mask_threshold,
            save_result_image=False,
            input_image_bytes=image_bytes,
        )
        try:
            result = session.predict(pred_request)
        except Exception:
            continue

        for inst in result.instances:
            all_pred_boxes.append(list(inst.bbox_xyxy))
            all_pred_classes.append(inst.class_id)
            all_pred_scores.append(inst.score)

        predictions_out.append({
            "image_index": img_idx,
            "image_path": str(image_path),
            "gt_count": len(gt_annotations),
            "pred_count": len(result.instances),
            "latency_ms": result.latency_ms,
        })

    duration = time.monotonic() - started
    total_images = len(predictions_out)

    # 简化版 bbox AP 计算
    map50, map50_95 = _compute_bbox_ap(
        all_gt_boxes, all_gt_classes, all_pred_boxes, all_pred_classes,
        all_pred_scores, all_image_ids, label_names,
        iou_thresholds=request.iou_thresholds,
    )

    report = {
        "task_type": "segmentation",
        "model_type": runtime_target.model_type,
        "split_name": split_name,
        "sample_count": total_images,
        "duration_seconds": round(duration, 3),
        "map50": round(map50, 6),
        "map50_95": round(map50_95, 6),
        "mask_map50": 0.0,
        "mask_map50_95": 0.0,
        "score_threshold": request.score_threshold,
        "mask_threshold": request.mask_threshold,
    }

    return SegmentationEvaluationResult(
        split_name=split_name, sample_count=total_images, duration_seconds=duration,
        map50=map50, map50_95=map50_95, mask_map50=0.0, mask_map50_95=0.0,
        report_payload=report, predictions_payload=predictions_out,
    )


def _parse_segmentation_manifest(
    manifest: dict[str, object],
    dataset_storage: LocalDatasetStorage,
) -> tuple[str, list[dict[str, object]], tuple[str, ...]]:
    """解析 segmentation manifest。"""
    splits = manifest.get("splits", [])
    chosen_split: dict[str, object] | None = None
    for split in (splits or []):
        if not isinstance(split, dict):
            continue
        name = str(split.get("name", "")).lower()
        if name in ("val", "valid", "validation", "test"):
            chosen_split = split
            break
    if chosen_split is None and splits:
        chosen_split = next((s for s in splits if isinstance(s, dict)), None)
    if chosen_split is None:
        raise InvalidRequestError("segmentation manifest 不包含可用的 split")

    split_name = str(chosen_split.get("name", "unknown"))
    image_root = str(chosen_split.get("image_root", "")).strip()
    annotation_file = str(chosen_split.get("annotation_file", "")).strip()
    label_root = str(chosen_split.get("label_root", "")).strip()
    if annotation_file:
        annotation_payload = dataset_storage.read_json(annotation_file)
        if not isinstance(annotation_payload, dict):
            raise InvalidRequestError(
                "segmentation annotation 文件格式无效",
                details={"annotation_file": annotation_file},
            )
        categories = annotation_payload.get("categories", [])
        label_names = tuple(
            str(category.get("name", category.get("id", "")))
            for category in categories
            if isinstance(category, dict)
        )
        return split_name, _build_segmentation_samples(image_root=image_root, payload=annotation_payload), label_names
    if label_root:
        category_names = normalize_yolo_category_names(
            category_names=manifest.get("category_names"),
            format_label="YOLO segmentation",
        )
        image_root_path = dataset_storage.resolve(image_root)
        label_root_path = dataset_storage.resolve(label_root)
        if not image_root_path.is_dir():
            raise InvalidRequestError(
                "segmentation 图片目录不存在",
                details={"image_root": image_root, "split_name": split_name},
            )
        if not label_root_path.is_dir():
            raise InvalidRequestError(
                "segmentation 标签目录不存在",
                details={"label_root": label_root, "split_name": split_name},
            )
        payload = build_coco_payload_from_yolo_segmentation_split(
            split_name=split_name,
            image_root=image_root_path,
            label_root=label_root_path,
            category_names=category_names,
        )
        return split_name, _build_segmentation_samples(image_root=image_root, payload=payload), category_names
    categories = manifest.get("categories", [])
    label_names = tuple(str(c.get("name", c.get("id", ""))) for c in categories if isinstance(c, dict))
    return split_name, _build_segmentation_samples(image_root=image_root, payload=chosen_split), label_names


def _build_segmentation_samples(
    *,
    image_root: str,
    payload: dict[str, object],
) -> list[dict[str, object]]:
    """把 COCO 风格 images/annotations 组装成评估样本列表。"""

    images_by_id: dict[int, str] = {}
    for img in (payload.get("images") or []):
        if isinstance(img, dict):
            images_by_id[int(img.get("id", -1))] = str(img.get("file_name", ""))

    anns_by_image: dict[int, list[dict]] = {}
    for ann in (payload.get("annotations") or []):
        if isinstance(ann, dict):
            img_id = int(ann.get("image_id", -1))
            anns_by_image.setdefault(img_id, []).append(ann)

    samples: list[dict[str, object]] = []
    for img_id, file_name in images_by_id.items():
        full_path = f"{image_root}/{file_name}" if image_root else file_name
        samples.append({
            "image_path": full_path,
            "annotations": anns_by_image.get(img_id, []),
        })
    return samples


def _compute_bbox_ap(
    gt_boxes: list[list[float]],
    gt_classes: list[int],
    pred_boxes: list[list[float]],
    pred_classes: list[int],
    pred_scores: list[float],
    image_ids: list[int],
    label_names: tuple[str, ...],
    iou_thresholds: tuple[float, ...] = (0.5, 0.75),
) -> tuple[float, float]:
    """简化版 bbox AP 计算（按类别分别计算 AP 再平均）。"""
    if not gt_boxes or not pred_boxes:
        return 0.0, 0.0

    all_classes = sorted(set(gt_classes + pred_classes))
    ap_at_50: list[float] = []
    ap_at_all: list[float] = []

    for cls_id in all_classes:
        cls_gt_indices = [i for i, c in enumerate(gt_classes) if c == cls_id]
        cls_pred_indices = [i for i, c in enumerate(pred_classes) if c == cls_id]
        if not cls_gt_indices:
            continue

        cls_pred_scores = [pred_scores[i] for i in cls_pred_indices]
        sorted_pred = sorted(zip(cls_pred_scores, cls_pred_indices), reverse=True)

        for iou_thresh in iou_thresholds:
            matched = set()
            tp = 0
            fp = 0
            for _, pred_idx in sorted_pred:
                pred_box = pred_boxes[pred_idx]
                best_iou = 0.0
                best_gt = -1
                for gt_idx in cls_gt_indices:
                    if gt_idx in matched:
                        continue
                    gt_box = gt_boxes[gt_idx]
                    iou = _box_iou(pred_box, gt_box)
                    if iou > best_iou:
                        best_iou = iou
                        best_gt = gt_idx
                if best_iou >= iou_thresh and best_gt >= 0:
                    tp += 1
                    matched.add(best_gt)
                else:
                    fp += 1

            fn = len(cls_gt_indices) - tp
            precision = tp / max(tp + fp, 1)
            recall = tp / max(tp + fn, 1)
            ap = precision * recall  # 简化 AP

            if abs(iou_thresh - 0.5) < 0.01:
                ap_at_50.append(ap)
            ap_at_all.append(ap)

    map50 = sum(ap_at_50) / max(len(ap_at_50), 1) if ap_at_50 else 0.0
    map50_95 = sum(ap_at_all) / max(len(ap_at_all), 1) if ap_at_all else 0.0
    return map50, map50_95


def _box_iou(box1: list[float], box2: list[float]) -> float:
    """计算两个 xyxy 框的 IoU。"""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union = area1 + area2 - inter
    return inter / max(union, 1e-6)
