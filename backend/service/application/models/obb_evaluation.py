"""OBB 数据集级评估执行模块。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.service.application.runtime.obb_model_runtime import DefaultObbModelRuntime
from backend.service.application.runtime.obb_runtime_contracts import ObbPredictionRequest
from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class ObbEvaluationRequest:
    """描述一次 obb 数据集级评估请求。"""

    dataset_storage: LocalDatasetStorage
    runtime_target: RuntimeTargetSnapshot
    manifest_payload: dict[str, object]
    score_threshold: float = 0.01
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ObbEvaluationResult:
    """OBB 评估结果。"""
    sample_count: int
    map50: float
    map50_95: float
    duration_seconds: float
    report_object_key: str
    per_class_metrics: list[dict] = field(default_factory=list)
    predictions_payload: list[dict] = field(default_factory=list)


def run_obb_evaluation(request: ObbEvaluationRequest) -> ObbEvaluationResult:
    """执行 OBB 数据集级评估（旋转框 AP 计算）。"""
    dataset_storage = request.dataset_storage
    manifest = request.manifest_payload
    score_threshold = request.score_threshold
    output_prefix = f"task-runs/evaluation/{request.runtime_target.model_version_id}"

    # 加载模型运行时
    from backend.service.application.runtime.obb_model_runtime import DefaultObbModelRuntime
    model_runtime = DefaultObbModelRuntime()

    started_at = datetime.now(timezone.utc)

    # 解析 manifest
    images = {img["id"]: img for img in manifest.get("images", [])}
    annotations = manifest.get("annotations", [])
    categories = manifest.get("categories", [])

    # 按 image_id 分组 GT
    gt_by_image: dict[int, list[dict]] = {}
    for ann in annotations:
        img_id = ann["image_id"]
        gt_by_image.setdefault(img_id, []).append(ann)

    # 收集预测
    all_preds: list[dict] = []
    processed_count = 0

    for img_id, gt_anns in gt_by_image.items():
        img_info = images.get(img_id)
        if not img_info:
            continue
        image_path = img_info.get("file_name", "")
        resolved = dataset_storage.resolve(image_path)
        if not resolved or not resolved.is_file():
            continue

        image_bytes = resolved.read_bytes()
        pred_request = ObbPredictionRequest(
            score_threshold=score_threshold,
            save_result_image=False,
            input_image_bytes=image_bytes,
        )

        try:
            result = model_runtime.predict(pred_request)
        except Exception:
            continue

        processed_count += 1

        # 收集预测
        for det in result.detections:
            all_preds.append({
                "image_id": img_id,
                "category_id": det.class_id,
                "bbox": det.bbox,  # OBB: [x, y, w, h, angle]
                "score": det.score,
            })

    # 计算 AP
    per_class_metrics = []
    all_ap50 = []
    all_ap50_95 = []

    for cat in categories:
        cat_id = cat["id"]
        cat_name = cat["name"]
        cat_gts = [a for a in annotations if a["category_id"] == cat_id]
        cat_preds = [p for p in all_preds if p["category_id"] == cat_id]

        if not cat_gts:
            continue

        ap50, ap50_95 = _compute_obb_ap(cat_gts, cat_preds)
        all_ap50.append(ap50)
        all_ap50_95.append(ap50_95)

        per_class_metrics.append({
            "category_id": cat_id,
            "category_name": cat_name,
            "gt_count": len(cat_gts),
            "pred_count": len(cat_preds),
            "ap50": ap50,
            "ap50_95": ap50_95,
        })

    map50 = sum(all_ap50) / max(len(all_ap50), 1)
    map50_95 = sum(all_ap50_95) / max(len(all_ap50_95), 1)

    finished_at = datetime.now(timezone.utc)
    duration = (finished_at - started_at).total_seconds()

    # 写报告
    report_key = f"{output_prefix}/reports/obb_evaluation.json"
    report = {
        "sample_count": processed_count,
        "map50": map50,
        "map50_95": map50_95,
        "duration_seconds": duration,
        "per_class_metrics": per_class_metrics,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
    }
    dataset_storage.write_json(report_key, report)

    return ObbEvaluationResult(
        sample_count=processed_count,
        map50=map50,
        map50_95=map50_95,
        duration_seconds=duration,
        report_object_key=report_key,
        per_class_metrics=per_class_metrics,
        predictions_payload=all_preds,
    )


def _compute_obb_ap(gts: list[dict], preds: list[dict]) -> tuple[float, float]:
    """计算旋转框 AP（简化版）。"""
    if not gts or not preds:
        return 0.0, 0.0

    # 按 score 降序排列
    preds_sorted = sorted(preds, key=lambda p: p["score"], reverse=True)

    tp50 = 0
    tp50_95 = 0
    matched_gts = set()

    for pred in preds_sorted:
        best_iou = 0.0
        best_gt_idx = -1

        for gt_idx, gt in enumerate(gts):
            if gt_idx in matched_gts:
                continue
            if gt["image_id"] != pred["image_id"]:
                continue

            iou = _compute_obb_iou(gt["bbox"], pred["bbox"])
            if iou > best_iou:
                best_iou = iou
                best_gt_idx = gt_idx

        if best_iou >= 0.5:
            tp50 += 1
            matched_gts.add(best_gt_idx)
        if best_iou >= 0.5 and best_iou < 0.95:
            tp50_95 += 1
        elif best_iou >= 0.95:
            tp50_95 += 1

    precision50 = tp50 / max(len(preds_sorted), 1)
    recall50 = tp50 / max(len(gts), 1)
    ap50 = precision50 * recall50

    precision50_95 = tp50_95 / max(len(preds_sorted), 1)
    recall50_95 = tp50_95 / max(len(gts), 1)
    ap50_95 = precision50_95 * recall50_95

    return ap50, ap50_95


def _compute_obb_iou(obb1: list[float], obb2: list[float]) -> float:
    """计算两个旋转框的 IoU（简化版：使用轴对齐近似）。"""
    if len(obb1) < 4 or len(obb2) < 4:
        return 0.0

    # 简化：忽略旋转角度，使用轴对齐框计算
    x1, y1, w1, h1 = obb1[:4]
    x2, y2, w2, h2 = obb2[:4]

    # 转换为 xyxy 格式
    left1, top1, right1, bottom1 = x1 - w1/2, y1 - h1/2, x1 + w1/2, y1 + h1/2
    left2, top2, right2, bottom2 = x2 - w2/2, y2 - h2/2, x2 + w2/2, y2 + h2/2

    # 计算交集
    inter_left = max(left1, left2)
    inter_top = max(top1, top2)
    inter_right = min(right1, right2)
    inter_bottom = min(bottom1, bottom2)

    inter_w = max(0, inter_right - inter_left)
    inter_h = max(0, inter_bottom - inter_top)
    inter_area = inter_w * inter_h

    # 计算并集
    area1 = w1 * h1
    area2 = w2 * h2
    union_area = area1 + area2 - inter_area

    if union_area <= 0:
        return 0.0

    return inter_area / union_area
