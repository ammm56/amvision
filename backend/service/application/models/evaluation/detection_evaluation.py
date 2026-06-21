"""统一 detection 数据集级评估执行模块。

适用于所有 detection 模型（yolox/yolov8/yolo11/yolo26/rfdetr），
通过 DefaultDetectionModelRuntime 加载推理会话，逐图推理并计算 mAP。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.tasks.detection_model_runtime import (
    DefaultDetectionModelRuntime,
)
from backend.service.application.runtime.contracts.detection import (
    DetectionPredictionRequest,
)
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class DetectionEvaluationRequest:
    """描述一次统一 detection 数据集级评估请求。"""

    dataset_storage: LocalDatasetStorage
    runtime_target: RuntimeTargetSnapshot
    manifest_payload: dict[str, object]
    score_threshold: float = 0.01
    nms_threshold: float = 0.65
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DetectionEvaluationResult:
    """描述一次统一 detection 评估结果。"""

    split_name: str
    sample_count: int
    duration_seconds: float
    map50: float
    map50_95: float
    mean_precision: float = 0.0
    mean_recall: float = 0.0
    mean_f1: float = 0.0
    per_class_metrics: list[dict[str, object]] = field(default_factory=list)
    report_payload: dict[str, object] = field(default_factory=dict)
    detections_payload: list[dict[str, object]] = field(default_factory=list)


def run_detection_evaluation(
    request: DetectionEvaluationRequest,
) -> DetectionEvaluationResult:
    """执行统一 detection 数据集级评估。

    通过 DefaultDetectionModelRuntime 加载推理会话，逐样本推理，
    用简化版 COCO-style AP 计算 mAP50 和 mAP50:95。
    """
    dataset_storage = request.dataset_storage
    manifest = request.manifest_payload
    runtime_target = request.runtime_target

    split_name, images, categories = _parse_detection_manifest(manifest, dataset_storage)
    if not images:
        return DetectionEvaluationResult(
            split_name=split_name, sample_count=0, duration_seconds=0.0,
            map50=0.0, map50_95=0.0,
        )

    label_names = tuple(str(c.get("name", c.get("id", ""))) for c in categories)

    runtime = DefaultDetectionModelRuntime()
    session = runtime.load_session(
        dataset_storage=dataset_storage,
        runtime_target=runtime_target,
    )

    started = time.monotonic()

    # 收集所有 GT 和预测结果
    all_gt: list[dict[str, Any]] = []
    all_pred: list[dict[str, Any]] = []
    predictions_out: list[dict[str, object]] = []

    for img_idx, img_info in enumerate(images):
        image_path = img_info["image_path"]
        gt_annotations = img_info.get("annotations", [])
        resolved = dataset_storage.resolve(image_path) if image_path else None
        if resolved is None or not resolved.is_file():
            continue

        # 记录 GT
        for ann in gt_annotations:
            bbox = ann.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4:
                x, y, w, h = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
                all_gt.append({
                    "image_id": img_idx,
                    "category_id": int(ann.get("category_id", 0)),
                    "bbox_xyxy": (x, y, x + w, y + h),
                    "area": w * h,
                })

        # 推理
        image_bytes = resolved.read_bytes()
        pred_request = DetectionPredictionRequest(
            score_threshold=request.score_threshold,
            save_result_image=False,
            input_image_bytes=image_bytes,
            extra_options={"nms_threshold": request.nms_threshold},
        )
        try:
            result = session.predict(pred_request)
        except Exception:
            continue

        for det in result.detections:
            all_pred.append({
                "image_id": img_idx,
                "category_id": det.class_id,
                "bbox_xyxy": det.bbox_xyxy,
                "score": det.score,
            })

        predictions_out.append({
            "image_index": img_idx,
            "image_path": str(image_path),
            "gt_count": len(gt_annotations),
            "pred_count": len(result.detections),
            "latency_ms": result.latency_ms,
        })

    duration = time.monotonic() - started
    total_images = len(predictions_out)

    # 计算 mAP
    iou_thresholds = [0.5 + 0.05 * i for i in range(10)]  # 0.5, 0.55, ..., 0.95
    all_class_ids = sorted(set(
        [g["category_id"] for g in all_gt] + [p["category_id"] for p in all_pred]
    ))

    ap_at_50_list: list[float] = []
    ap_at_all_list: list[float] = []
    precision_list: list[float] = []
    recall_list: list[float] = []
    per_class: list[dict[str, object]] = []

    for cat_id in all_class_ids:
        cat_gt = [g for g in all_gt if g["category_id"] == cat_id]
        cat_pred = sorted(
            [p for p in all_pred if p["category_id"] == cat_id],
            key=lambda x: x["score"],
            reverse=True,
        )
        if not cat_gt:
            continue

        cat_ap50 = _compute_ap(cat_gt, cat_pred, iou_threshold=0.5)
        cat_ap_all = [_compute_ap(cat_gt, cat_pred, iou_threshold=t) for t in iou_thresholds]
        cat_ap_mean = sum(cat_ap_all) / max(len(cat_ap_all), 1)

        # 计算单类别 precision/recall/F1（IoU=0.5）
        cat_metrics = _compute_precision_recall_f1(cat_gt, cat_pred, iou_threshold=0.5)
        cat_precision = cat_metrics["precision"]
        cat_recall = cat_metrics["recall"]
        cat_f1 = cat_metrics["f1"]

        ap_at_50_list.append(cat_ap50)
        ap_at_all_list.extend(cat_ap_all)
        precision_list.append(cat_precision)
        recall_list.append(cat_recall)

        name = label_names[cat_id] if 0 <= cat_id < len(label_names) else str(cat_id)
        per_class.append({
            "class_id": cat_id,
            "class_name": name,
            "gt_count": len(cat_gt),
            "pred_count": len(cat_pred),
            "ap50": round(cat_ap50, 6),
            "ap50_95": round(cat_ap_mean, 6),
            "precision": round(cat_precision, 6),
            "recall": round(cat_recall, 6),
            "f1": round(cat_f1, 6),
        })

    map50 = sum(ap_at_50_list) / max(len(ap_at_50_list), 1) if ap_at_50_list else 0.0
    map50_95 = sum(ap_at_all_list) / max(len(ap_at_all_list), 1) if ap_at_all_list else 0.0
    mean_precision = sum(precision_list) / max(len(precision_list), 1) if precision_list else 0.0
    mean_recall = sum(recall_list) / max(len(recall_list), 1) if recall_list else 0.0
    mean_f1 = (2 * mean_precision * mean_recall / (mean_precision + mean_recall)) if (mean_precision + mean_recall) > 0 else 0.0

    report = {
        "task_type": "detection",
        "model_type": runtime_target.model_type,
        "split_name": split_name,
        "sample_count": total_images,
        "duration_seconds": round(duration, 3),
        "map50": round(map50, 6),
        "map50_95": round(map50_95, 6),
        "mean_precision": round(mean_precision, 6),
        "mean_recall": round(mean_recall, 6),
        "mean_f1": round(mean_f1, 6),
        "score_threshold": request.score_threshold,
        "nms_threshold": request.nms_threshold,
        "per_class_metrics": per_class,
    }

    return DetectionEvaluationResult(
        split_name=split_name, sample_count=total_images, duration_seconds=duration,
        map50=map50, map50_95=map50_95,
        mean_precision=mean_precision, mean_recall=mean_recall, mean_f1=mean_f1,
        per_class_metrics=per_class, report_payload=report,
        detections_payload=predictions_out,
    )


def _parse_detection_manifest(
    manifest: dict[str, object],
    dataset_storage: LocalDatasetStorage,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """解析 detection manifest，返回 (split_name, images, categories)。"""
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
        raise InvalidRequestError("detection manifest 不包含可用的 split")

    split_name = str(chosen_split.get("name", "unknown"))
    image_root = str(chosen_split.get("image_root", "")).strip()
    annotation_file = str(chosen_split.get("annotation_file", "")).strip()
    label_root = str(chosen_split.get("label_root", "")).strip()
    if annotation_file:
        return _parse_coco_detection_split(
            dataset_storage=dataset_storage,
            split_name=split_name,
            image_root=image_root,
            annotation_file=annotation_file,
        )
    if label_root:
        return _parse_yolo_detection_split(
            dataset_storage=dataset_storage,
            split_name=split_name,
            image_root=image_root,
            label_root=label_root,
            category_names=manifest.get("category_names"),
        )
    return _parse_inline_detection_split(
        split_name=split_name,
        image_root=image_root,
        split_payload=chosen_split,
        categories_payload=manifest.get("categories"),
    )


def _parse_coco_detection_split(
    *,
    dataset_storage: LocalDatasetStorage,
    split_name: str,
    image_root: str,
    annotation_file: str,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """解析 COCO detection split。"""

    annotation_payload = dataset_storage.read_json(annotation_file)
    if not isinstance(annotation_payload, dict):
        raise InvalidRequestError(
            "detection annotation 文件格式无效",
            details={"annotation_file": annotation_file},
        )
    categories = _normalize_detection_categories(annotation_payload.get("categories"))
    images = _build_detection_images_from_annotation_payload(
        image_root=image_root,
        annotation_payload=annotation_payload,
    )
    return split_name, images, categories


def _parse_yolo_detection_split(
    *,
    dataset_storage: LocalDatasetStorage,
    split_name: str,
    image_root: str,
    label_root: str,
    category_names: object,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """解析 YOLO detection split。"""

    normalized_category_names = [
        normalized_name
        for item in (category_names if isinstance(category_names, list | tuple) else [])
        if (normalized_name := str(item).strip())
    ]
    categories = [
        {"id": category_index + 1, "name": category_name}
        for category_index, category_name in enumerate(normalized_category_names)
    ]
    resolved_image_root = dataset_storage.resolve(image_root)
    resolved_label_root = dataset_storage.resolve(label_root)
    if not resolved_image_root.is_dir():
        raise InvalidRequestError(
            "detection 图片目录不存在",
            details={"image_root": image_root, "split_name": split_name},
        )
    if not resolved_label_root.is_dir():
        raise InvalidRequestError(
            "detection 标签目录不存在",
            details={"label_root": label_root, "split_name": split_name},
        )
    images: list[dict[str, Any]] = []
    for image_id, image_path in enumerate(_iter_detection_image_files(resolved_image_root), start=1):
        image_width, image_height = _read_detection_image_size(image_path)
        relative_image_path = image_path.relative_to(resolved_image_root).as_posix()
        label_path = (resolved_label_root / relative_image_path).with_suffix(".txt")
        images.append(
            {
                "image_path": f"{image_root}/{relative_image_path}",
                "annotations": _parse_yolo_detection_annotations(
                    label_path=label_path,
                    image_id=image_id,
                    image_width=image_width,
                    image_height=image_height,
                ),
            }
        )
    return split_name, images, categories


def _parse_inline_detection_split(
    *,
    split_name: str,
    image_root: str,
    split_payload: dict[str, object],
    categories_payload: object,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """解析内嵌 images/annotations 的 detection split。"""

    categories = _normalize_detection_categories(categories_payload)
    images = _build_detection_images_from_annotation_payload(
        image_root=image_root,
        annotation_payload=split_payload,
    )
    return split_name, images, categories


def _normalize_detection_categories(categories_payload: object) -> list[dict[str, Any]]:
    """归一化 detection 类别列表。"""

    normalized_categories: list[dict[str, Any]] = []
    for category in categories_payload if isinstance(categories_payload, list) else ():
        if not isinstance(category, dict):
            continue
        category_id = category.get("id", category.get("category_id"))
        if not isinstance(category_id, int):
            continue
        normalized_categories.append(
            {
                "id": category_id,
                "name": str(category.get("name", category_id)),
            }
        )
    return normalized_categories


def _build_detection_images_from_annotation_payload(
    *,
    image_root: str,
    annotation_payload: dict[str, object],
) -> list[dict[str, Any]]:
    """把 COCO 风格 annotation payload 转成评估使用的图片列表。"""

    images_by_id: dict[int, str] = {}
    for img in (annotation_payload.get("images") or []):
        if isinstance(img, dict):
            images_by_id[int(img.get("id", -1))] = str(img.get("file_name", ""))

    anns_by_image: dict[int, list[dict[str, Any]]] = {}
    for ann in (annotation_payload.get("annotations") or []):
        if isinstance(ann, dict):
            img_id = int(ann.get("image_id", -1))
            anns_by_image.setdefault(img_id, []).append(ann)

    images: list[dict[str, Any]] = []
    for img_id, file_name in images_by_id.items():
        full_path = f"{image_root}/{file_name}" if image_root else file_name
        images.append(
            {
                "image_path": full_path,
                "annotations": anns_by_image.get(img_id, []),
            }
        )
    return images


def _iter_detection_image_files(image_root: Any) -> tuple[Any, ...]:
    """收集 detection split 下的全部图片文件。"""

    image_suffixes = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
    return tuple(
        sorted(
            (
                candidate
                for candidate in image_root.rglob("*")
                if candidate.is_file() and candidate.suffix.lower() in image_suffixes
            ),
            key=lambda item: item.as_posix().lower(),
        )
    )


def _read_detection_image_size(image_path: Any) -> tuple[int, int]:
    """读取 detection 图片尺寸。"""

    import cv2

    image = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise InvalidRequestError(
            "detection 图片无法读取",
            details={"image_path": str(image_path)},
        )
    return int(image.shape[1]), int(image.shape[0])


def _parse_yolo_detection_annotations(
    *,
    label_path: Any,
    image_id: int,
    image_width: int,
    image_height: int,
) -> list[dict[str, Any]]:
    """解析 YOLO detection 标签文件。"""

    if not label_path.is_file():
        return []
    annotations: list[dict[str, Any]] = []
    for raw_line in label_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            continue
        try:
            category_index = int(parts[0])
            x_center = float(parts[1])
            y_center = float(parts[2])
            box_width = float(parts[3])
            box_height = float(parts[4])
        except ValueError:
            continue
        x = max(0.0, (x_center - (box_width / 2.0)) * float(image_width))
        y = max(0.0, (y_center - (box_height / 2.0)) * float(image_height))
        w = max(0.0, box_width * float(image_width))
        h = max(0.0, box_height * float(image_height))
        if w <= 0.0 or h <= 0.0:
            continue
        annotations.append(
            {
                "image_id": image_id,
                "category_id": category_index + 1,
                "bbox": [x, y, w, h],
            }
        )
    return annotations


def _compute_ap(
    gt_list: list[dict],
    pred_list: list[dict],
    iou_threshold: float = 0.5,
) -> float:
    """计算单类别在指定 IoU 阈值下的 AP（101 点插值法）。

    遵循 COCO 评估标准：
    1. 按置信度降序排列预测
    2. 贪心匹配每个预测到 IoU 最高且未被匹配的 GT
    3. 构建 precision-recall 曲线
    4. 在 101 个等间距 recall 阈值 [0.00, 0.01, ..., 1.00] 上插值 precision
    5. AP = 插值 precision 的均值
    """
    if not gt_list:
        return 0.0
    if not pred_list:
        return 0.0

    # 按 image_id 分组 GT
    gt_by_image: dict[int, list[dict]] = {}
    for g in gt_list:
        gt_by_image.setdefault(g["image_id"], []).append(g)

    gt_id_counter = 0
    gt_id_map: dict[int, dict[int, int]] = {}
    for g in gt_list:
        img_id = g["image_id"]
        if img_id not in gt_id_map:
            gt_id_map[img_id] = {}
        gt_idx = len(gt_id_map[img_id])
        gt_id_map[img_id][gt_idx] = gt_id_counter
        gt_id_counter += 1

    total_gt = len(gt_list)
    matched_gt: set[int] = set()

    # 按 score 降序遍历预测，逐步构建 PR 曲线
    tp_cumsum: list[int] = []
    fp_cumsum: list[int] = []
    tp_count = 0
    fp_count = 0

    for pred in pred_list:
        img_id = pred["image_id"]
        img_gt = gt_by_image.get(img_id, [])
        best_iou = 0.0
        best_gt_idx = -1

        for gt_idx, gt in enumerate(img_gt):
            gid = gt_id_map[img_id][gt_idx]
            if gid in matched_gt:
                continue
            iou = _box_iou(pred["bbox_xyxy"], gt["bbox_xyxy"])
            if iou > best_iou:
                best_iou = iou
                best_gt_idx = gt_idx

        if best_iou >= iou_threshold and best_gt_idx >= 0:
            tp_count += 1
            gid = gt_id_map[img_id][best_gt_idx]
            matched_gt.add(gid)
        else:
            fp_count += 1

        tp_cumsum.append(tp_count)
        fp_cumsum.append(fp_count)

    if not tp_cumsum:
        return 0.0

    # 构建 precision-recall 曲线
    n_det = len(tp_cumsum)
    precisions: list[float] = []
    recalls: list[float] = []
    for i in range(n_det):
        precision_i = tp_cumsum[i] / max(tp_cumsum[i] + fp_cumsum[i], 1)
        recall_i = tp_cumsum[i] / max(total_gt, 1)
        precisions.append(precision_i)
        recalls.append(recall_i)

    # 101 点插值法（COCO 标准）
    # 对每个 recall 阈值 r，找到 recall >= r 的所有点中的最大 precision
    interpolated_precisions: list[float] = []
    for r_threshold_i in range(101):
        r_threshold = r_threshold_i / 100.0
        # 找到所有 recall >= r_threshold 的点中的最大 precision
        max_precision = 0.0
        for i in range(n_det):
            if recalls[i] >= r_threshold and precisions[i] > max_precision:
                max_precision = precisions[i]
        interpolated_precisions.append(max_precision)

    # AP = 101 个插值 precision 的均值
    return sum(interpolated_precisions) / 101.0


def _compute_precision_recall_f1(
    gt_list: list[dict],
    pred_list: list[dict],
    iou_threshold: float = 0.5,
) -> dict[str, float]:
    """计算单类别在指定 IoU 阈值下的 Precision、Recall、F1。

    参数：
    - gt_list: ground truth 列表，每个元素包含 image_id 和 bbox_xyxy
    - pred_list: 预测列表，每个元素包含 image_id、bbox_xyxy 和 score（已按 score 降序排列）
    - iou_threshold: IoU 匹配阈值

    返回：
    - dict 包含 precision、recall、f1 三个指标
    """
    if not gt_list:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    if not pred_list:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    # 按 image_id 分组 GT
    gt_by_image: dict[int, list[dict]] = {}
    for g in gt_list:
        gt_by_image.setdefault(g["image_id"], []).append(g)

    gt_id_counter = 0
    gt_id_map: dict[int, dict[int, int]] = {}
    for g in gt_list:
        img_id = g["image_id"]
        if img_id not in gt_id_map:
            gt_id_map[img_id] = {}
        gt_idx = len(gt_id_map[img_id])
        gt_id_map[img_id][gt_idx] = gt_id_counter
        gt_id_counter += 1

    total_gt = len(gt_list)
    matched_gt: set[int] = set()

    # 贪心匹配
    tp = 0
    fp = 0

    for pred in pred_list:
        img_id = pred["image_id"]
        img_gt = gt_by_image.get(img_id, [])
        best_iou = 0.0
        best_gt_idx = -1

        for gt_idx, gt in enumerate(img_gt):
            gid = gt_id_map[img_id][gt_idx]
            if gid in matched_gt:
                continue
            iou = _box_iou(pred["bbox_xyxy"], gt["bbox_xyxy"])
            if iou > best_iou:
                best_iou = iou
                best_gt_idx = gt_idx

        if best_iou >= iou_threshold and best_gt_idx >= 0:
            tp += 1
            gid = gt_id_map[img_id][best_gt_idx]
            matched_gt.add(gid)
        else:
            fp += 1

    fn = total_gt - tp
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {"precision": precision, "recall": recall, "f1": f1}


def _box_iou(box1: tuple, box2: tuple) -> float:
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
