"""统一 detection 数据集级评估执行模块。

适用于所有 detection 模型（yolox/yolov8/yolo11/yolo26/rfdetr），
通过 DefaultDetectionModelRuntime 加载推理会话，逐图推理并计算 mAP。
"""

from __future__ import annotations

import time
from bisect import bisect_right
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
from pathlib import PurePosixPath
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.images.image_matrix import (
    ImageDecodeError,
    decode_image_bytes_to_matrix,
)
from backend.service.application.models.evaluation.manifest_splits import (
    select_independent_evaluation_split,
)
from backend.service.application.runtime.contracts.detection.prediction import (
    DetectionPredictionRequest,
)
from backend.service.application.runtime.session_lifecycle import RuntimeSessionLease
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)

DefaultDetectionModelRuntime: type | None = None


@dataclass(frozen=True)
class DetectionEvaluationRequest:
    """描述一次统一 detection 数据集级评估请求。"""

    dataset_storage: LocalDatasetStorage
    runtime_target: RuntimeTargetSnapshot
    manifest_payload: dict[str, object]
    score_threshold: float = 0.01
    nms_threshold: float | None = 0.65
    extra_options: dict[str, object] = field(default_factory=dict)
    # 接收阶段、覆盖量和最近处理记录，供任务服务保存进度并检查取消。
    on_progress: Callable[[dict[str, object]], None] | None = None


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
    # 仅供授权预览；不进入报告或结果压缩包。
    failed_image_paths: dict[int, str] = field(default_factory=dict)


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

    selected_split = request.extra_options.get("split")
    split_name, images, categories = _parse_detection_manifest(
        manifest, dataset_storage, selected_split=selected_split,
    )
    if request.on_progress is not None:
        request.on_progress({
            "stage": "evaluating", "percent": 5.0, "split_name": split_name,
            "coverage": {"requested": len(images), "succeeded": 0, "failed": 0, "unprocessed": len(images)},
            "recent_samples": [],
        })
    if not images:
        return DetectionEvaluationResult(
            split_name=split_name,
            sample_count=0,
            duration_seconds=0.0,
            map50=0.0,
            map50_95=0.0,
        )

    category_ids = tuple(int(category["id"]) for category in categories)
    category_name_by_id = {
        int(category["id"]): str(category.get("name", category["id"]))
        for category in categories
    }

    runtime_class = DefaultDetectionModelRuntime
    if runtime_class is None:
        from backend.service.application.runtime.tasks.detection_model_runtime import (
            DefaultDetectionModelRuntime as runtime_class,
        )

    runtime = runtime_class()
    session = RuntimeSessionLease(
        runtime.load_session(
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
        )
    )
    try:
        return _run_detection_evaluation_with_session(
            request=request,
            dataset_storage=dataset_storage,
            runtime_target=runtime_target,
            split_name=split_name,
            images=images,
            category_ids=category_ids,
            category_name_by_id=category_name_by_id,
            session=session,
        )
    finally:
        session.close()


def _run_detection_evaluation_with_session(
    *,
    request: DetectionEvaluationRequest,
    dataset_storage: LocalDatasetStorage,
    runtime_target: RuntimeTargetSnapshot,
    split_name: str,
    images: list[dict[str, Any]],
    category_ids: tuple[int, ...],
    category_name_by_id: dict[int, str],
    session: RuntimeSessionLease,
) -> DetectionEvaluationResult:
    """在受控 runtime session 内计算 detection 指标。"""

    started = time.monotonic()

    # 收集所有 GT 和预测结果
    all_gt: list[dict[str, Any]] = []
    all_pred: list[dict[str, Any]] = []
    curve_predictions: list[dict[str, Any]] = []
    predictions_out: list[dict[str, object]] = []
    failed_samples: list[dict[str, object]] = []
    failed_image_paths: dict[int, str] = {}
    curve_score_floor = min(0.001, request.score_threshold)
    confusion: Counter[tuple[int | None, int | None]] = Counter()
    recent_samples: deque[dict[str, object]] = deque(maxlen=3)

    def publish_progress(stage: str) -> None:
        """发送最新的样本覆盖量和有界执行记录。"""
        if request.on_progress is None:
            return
        succeeded, failed = len(predictions_out), len(failed_samples)
        processed = succeeded + failed
        request.on_progress({
            "stage": stage, "percent": 5.0 + 90.0 * processed / len(images), "split_name": split_name,
            "coverage": {"requested": len(images), "succeeded": succeeded, "failed": failed, "unprocessed": len(images) - processed},
            "recent_samples": list(reversed(recent_samples)),
        })

    def note_sample(sample: dict[str, object], status: str) -> None:
        """保存最新样本的文件名、类别和处理时间。"""
        if request.on_progress is not None:
            recent_samples.append({
                "image_index": sample["image_index"], "name": sample["name"], "classes": sample["classes"],
                "status": status, "processed_at": datetime.now(timezone.utc).isoformat(),
            })
            publish_progress("evaluating")

    for img_idx, img_info in enumerate(images):
        image_path = img_info["image_path"]
        gt_annotations = img_info.get("annotations", [])
        failure = img_info.get("sample_error")
        image_bytes = b""
        sample_gt = _validated_sample_ground_truth(img_idx, gt_annotations, category_name_by_id)
        if failure is None:
            try:
                if not image_path:
                    raise FileNotFoundError
                image_bytes = dataset_storage.resolve_filesystem_path(image_path).read_bytes()
            except FileNotFoundError:
                failure = "missing_image"
            except (OSError, InvalidRequestError, ValueError):
                failure = "unreadable_image"
        if failure is None and sample_gt is None:
            failure = "invalid_annotation"
        if failure is not None:
            if image_path:
                failed_image_paths[img_idx] = str(image_path)
            failed_samples.append(_failed_sample(img_idx, image_path, failure, gt_annotations, category_name_by_id))
            note_sample(failed_samples[-1], "failed")
            continue
        assert sample_gt is not None
        predictions_start = len(all_pred)
        prediction_extra_options: dict[str, object] = {}
        if request.nms_threshold is not None:
            prediction_extra_options["nms_threshold"] = request.nms_threshold
        pred_request = DetectionPredictionRequest(
            score_threshold=curve_score_floor,
            save_result_image=False,
            input_image_bytes=image_bytes,
            extra_options=prediction_extra_options,
        )
        try:
            result = session.predict(pred_request)
        except ImageDecodeError:
            if image_path:
                failed_image_paths[img_idx] = str(image_path)
            failed_samples.append(_failed_sample(img_idx, image_path, "unreadable_image", gt_annotations, category_name_by_id))
            note_sample(failed_samples[-1], "failed")
            continue
        all_gt.extend(sample_gt)

        visible_count = 0
        for det in result.detections:
            at_working_point = det.score >= request.score_threshold
            visible_count += int(at_working_point)
            class_index = int(det.class_id)
            category_id = _resolve_detection_category_id(
                class_index=class_index,
                category_ids=category_ids,
            )
            if category_id is None:
                continue
            prediction = {
                "image_id": img_idx,
                # 模型输出是零基索引，COCO 类别 ID 可以不连续。
                "category_id": category_id,
                "bbox_xyxy": det.bbox_xyxy,
                "score": det.score,
            }
            curve_predictions.append(prediction)
            if at_working_point:
                all_pred.append(prediction)

        sample_pred = all_pred[predictions_start:]
        confusion.update(_detection_confusion(sample_gt, sample_pred))
        predictions_out.append(
            {
                "image_index": img_idx,
                "image_path": str(image_path),
                "gt_count": len(gt_annotations),
                "pred_count": visible_count,
                "latency_ms": result.latency_ms,
                **_summarize_detection_sample(sample_gt, sample_pred, category_name_by_id),
            }
        )
        if request.on_progress is not None:
            note_sample(_sample_identity(img_idx, image_path, gt_annotations, category_name_by_id), "succeeded")

    duration = time.monotonic() - started
    total_images = len(predictions_out)
    coverage = {"requested": len(images), "succeeded": total_images, "failed": len(failed_samples), "unprocessed": 0}
    if not total_images:
        raise InvalidRequestError("没有可用于计算指标的评估样本", details={"coverage": coverage})

    publish_progress("summarizing")

    # 计算 mAP
    iou_thresholds = [0.5 + 0.05 * i for i in range(10)]  # 0.5, 0.55, ..., 0.95
    all_class_ids = sorted(
        set([g["category_id"] for g in all_gt] + [p["category_id"] for p in all_pred])
    )

    ap_at_50_list: list[float] = []
    ap_at_all_list: list[float] = []
    precision_list: list[float] = []
    recall_list: list[float] = []
    per_class: list[dict[str, object]] = []
    curves: list[dict[str, object]] = []
    confidence = sorted({curve_score_floor, request.score_threshold, *(i / 100 for i in range(1, 101))})
    curve_by_class: dict[int, list[dict[str, Any]]] = {}
    for prediction in curve_predictions:
        curve_by_class.setdefault(prediction["category_id"], []).append(prediction)

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
        cat_ap_all = [cat_ap50, *(_compute_ap(cat_gt, cat_pred, iou_threshold=t) for t in iou_thresholds[1:])]
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

        name = category_name_by_id.get(cat_id, str(cat_id))
        curve_pred = sorted(curve_by_class.get(cat_id, []), key=lambda item: item["score"], reverse=True)
        matches = _detection_matches(cat_gt, curve_pred, iou_threshold=0.5)
        neg_scores = [-item["score"] for item in curve_pred]
        f1_at_threshold = []
        for threshold in confidence:
            count = bisect_right(neg_scores, -threshold)
            tp = matches[count - 1] if count else 0
            f1_at_threshold.append(round(2 * tp / (len(cat_gt) + count), 6))
        curves.append({
            "class_id": cat_id, "class_name": name,
            "precision_recall": _interpolated_precision(matches, len(cat_gt)),
            "f1_confidence": f1_at_threshold,
        })
        per_class.append(
            {
                "class_id": cat_id,
                "class_name": name,
                "gt_count": len(cat_gt),
                "pred_count": len(cat_pred),
                "ap50": round(cat_ap50, 6),
                "ap50_95": round(cat_ap_mean, 6),
                "precision": round(cat_precision, 6),
                "recall": round(cat_recall, 6),
                "f1": round(cat_f1, 6),
            }
        )

    map50 = sum(ap_at_50_list) / max(len(ap_at_50_list), 1) if ap_at_50_list else 0.0
    map50_95 = (
        sum(ap_at_all_list) / max(len(ap_at_all_list), 1) if ap_at_all_list else 0.0
    )
    mean_precision = (
        sum(precision_list) / max(len(precision_list), 1) if precision_list else 0.0
    )
    mean_recall = sum(recall_list) / max(len(recall_list), 1) if recall_list else 0.0
    mean_f1 = (
        (2 * mean_precision * mean_recall / (mean_precision + mean_recall))
        if (mean_precision + mean_recall) > 0
        else 0.0
    )

    report: dict[str, object] = {
        "task_type": "detection",
        "model_type": runtime_target.model_type,
        "split_name": split_name,
        "sample_count": total_images,
        "coverage": coverage,
        "failed_samples": failed_samples,
        "duration_seconds": round(duration, 3),
        "map50": round(map50, 6),
        "map50_95": round(map50_95, 6),
        "mean_precision": round(mean_precision, 6),
        "mean_recall": round(mean_recall, 6),
        "mean_f1": round(mean_f1, 6),
        "score_threshold": request.score_threshold,
        "per_class_metrics": per_class,
        "curves": {
            "iou_threshold": 0.5, "working_point": request.score_threshold,
            "score_floor": curve_score_floor, "confidence": confidence, "series": curves,
            "confusion": [
                {"actual": actual, "predicted": predicted, "count": count}
                for (actual, predicted), count in confusion.items()
            ],
            "labels": [{"id": cid, "name": category_name_by_id.get(cid, str(cid))} for cid in all_class_ids],
        },
        "ground_truth_count": len(all_gt),
        "prediction_count": len(all_pred),
        "samples_with_false_negatives": sum(bool(sample["false_negatives"]) for sample in predictions_out),
        "samples_with_false_positives": sum(bool(sample["false_positives"]) for sample in predictions_out),
    }
    if request.nms_threshold is not None:
        report["nms_threshold"] = request.nms_threshold

    return DetectionEvaluationResult(
        split_name=split_name,
        sample_count=total_images,
        duration_seconds=duration,
        map50=map50,
        map50_95=map50_95,
        mean_precision=mean_precision,
        mean_recall=mean_recall,
        mean_f1=mean_f1,
        per_class_metrics=per_class,
        report_payload=report,
        detections_payload=predictions_out,
        failed_image_paths=failed_image_paths,
    )


def _validated_sample_ground_truth(
    image_index: int, annotations: list[dict[str, Any]], names: dict[int, str],
) -> list[dict[str, Any]] | None:
    """标注必须有已知类别和有限、有效的框；错误时整张样本不计分。"""
    ground_truth = []
    for annotation in annotations:
        box = annotation.get("bbox")
        category_id = annotation.get("category_id")
        if type(category_id) is not int or category_id not in names:
            return None
        if not isinstance(box, list) or len(box) != 4:
            return None
        if any(not isinstance(v, (int, float)) or not isfinite(v) for v in box):
            return None
        x, y, width, height = box
        if width <= 0 or height <= 0 or not all(map(isfinite, (x + width, y + height, width * height))):
            return None
        ground_truth.append({
            "image_id": image_index, "category_id": category_id,
            "bbox_xyxy": (x, y, x + width, y + height), "area": width * height,
        })
    return ground_truth


def _failed_sample(
    image_index: int, path: str, reason: str, annotations: list[dict[str, Any]], names: dict[int, str],
) -> dict[str, object]:
    """失败样本报告仅保留名称和已知类别。"""
    return {**_sample_identity(image_index, path, annotations, names), "reason": reason}


def _sample_identity(
    image_index: int, path: str, annotations: list[dict[str, Any]], names: dict[int, str],
) -> dict[str, object]:
    """返回执行记录和报告共用的样本标识，不返回文件路径。"""
    return {
        "image_index": image_index,
        "name": PurePosixPath(str(path).replace("\\", "/")).name,
        "classes": sorted({names[cid] for ann in annotations
                           if isinstance(cid := ann.get("category_id"), int) and cid in names}),
    }


def _detection_confusion(
    ground_truth: list[dict], predictions: list[dict],
) -> list[tuple[int | None, int | None]]:
    """按置信度和 IoU 0.50 匹配不同类别的框，记录错分与背景。"""
    remaining = set(range(len(ground_truth)))
    pairs = []
    for prediction in sorted(predictions, key=lambda item: item["score"], reverse=True):
        best = max(sorted(remaining), key=lambda idx: _box_iou(
            ground_truth[idx]["bbox_xyxy"], prediction["bbox_xyxy"],
        ), default=None)
        if best is not None and _box_iou(ground_truth[best]["bbox_xyxy"], prediction["bbox_xyxy"]) >= 0.5:
            remaining.remove(best)
            pairs.append((ground_truth[best]["category_id"], prediction["category_id"]))
        else:
            pairs.append((None, prediction["category_id"]))
    pairs.extend((ground_truth[idx]["category_id"], None) for idx in sorted(remaining))
    return pairs


def _summarize_detection_sample(ground_truth: list[dict], predictions: list[dict], names: dict[int, str]) -> dict[str, object]:
    """记录可回放标注与预测，按同类别和 IoU 0.50 标记漏检及误检。"""
    missed = set(range(len(ground_truth)))
    ordered = sorted(predictions, key=lambda item: item["score"], reverse=True)
    predicted = []
    for item in ordered:
        same_class = [index for index in missed if ground_truth[index]["category_id"] == item["category_id"]]
        best = max(same_class, key=lambda index: _box_iou(item["bbox_xyxy"], ground_truth[index]["bbox_xyxy"]), default=None)
        matched = best is not None and _box_iou(item["bbox_xyxy"], ground_truth[best]["bbox_xyxy"]) >= 0.5
        if matched:
            missed.remove(best)
        predicted.append({
            "class_name": names.get(item["category_id"], str(item["category_id"])),
            "bbox_xyxy": item["bbox_xyxy"], "score": item["score"], "matched": matched,
        })
    return {
        "ground_truth": [{
            "class_name": names.get(item["category_id"], str(item["category_id"])),
            "bbox_xyxy": item["bbox_xyxy"], "matched": index not in missed,
        } for index, item in enumerate(ground_truth)],
        "predictions": predicted,
        "false_negatives": len(missed),
        "false_positives": sum(not item["matched"] for item in predicted),
    }


def find_localization_error(sample: dict, class_name: str = "") -> dict[str, int | float] | None:
    """返回同类别未匹配框中 IoU 最大的重叠对，定位偏差的 IoU 低于 0.50。

    sample 是持久化的样本快照，class_name 为空时比较所有已知类别。
    返回值包含两个原始框的索引及其 IoU，旧快照没有完整框时返回空。
    """
    if not sample.get("false_negatives") or not sample.get("false_positives"):
        return None

    def unmatched(layer: str):
        """提取指定快照图层的有效未匹配框。"""
        for index, item in enumerate(sample.get(layer) or ()):
            if not isinstance(item, dict) or item.get("matched") is not False:
                continue
            name, box = item.get("class_name"), item.get("bbox_xyxy")
            if (not isinstance(name, str) or not name or class_name and name != class_name
                or not isinstance(box, (list, tuple)) or len(box) != 4
                or not all(isinstance(value, (int, float)) and isfinite(value) for value in box)):
                continue
            yield index, name, tuple(box)

    truth = list(unmatched("ground_truth"))
    best = None
    best_iou = 0.0
    for pred_index, category, prediction_box in unmatched("predictions"):
        for truth_index, truth_category, truth_box in truth:
            if truth_category != category:
                continue
            iou = _box_iou(truth_box, prediction_box)
            if best_iou < iou < 0.5:
                best_iou = iou
                best = {"ground_truth_index": truth_index, "prediction_index": pred_index, "iou": iou}
    return best


def _resolve_detection_category_id(
    *,
    class_index: int,
    category_ids: tuple[int, ...],
) -> int | None:
    """把模型零基 class index 映射到 manifest 的真实 category id。"""

    if class_index < 0 or class_index >= len(category_ids):
        return None
    return int(category_ids[class_index])


def _parse_detection_manifest(
    manifest: dict[str, object],
    dataset_storage: LocalDatasetStorage,
    *,
    selected_split: object = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """解析 detection manifest，返回 (split_name, images, categories)。"""
    splits = manifest.get("splits", [])

    chosen_split = select_independent_evaluation_split(splits, selected_split=selected_split)
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
    resolved_image_root = dataset_storage.resolve_filesystem_path(image_root)
    resolved_label_root = dataset_storage.resolve_filesystem_path(label_root)
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
    for image_id, image_path in enumerate(
        _iter_detection_image_files(resolved_image_root), start=1
    ):
        relative_image_path = image_path.relative_to(resolved_image_root).as_posix()
        label_path = (resolved_label_root / relative_image_path).with_suffix(".txt")
        item: dict[str, Any] = {"image_path": f"{image_root}/{relative_image_path}"}
        try:
            image_width, image_height = _read_detection_image_size(image_path)
        except FileNotFoundError:
            item["sample_error"] = "missing_image"
        except (ImageDecodeError, OSError):
            item["sample_error"] = "unreadable_image"
        else:
            try:
                item["annotations"] = _parse_yolo_detection_annotations(
                    label_path=label_path, image_id=image_id,
                    image_width=image_width, image_height=image_height,
                )
            except (OSError, ValueError):
                item["sample_error"] = "invalid_annotation"
        images.append(item)
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
    for img in annotation_payload.get("images") or []:
        if isinstance(img, dict):
            images_by_id[int(img.get("id", -1))] = str(img.get("file_name", ""))

    anns_by_image: dict[int, list[dict[str, Any]]] = {}
    for ann in annotation_payload.get("annotations") or []:
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
    import numpy as np

    image = decode_image_bytes_to_matrix(
        cv2_module=cv2, np_module=np, image_bytes=image_path.read_bytes(),
        image_payload=None, imdecode_flags=cv2.IMREAD_UNCHANGED,
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
            raise ValueError("无效的 YOLO 标注字段数")
        category_index = int(parts[0])
        x_center, y_center, box_width, box_height = map(float, parts[1:])
        if not all(map(isfinite, (x_center, y_center, box_width, box_height))):
            raise ValueError("YOLO 标注必须为有限数值")
        x = max(0.0, (x_center - (box_width / 2.0)) * float(image_width))
        y = max(0.0, (y_center - (box_height / 2.0)) * float(image_height))
        w = max(0.0, box_width * float(image_width))
        h = max(0.0, box_height * float(image_height))
        if w <= 0.0 or h <= 0.0:
            raise ValueError("YOLO 标注宽高必须为正数")
        annotations.append(
            {
                "image_id": image_id,
                "category_id": category_index + 1,
                "bbox": [x, y, w, h],
            }
        )
    return annotations


def _detection_matches(
    gt_list: list[dict], pred_list: list[dict], iou_threshold: float,
) -> list[int]:
    """按置信度降序逐框匹配同类标注，返回每个预测之后的累计 TP。"""
    gt_by_image: dict[int, list[dict]] = {}
    for gt in gt_list:
        gt_by_image.setdefault(gt["image_id"], []).append(gt)

    cumulative: list[int] = []
    matched: set[tuple[int, int]] = set()
    for prediction in pred_list:
        image_id = prediction["image_id"]
        best_index = None
        best_iou = 0.0
        for index, gt in enumerate(gt_by_image.get(image_id, ())):
            if (image_id, index) in matched:
                continue
            iou = _box_iou(prediction["bbox_xyxy"], gt["bbox_xyxy"])
            if iou > best_iou:
                best_iou = iou
                best_index = index
        if best_index is not None and best_iou >= iou_threshold:
            matched.add((image_id, best_index))
        cumulative.append(len(matched))
    return cumulative


def _interpolated_precision(matches: list[int], total_gt: int) -> list[float]:
    """在 101 个召回率点查找单调的精确率包络。"""
    precisions = [0.0] * 101
    recall_index = 100
    best = 0.0
    for index in range(len(matches) - 1, -1, -1):
        recall = matches[index] / total_gt
        while recall_index >= 0 and recall_index / 100 > recall:
            precisions[recall_index] = best
            recall_index -= 1
        best = max(best, matches[index] / (index + 1))
    for index in range(recall_index + 1):
        precisions[index] = best
    return precisions


def _compute_ap(gt_list: list[dict], pred_list: list[dict], iou_threshold: float = 0.5) -> float:
    """计算单类别的 101 点插值 AP。"""
    if not gt_list or not pred_list:
        return 0.0
    matches = _detection_matches(gt_list, pred_list, iou_threshold)
    return sum(_interpolated_precision(matches, len(gt_list))) / 101


def _compute_precision_recall_f1(
    gt_list: list[dict], pred_list: list[dict], iou_threshold: float = 0.5,
) -> dict[str, float]:
    """计算单类别在工作点的 Precision、Recall 和 F1。"""
    matches = _detection_matches(gt_list, pred_list, iou_threshold)
    tp = matches[-1] if matches else 0
    return {
        "precision": tp / max(len(pred_list), 1),
        "recall": tp / max(len(gt_list), 1),
        "f1": 2 * tp / max(len(gt_list) + len(pred_list), 1),
    }

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
