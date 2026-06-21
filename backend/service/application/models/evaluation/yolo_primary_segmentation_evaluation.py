"""YOLO 主线 segmentation 数据集级评估执行模块。

对已导出的 segmentation 数据集中每张样本执行推理，
统计 bbox AP 与 mask IoU 指标。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.evaluation.coco_style_metrics import (
    bbox_iou_xyxy,
    compute_coco_style_ap,
)
from backend.service.application.models.support.yolo_dataset_manifest_support import (
    build_coco_payload_from_yolo_segmentation_split,
    normalize_yolo_category_names,
)
from backend.service.application.runtime.tasks.segmentation_model_runtime import (
    DefaultSegmentationModelRuntime,
)
from backend.service.application.runtime.contracts.segmentation.prediction import (
    SegmentationPredictionRequest,
)
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot
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
    gt_bbox_items: list[dict[str, object]] = []
    pred_bbox_items: list[dict[str, object]] = []
    gt_mask_items: list[dict[str, object]] = []
    pred_mask_items: list[dict[str, object]] = []
    predictions_out: list[dict[str, object]] = []
    category_names = {index: name for index, name in enumerate(label_names)}

    for img_idx, sample in enumerate(samples):
        image_path = sample["image_path"]
        gt_annotations = sample.get("annotations", [])
        resolved = dataset_storage.resolve(image_path) if image_path else None
        if resolved is None or not resolved.is_file():
            continue

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

        image_width = int(result.image_width)
        image_height = int(result.image_height)
        for ann in gt_annotations:
            bbox = ann.get("bbox")
            category_id = int(ann.get("category_id", 0))
            if isinstance(bbox, list) and len(bbox) == 4:
                x, y, w, h = (float(value) for value in bbox)
                gt_bbox_items.append(
                    {
                        "image_id": img_idx,
                        "category_id": category_id,
                        "bbox_xyxy": [x, y, x + w, y + h],
                    },
                )
            mask = _build_segmentation_annotation_mask(
                annotation=ann,
                width=image_width,
                height=image_height,
            )
            if mask is not None:
                gt_mask_items.append(
                    {
                        "image_id": img_idx,
                        "category_id": category_id,
                        "mask": mask,
                    },
                )

        for inst in result.instances:
            pred_bbox_items.append(
                {
                    "image_id": img_idx,
                    "category_id": int(inst.class_id),
                    "bbox_xyxy": list(inst.bbox_xyxy),
                    "score": float(inst.score),
                },
            )
            mask = _build_segmentation_instance_mask(
                segments=inst.segments,
                width=image_width,
                height=image_height,
            )
            if mask is not None:
                pred_mask_items.append(
                    {
                        "image_id": img_idx,
                        "category_id": int(inst.class_id),
                        "mask": mask,
                        "score": float(inst.score),
                    },
                )

        predictions_out.append({
            "image_index": img_idx,
            "image_path": str(image_path),
            "gt_count": len(gt_annotations),
            "pred_count": len(result.instances),
            "latency_ms": result.latency_ms,
        })

    duration = time.monotonic() - started
    total_images = len(predictions_out)

    bbox_metrics = compute_coco_style_ap(
        gt_items=gt_bbox_items,
        pred_items=pred_bbox_items,
        category_names=category_names,
        iou_thresholds=request.iou_thresholds,
        similarity_func=lambda pred, gt: bbox_iou_xyxy(
            pred["bbox_xyxy"],
            gt["bbox_xyxy"],
        ),
    )
    mask_metrics = compute_coco_style_ap(
        gt_items=gt_mask_items,
        pred_items=pred_mask_items,
        category_names=category_names,
        iou_thresholds=request.iou_thresholds,
        similarity_func=lambda pred, gt: _mask_iou(pred["mask"], gt["mask"]),
    )
    per_class_metrics = _merge_segmentation_per_class_metrics(
        bbox_metrics=bbox_metrics.per_class_metrics,
        mask_metrics=mask_metrics.per_class_metrics,
    )

    report = {
        "task_type": "segmentation",
        "model_type": runtime_target.model_type,
        "split_name": split_name,
        "sample_count": total_images,
        "duration_seconds": round(duration, 3),
        "map50": round(bbox_metrics.ap50, 6),
        "map50_95": round(bbox_metrics.ap50_95, 6),
        "mask_map50": round(mask_metrics.ap50, 6),
        "mask_map50_95": round(mask_metrics.ap50_95, 6),
        "score_threshold": request.score_threshold,
        "mask_threshold": request.mask_threshold,
        "per_class_metrics": per_class_metrics,
    }

    return SegmentationEvaluationResult(
        split_name=split_name, sample_count=total_images, duration_seconds=duration,
        map50=bbox_metrics.ap50, map50_95=bbox_metrics.ap50_95,
        mask_map50=mask_metrics.ap50, mask_map50_95=mask_metrics.ap50_95,
        per_class_metrics=per_class_metrics,
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


def _build_segmentation_annotation_mask(
    *,
    annotation: dict,
    width: int,
    height: int,
):
    """把 COCO polygon segmentation 标注转换为二值 mask。"""

    segmentation = annotation.get("segmentation")
    polygons = _normalize_segmentation_polygons(segmentation)
    if not polygons:
        return None
    return _rasterize_polygons(polygons=polygons, width=width, height=height)


def _build_segmentation_instance_mask(
    *,
    segments: object,
    width: int,
    height: int,
):
    """把预测 segments 转换为二值 mask。"""

    polygons: list[list[tuple[float, float]]] = []
    if isinstance(segments, (list, tuple)):
        for segment in segments:
            if not isinstance(segment, (list, tuple)):
                continue
            polygon: list[tuple[float, float]] = []
            for point in segment:
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    polygon.append((float(point[0]), float(point[1])))
            if len(polygon) >= 3:
                polygons.append(polygon)
    if not polygons:
        return None
    return _rasterize_polygons(polygons=polygons, width=width, height=height)


def _normalize_segmentation_polygons(segmentation: object) -> list[list[tuple[float, float]]]:
    """归一化 COCO polygon segmentation。"""

    polygons: list[list[tuple[float, float]]] = []
    if not isinstance(segmentation, list):
        return polygons
    raw_polygons = segmentation
    if raw_polygons and all(isinstance(value, (int, float)) for value in raw_polygons):
        raw_polygons = [raw_polygons]
    for raw_polygon in raw_polygons:
        if not isinstance(raw_polygon, list) or len(raw_polygon) < 6:
            continue
        polygon = [
            (float(raw_polygon[index]), float(raw_polygon[index + 1]))
            for index in range(0, len(raw_polygon) - 1, 2)
        ]
        if len(polygon) >= 3:
            polygons.append(polygon)
    return polygons


def _rasterize_polygons(*, polygons: list[list[tuple[float, float]]], width: int, height: int):
    """用 Pillow 把 polygon 列表栅格化为 NumPy bool mask。"""

    from PIL import Image, ImageDraw
    import numpy as np

    mask_image = Image.new("1", (max(1, int(width)), max(1, int(height))), 0)
    draw = ImageDraw.Draw(mask_image)
    for polygon in polygons:
        draw.polygon(polygon, outline=1, fill=1)
    return np.asarray(mask_image, dtype=bool)


def _mask_iou(mask1: object, mask2: object) -> float:
    """计算两个二值 mask 的 IoU。"""

    import numpy as np

    left = np.asarray(mask1, dtype=bool)
    right = np.asarray(mask2, dtype=bool)
    if left.shape != right.shape:
        return 0.0
    intersection = np.logical_and(left, right).sum()
    union = np.logical_or(left, right).sum()
    return float(intersection / max(float(union), 1.0))


def _merge_segmentation_per_class_metrics(
    *,
    bbox_metrics: list[dict[str, object]],
    mask_metrics: list[dict[str, object]],
) -> list[dict[str, object]]:
    """合并 bbox AP 和 mask AP 的 per-class 摘要。"""

    mask_by_category = {
        int(item["category_id"]): item
        for item in mask_metrics
        if "category_id" in item
    }
    merged: list[dict[str, object]] = []
    for bbox_item in bbox_metrics:
        category_id = int(bbox_item["category_id"])
        mask_item = mask_by_category.get(category_id, {})
        merged.append(
            {
                "category_id": category_id,
                "category_name": bbox_item.get("category_name", str(category_id)),
                "gt_count": bbox_item.get("gt_count", 0),
                "pred_count": bbox_item.get("pred_count", 0),
                "bbox_ap50": bbox_item.get("ap50", 0.0),
                "bbox_ap50_95": bbox_item.get("ap50_95", 0.0),
                "mask_ap50": mask_item.get("ap50", 0.0),
                "mask_ap50_95": mask_item.get("ap50_95", 0.0),
            },
        )
    return merged
