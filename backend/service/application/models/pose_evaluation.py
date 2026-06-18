"""Pose 数据集级评估执行模块。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.coco_style_metrics import compute_coco_style_ap
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
    oks_thresholds: tuple[float, ...] = (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95)
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
    report_payload: dict[str, object] = field(default_factory=dict)


def run_pose_evaluation(request: PoseEvaluationRequest) -> PoseEvaluationResult:
    """执行 Pose 数据集级评估（简化版 OKS AP 计算）。"""
    dataset_storage = request.dataset_storage
    manifest = request.manifest_payload
    score_threshold = request.score_threshold
    output_prefix = f"task-runs/evaluation/{request.runtime_target.model_version_id}"

    model_runtime = DefaultPoseModelRuntime()
    session = model_runtime.load_session(
        dataset_storage=dataset_storage,
        runtime_target=request.runtime_target,
    )

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
            keypoint_confidence_threshold=_resolve_keypoint_confidence_threshold(
                request.extra_options,
            ),
            save_result_image=False,
            input_image_bytes=image_bytes,
        )

        try:
            result = session.predict(pred_request)
        except Exception:
            continue

        processed_count += 1

        # 收集 GT keypoints
        for gt_ann in gt_anns:
            if not isinstance(gt_ann, dict):
                continue
            kpts = gt_ann.get("keypoints", [])
            if kpts:
                all_gts.append(
                    {
                        "image_id": image_index,
                        "category_id": gt_ann.get("category_id", 0),
                        "keypoints": kpts,
                        "num_keypoints": gt_ann.get("num_keypoints", len(kpts) // 3),
                        "area": _resolve_pose_annotation_area(gt_ann),
                    },
                )

        # 收集预测 keypoints
        for det in _iter_pose_prediction_instances(result):
            all_preds.append({
                "image_id": image_index,
                "category_id": det.class_id,
                "keypoints": _flatten_pose_keypoints(det.keypoints),
                "score": det.score,
            })

    category_names = {
        int(cat.get("id", 0)): str(cat.get("name", cat.get("id", 0)))
        for cat in categories
    }
    oks_sigmas = _resolve_oks_sigmas(request.extra_options)
    oks_metrics = compute_coco_style_ap(
        gt_items=all_gts,
        pred_items=all_preds,
        category_names=category_names,
        iou_thresholds=request.oks_thresholds,
        similarity_func=lambda pred, gt: _compute_oks(
            gt["keypoints"],
            pred["keypoints"],
            area=float(gt.get("area", 1.0)),
            sigmas=oks_sigmas,
        ),
    )

    finished_at = datetime.now(timezone.utc)
    duration = (finished_at - started_at).total_seconds()

    # 写报告
    report_key = f"{output_prefix}/reports/pose_evaluation.json"
    report = {
        "sample_count": processed_count,
        "oks_ap50": oks_metrics.ap50,
        "oks_ap50_95": oks_metrics.ap50_95,
        "duration_seconds": duration,
        "per_class_metrics": oks_metrics.per_class_metrics,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
    }
    dataset_storage.write_json(report_key, report)

    return PoseEvaluationResult(
        sample_count=processed_count,
        oks_ap50=oks_metrics.ap50,
        oks_ap50_95=oks_metrics.ap50_95,
        duration_seconds=duration,
        report_object_key=report_key,
        per_class_metrics=oks_metrics.per_class_metrics,
        predictions_payload=all_preds,
        report_payload=report,
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


def _resolve_keypoint_confidence_threshold(extra_options: dict[str, object]) -> float:
    """解析 pose 评估的 keypoint confidence 阈值。"""

    value = extra_options.get("keypoint_confidence_threshold")
    if value is None:
        return 0.25
    return float(value)


def _iter_pose_prediction_instances(result: object):
    """返回当前 runtime contract 下的 pose instance 列表。"""

    instances = getattr(result, "instances", None)
    if instances is not None:
        return instances
    return getattr(result, "detections", ())


def _flatten_pose_keypoints(keypoints: object) -> list[float]:
    """把 pose keypoint 对象归一化为 COCO 风格扁平列表。"""

    if not isinstance(keypoints, (list, tuple)):
        return []
    flattened: list[float] = []
    for keypoint in keypoints:
        if isinstance(keypoint, (int, float)):
            flattened.append(float(keypoint))
            continue
        x = float(getattr(keypoint, "x", 0.0))
        y = float(getattr(keypoint, "y", 0.0))
        confidence = getattr(keypoint, "confidence", None)
        visibility = 2.0 if confidence is None else float(confidence)
        flattened.extend([x, y, visibility])
    return flattened


def _resolve_pose_annotation_area(annotation: dict[str, object]) -> float:
    """解析 pose 标注面积，缺失时用 bbox 面积兜底。"""

    area = annotation.get("area")
    if area is not None:
        return max(float(area), 1.0)
    bbox = annotation.get("bbox")
    if isinstance(bbox, list) and len(bbox) >= 4:
        return max(float(bbox[2]) * float(bbox[3]), 1.0)
    return 1.0


def _resolve_oks_sigmas(extra_options: dict[str, object]) -> tuple[float, ...]:
    """解析 OKS sigma 配置，默认使用 COCO person 17 点 sigma。"""

    raw_sigmas = extra_options.get("oks_sigmas")
    if isinstance(raw_sigmas, list) and raw_sigmas:
        return tuple(float(value) for value in raw_sigmas)
    return (
        0.026,
        0.025,
        0.025,
        0.035,
        0.035,
        0.079,
        0.079,
        0.072,
        0.072,
        0.062,
        0.062,
        0.107,
        0.107,
        0.087,
        0.087,
        0.089,
        0.089,
    )


def _compute_oks(
    gt_kpts: list[float],
    pred_kpts: list[float],
    *,
    area: float,
    sigmas: tuple[float, ...],
) -> float:
    """计算 Object Keypoint Similarity。"""

    if not gt_kpts or not pred_kpts:
        return 0.0

    num_kpts = min(len(gt_kpts) // 3, len(pred_kpts) // 3)
    if num_kpts == 0:
        return 0.0

    oks_sum = 0.0
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
            sigma = sigmas[i] if i < len(sigmas) else 0.05
            denominator = 2.0 * (sigma ** 2) * max(float(area), 1.0)
            import math

            oks_sum += math.exp(-((dx * dx + dy * dy) / max(denominator, 1e-8)))
            visible_count += 1

    if visible_count == 0:
        return 0.0

    return oks_sum / visible_count
