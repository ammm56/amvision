"""Pose 数据集级评估执行模块。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_dataset_manifest_support import (
    build_coco_payload_from_yolo_pose_split,
    normalize_yolo_category_names,
)
from backend.service.application.runtime.pose_model_runtime import DefaultPoseModelRuntime
from backend.service.application.runtime.pose_runtime_contracts import PosePredictionRequest
from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class PoseEvaluationRequest:
    """描述一次 pose 数据集级评估请求。"""

    dataset_storage: LocalDatasetStorage
    runtime_target: RuntimeTargetSnapshot
    manifest_payload: dict[str, object]
    score_threshold: float = 0.01
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PoseEvaluationResult:
    """Pose 评估结果。"""
    sample_count: int
    oks_ap50: float
    oks_ap50_95: float
    duration_seconds: float
    report_object_key: str
    per_class_metrics: list[dict] = field(default_factory=list)
    predictions_payload: list[dict] = field(default_factory=list)


def run_pose_evaluation(request: PoseEvaluationRequest) -> PoseEvaluationResult:
    """执行 Pose 数据集级评估（简化版 OKS AP 计算）。"""
    dataset_storage = request.dataset_storage
    manifest = request.manifest_payload
    score_threshold = request.score_threshold
    output_prefix = f"task-runs/evaluation/{request.runtime_target.model_version_id}"

    model_runtime = DefaultPoseModelRuntime()

    started_at = datetime.now(timezone.utc)

    _, samples, categories = _parse_pose_manifest(manifest, dataset_storage)

    # 收集预测
    all_preds: list[dict] = []
    all_gts: list[dict] = []
    processed_count = 0

    for image_index, sample in enumerate(samples):
        image_path = str(sample.get("image_path", "")).strip()
        gt_anns = sample.get("annotations", [])
        if not isinstance(gt_anns, list):
            gt_anns = []
        resolved = dataset_storage.resolve(image_path) if image_path else None
        if not resolved or not resolved.is_file():
            continue

        image_bytes = resolved.read_bytes()
        pred_request = PosePredictionRequest(
            score_threshold=score_threshold,
            save_result_image=False,
            input_image_bytes=image_bytes,
        )

        try:
            result = model_runtime.predict(pred_request)
        except Exception:
            continue

        processed_count += 1

        # 收集 GT keypoints
        for gt_ann in gt_anns:
            if not isinstance(gt_ann, dict):
                continue
            kpts = gt_ann.get("keypoints", [])
            if kpts:
                all_gts.append({
                    "image_id": image_index,
                    "category_id": gt_ann.get("category_id", 0),
                    "keypoints": kpts,
                    "num_keypoints": gt_ann.get("num_keypoints", len(kpts) // 3),
                })

        # 收集预测 keypoints
        for det in result.detections:
            all_preds.append({
                "image_id": image_index,
                "category_id": det.class_id,
                "keypoints": det.keypoints,
                "score": det.score,
            })

    # 简化版 OKS AP 计算（按类别）
    per_class_metrics = []
    all_ap50 = []
    all_ap50_95 = []

    for cat in categories:
        cat_id = int(cat.get("id", 0))
        cat_name = str(cat.get("name", cat_id))
        cat_gts = [g for g in all_gts if g["category_id"] == cat_id]
        cat_preds = [p for p in all_preds if p["category_id"] == cat_id]

        if not cat_gts:
            continue

        # 简化 AP 计算（使用关键点匹配）
        ap50, ap50_95 = _compute_keypoint_ap(cat_gts, cat_preds)
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

    oks_ap50 = sum(all_ap50) / max(len(all_ap50), 1)
    oks_ap50_95 = sum(all_ap50_95) / max(len(all_ap50_95), 1)

    finished_at = datetime.now(timezone.utc)
    duration = (finished_at - started_at).total_seconds()

    # 写报告
    report_key = f"{output_prefix}/reports/pose_evaluation.json"
    report = {
        "sample_count": processed_count,
        "oks_ap50": oks_ap50,
        "oks_ap50_95": oks_ap50_95,
        "duration_seconds": duration,
        "per_class_metrics": per_class_metrics,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
    }
    dataset_storage.write_json(report_key, report)

    return PoseEvaluationResult(
        sample_count=processed_count,
        oks_ap50=oks_ap50,
        oks_ap50_95=oks_ap50_95,
        duration_seconds=duration,
        report_object_key=report_key,
        per_class_metrics=per_class_metrics,
        predictions_payload=all_preds,
    )


def _parse_pose_manifest(
    manifest: dict[str, object],
    dataset_storage: LocalDatasetStorage,
) -> tuple[str, list[dict[str, object]], list[dict[str, Any]]]:
    """解析 pose export manifest。"""

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
        chosen_split = next((split for split in splits if isinstance(split, dict)), None)
    if chosen_split is None:
        raise InvalidRequestError("pose manifest 不包含可用的 split")

    split_name = str(chosen_split.get("name", "unknown"))
    image_root = str(chosen_split.get("image_root", "")).strip()
    annotation_file = str(chosen_split.get("annotation_file", "")).strip()
    label_root = str(chosen_split.get("label_root", "")).strip()
    if annotation_file:
        annotation_payload = dataset_storage.read_json(annotation_file)
        if not isinstance(annotation_payload, dict):
            raise InvalidRequestError(
                "pose annotation 文件格式无效",
                details={"annotation_file": annotation_file},
            )
        categories = _normalize_pose_categories(annotation_payload.get("categories"))
        return split_name, _build_pose_samples(image_root=image_root, payload=annotation_payload), categories
    if label_root:
        category_names = normalize_yolo_category_names(
            category_names=manifest.get("category_names"),
            format_label="YOLO pose",
        )
        image_root_path = dataset_storage.resolve(image_root)
        label_root_path = dataset_storage.resolve(label_root)
        if not image_root_path.is_dir():
            raise InvalidRequestError(
                "pose 图片目录不存在",
                details={"image_root": image_root, "split_name": split_name},
            )
        if not label_root_path.is_dir():
            raise InvalidRequestError(
                "pose 标签目录不存在",
                details={"label_root": label_root, "split_name": split_name},
            )
        payload = build_coco_payload_from_yolo_pose_split(
            split_name=split_name,
            image_root=image_root_path,
            label_root=label_root_path,
            category_names=category_names,
        )
        categories = _normalize_pose_categories(payload.get("categories"))
        return split_name, _build_pose_samples(image_root=image_root, payload=payload), categories
    categories = _normalize_pose_categories(manifest.get("categories"))
    return split_name, _build_pose_samples(image_root=image_root, payload=chosen_split), categories


def _build_pose_samples(
    *,
    image_root: str,
    payload: dict[str, object],
) -> list[dict[str, object]]:
    """把 COCO 风格 pose 标注组装成按图片分组的样本列表。"""

    images_by_id: dict[int, str] = {}
    for image in (payload.get("images") or []):
        if not isinstance(image, dict):
            continue
        image_id = image.get("id")
        file_name = str(image.get("file_name", "")).strip()
        if not isinstance(image_id, int) or not file_name:
            continue
        images_by_id[image_id] = file_name

    anns_by_image: dict[int, list[dict[str, object]]] = {}
    for ann in (payload.get("annotations") or []):
        if not isinstance(ann, dict):
            continue
        image_id = ann.get("image_id")
        if not isinstance(image_id, int):
            continue
        anns_by_image.setdefault(image_id, []).append(ann)

    samples: list[dict[str, object]] = []
    for image_id, file_name in images_by_id.items():
        full_path = f"{image_root}/{file_name}" if image_root else file_name
        samples.append(
            {
                "image_path": full_path,
                "annotations": anns_by_image.get(image_id, []),
            }
        )
    return samples


def _normalize_pose_categories(categories_payload: object) -> list[dict[str, Any]]:
    """归一化 pose 类别列表。"""

    categories: list[dict[str, Any]] = []
    for category in categories_payload if isinstance(categories_payload, list) else ():
        if not isinstance(category, dict):
            continue
        category_id = category.get("id", category.get("category_id"))
        if not isinstance(category_id, int):
            continue
        categories.append({"id": category_id, "name": str(category.get("name", category_id))})
    return categories


def _compute_keypoint_ap(gts: list[dict], preds: list[dict], sigma: float = 0.05) -> tuple[float, float]:
    """简化版关键点 AP 计算。"""
    if not gts or not preds:
        return 0.0, 0.0

    # 按 score 降序排列预测
    preds_sorted = sorted(preds, key=lambda p: p["score"], reverse=True)

    tp50 = 0
    tp50_95 = 0
    matched_gts = set()

    for pred in preds_sorted:
        best_oks = 0.0
        best_gt_idx = -1

        for gt_idx, gt in enumerate(gts):
            if gt_idx in matched_gts:
                continue
            if gt["image_id"] != pred["image_id"]:
                continue

            oks = _compute_oks(gt["keypoints"], pred["keypoints"], sigma)
            if oks > best_oks:
                best_oks = oks
                best_gt_idx = gt_idx

        if best_oks >= 0.5:
            tp50 += 1
            matched_gts.add(best_gt_idx)
        if best_oks >= 0.5 and best_oks < 0.95:
            tp50_95 += 1
        elif best_oks >= 0.95:
            tp50_95 += 1

    precision50 = tp50 / max(len(preds_sorted), 1)
    recall50 = tp50 / max(len(gts), 1)
    ap50 = precision50 * recall50

    precision50_95 = tp50_95 / max(len(preds_sorted), 1)
    recall50_95 = tp50_95 / max(len(gts), 1)
    ap50_95 = precision50_95 * recall50_95

    return ap50, ap50_95


def _compute_oks(gt_kpts: list[float], pred_kpts: list[float], sigma: float = 0.05) -> float:
    """计算 Object Keypoint Similarity。"""
    if not gt_kpts or not pred_kpts:
        return 0.0

    # 确保长度一致
    num_kpts = min(len(gt_kpts) // 3, len(pred_kpts) // 3)
    if num_kpts == 0:
        return 0.0

    sum_dist_sq = 0.0
    visible_count = 0

    for i in range(num_kpts):
        gt_x = gt_kpts[i * 3]
        gt_y = gt_kpts[i * 3 + 1]
        gt_v = gt_kpts[i * 3 + 2]

        pred_x = pred_kpts[i * 3]
        pred_y = pred_kpts[i * 3 + 1]
        pred_v = pred_kpts[i * 3 + 2]

        if gt_v > 0 and pred_v > 0:
            dx = gt_x - pred_x
            dy = gt_y - pred_y
            dist_sq = dx * dx + dy * dy
            sum_dist_sq += dist_sq / (sigma * sigma)
            visible_count += 1

    if visible_count == 0:
        return 0.0

    import math
    oks = math.exp(-sum_dist_sq / (2.0 * visible_count))
    return oks
