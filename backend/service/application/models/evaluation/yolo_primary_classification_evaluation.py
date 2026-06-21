"""YOLO 主线 classification 数据集级评估执行模块。

对已导出的 classification 数据集中每张样本执行推理，
统计 top-1 / top-5 准确率与 per-class 指标。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.tasks.classification_model_runtime import (
    DefaultClassificationModelRuntime,
)
from backend.service.application.runtime.contracts.classification import (
    ClassificationPredictionRequest,
)
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class ClassificationEvaluationRequest:
    """描述一次 classification 数据集级评估请求。"""

    dataset_storage: LocalDatasetStorage
    runtime_target: RuntimeTargetSnapshot
    manifest_payload: dict[str, object]
    score_threshold: float = 0.0
    top_k: int = 5
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ClassificationEvaluationResult:
    """描述一次 classification 评估结果。"""

    split_name: str
    sample_count: int
    duration_seconds: float
    top1_accuracy: float
    top5_accuracy: float
    per_class_metrics: list[dict[str, object]] = field(default_factory=list)
    report_payload: dict[str, object] = field(default_factory=dict)
    predictions_payload: list[dict[str, object]] = field(default_factory=list)


def run_yolo_primary_classification_evaluation(
    request: ClassificationEvaluationRequest,
) -> ClassificationEvaluationResult:
    """执行 classification 数据集级评估。

    通过 DefaultClassificationModelRuntime 加载对应模型的推理会话，
    逐样本推理并统计 top-1 / top-5 准确率。
    """

    dataset_storage = request.dataset_storage
    manifest = request.manifest_payload
    runtime_target = request.runtime_target
    top_k = max(1, int(request.top_k))

    split_name, samples, label_names = _parse_classification_manifest(manifest, dataset_storage)
    if not samples:
        return ClassificationEvaluationResult(
            split_name=split_name, sample_count=0, duration_seconds=0.0,
            top1_accuracy=0.0, top5_accuracy=0.0,
        )

    runtime = DefaultClassificationModelRuntime()
    session = runtime.load_session(
        dataset_storage=dataset_storage,
        runtime_target=runtime_target,
    )

    started = time.monotonic()
    correct_top1 = 0
    correct_top5 = 0
    total = 0
    per_class_correct: dict[int, int] = {}
    per_class_total: dict[int, int] = {}
    predictions: list[dict[str, object]] = []

    for sample in samples:
        image_path = sample["image_path"]
        gt_class_id = sample["class_id"]
        resolved = dataset_storage.resolve(image_path) if image_path else None
        if resolved is None or not resolved.is_file():
            continue

        image_bytes = resolved.read_bytes()
        pred_request = ClassificationPredictionRequest(
            top_k=top_k, save_result_image=False,
            input_image_bytes=image_bytes,
        )
        try:
            result = session.predict(pred_request)
        except Exception:
            continue

        predicted_ids = [c.class_id for c in result.categories[:top_k]]
        total += 1
        per_class_total[gt_class_id] = per_class_total.get(gt_class_id, 0) + 1

        if predicted_ids and predicted_ids[0] == gt_class_id:
            correct_top1 += 1
            per_class_correct[gt_class_id] = per_class_correct.get(gt_class_id, 0) + 1
        if gt_class_id in predicted_ids:
            correct_top5 += 1

        predictions.append({
            "image_path": str(image_path),
            "ground_truth_class_id": gt_class_id,
            "ground_truth_class_name": label_names[gt_class_id] if gt_class_id < len(label_names) else None,
            "predicted_top_k": [
                {"class_id": c.class_id, "class_name": c.class_name, "probability": round(c.probability, 6)}
                for c in result.categories[:top_k]
            ],
            "top1_correct": bool(predicted_ids and predicted_ids[0] == gt_class_id),
            "top5_correct": bool(gt_class_id in predicted_ids),
        })

    duration = time.monotonic() - started
    top1_acc = correct_top1 / max(total, 1)
    top5_acc = correct_top5 / max(total, 1)

    all_class_ids = sorted(set(list(per_class_total.keys()) + list(range(len(label_names)))))
    per_class: list[dict[str, object]] = []
    for cid in all_class_ids:
        ct = per_class_total.get(cid, 0)
        cc = per_class_correct.get(cid, 0)
        per_class.append({
            "class_id": cid,
            "class_name": label_names[cid] if cid < len(label_names) else str(cid),
            "sample_count": ct,
            "correct_count": cc,
            "accuracy": round(cc / max(ct, 1), 6),
        })

    report = {
        "task_type": "classification",
        "model_type": runtime_target.model_type,
        "split_name": split_name,
        "sample_count": total,
        "duration_seconds": round(duration, 3),
        "top1_accuracy": round(top1_acc, 6),
        "top5_accuracy": round(top5_acc, 6),
        "per_class_metrics": per_class,
    }

    return ClassificationEvaluationResult(
        split_name=split_name, sample_count=total, duration_seconds=duration,
        top1_accuracy=top1_acc, top5_accuracy=top5_acc,
        per_class_metrics=per_class, report_payload=report,
        predictions_payload=predictions,
    )


def _parse_classification_manifest(
    manifest: dict[str, object],
    dataset_storage: LocalDatasetStorage,
) -> tuple[str, list[dict[str, object]], tuple[str, ...]]:
    """解析 classification manifest，返回 (split_name, samples, label_names)。"""

    splits = manifest.get("splits", [])
    categories = manifest.get("categories", [])
    label_names = tuple(
        str(c.get("name", c.get("id", "")))
        for c in categories
        if isinstance(c, dict)
    )

    chosen_split: dict[str, object] | None = None
    for split in (splits or []):
        if not isinstance(split, dict):
            continue
        name = str(split.get("name", "")).lower()
        if name in ("val", "valid", "validation", "test"):
            chosen_split = split
            break
    if chosen_split is None and splits:
        for split in splits:
            if isinstance(split, dict):
                chosen_split = split
                break
    if chosen_split is None:
        raise InvalidRequestError("classification manifest 不包含可用的 split")

    split_name = str(chosen_split.get("name", "unknown"))
    image_root = str(chosen_split.get("image_root", ""))
    annotations = chosen_split.get("annotations", [])
    if not isinstance(annotations, list):
        annotations = []
    if not annotations:
        annotation_file = str(chosen_split.get("annotation_file", ""))
        if annotation_file:
            ann_payload = dataset_storage.read_json(annotation_file)
            if isinstance(ann_payload, dict):
                if not label_names:
                    payload_categories = ann_payload.get("categories", [])
                    if isinstance(payload_categories, list):
                        label_names = tuple(
                            str(c.get("name", c.get("id", "")))
                            for c in payload_categories
                            if isinstance(c, dict)
                        )
                images = ann_payload.get("images", [])
                image_map: dict[int, str] = {}
                if isinstance(images, list):
                    for image in images:
                        if isinstance(image, dict):
                            image_map[int(image.get("id", -1))] = str(
                                image.get("file_name", "")
                            )
                payload_annotations = ann_payload.get("annotations", [])
                if isinstance(payload_annotations, list):
                    annotations = []
                    for annotation in payload_annotations:
                        if not isinstance(annotation, dict):
                            continue
                        image_id = int(annotation.get("image_id", -1))
                        file_name = image_map.get(image_id, "")
                        if not file_name:
                            continue
                        annotations.append(
                            {
                                "image_id": image_id,
                                "file_name": file_name,
                                "category_id": int(annotation.get("category_id", 0)),
                                **dict(annotation),
                            }
                        )

    samples: list[dict[str, object]] = []
    for ann in annotations:
        if not isinstance(ann, dict):
            continue
        file_name = ann.get("file_name") or ann.get("image_path") or ""
        class_id = ann.get("class_id") or ann.get("category_id")
        if class_id is None:
            continue
        full_path = f"{image_root}/{file_name}" if image_root and file_name else str(file_name)
        samples.append({"image_path": full_path, "class_id": int(class_id)})

    return split_name, samples, label_names
