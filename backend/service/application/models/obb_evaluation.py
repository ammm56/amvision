"""OBB 数据集级评估执行模块。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.service.application.models.coco_style_metrics import (
    bbox_iou_xyxy,
    compute_coco_style_ap,
    polygon_bounds_xyxy,
    polygon_iou,
    xywhr_to_polygon,
)
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
    iou_thresholds: tuple[float, ...] = (0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95)
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
    report_payload: dict[str, object] = field(default_factory=dict)


def run_obb_evaluation(request: ObbEvaluationRequest) -> ObbEvaluationResult:
    """执行 OBB 数据集级评估（旋转框 AP 计算）。"""
    dataset_storage = request.dataset_storage
    manifest = request.manifest_payload
    score_threshold = request.score_threshold
    output_prefix = f"task-runs/evaluation/{request.runtime_target.model_version_id}"

    from backend.service.application.runtime.obb_model_runtime import DefaultObbModelRuntime

    model_runtime = DefaultObbModelRuntime()
    session = model_runtime.load_session(
        dataset_storage=dataset_storage,
        runtime_target=request.runtime_target,
    )

    started_at = datetime.now(timezone.utc)

    # 解析 manifest
    images, annotations, categories = _parse_obb_manifest_payload(
        manifest=manifest,
        dataset_storage=dataset_storage,
    )

    # 按 image_id 分组 GT
    gt_by_image: dict[int, list[dict]] = {}
    for ann in annotations:
        img_id = ann["image_id"]
        gt_by_image.setdefault(img_id, []).append(ann)

    gt_items: list[dict[str, object]] = []
    for annotation in annotations:
        gt_item = _build_obb_gt_item(annotation)
        if gt_item is not None:
            gt_items.append(gt_item)
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
            result = session.predict(pred_request)
        except Exception:
            continue

        processed_count += 1

        # 收集预测
        for det in _iter_obb_prediction_instances(result):
            bbox = _build_obb_prediction_bbox(det)
            all_preds.append({
                "image_id": img_id,
                "category_id": det.class_id,
                "bbox": bbox,
                "polygon": _xywhr_to_polygon(bbox),
                "score": det.score,
            })

    category_names = {
        int(category.get("id", 0)): str(category.get("name", category.get("id", 0)))
        for category in categories
    }
    obb_metrics = compute_coco_style_ap(
        gt_items=gt_items,
        pred_items=all_preds,
        category_names=category_names,
        iou_thresholds=request.iou_thresholds,
        similarity_func=lambda pred, gt: _compute_obb_iou(
            pred.get("polygon"),
            gt.get("polygon"),
            pred.get("bbox"),
            gt.get("bbox"),
        ),
    )

    finished_at = datetime.now(timezone.utc)
    duration = (finished_at - started_at).total_seconds()

    # 写报告
    report_key = f"{output_prefix}/reports/obb_evaluation.json"
    report = {
        "sample_count": processed_count,
        "map50": obb_metrics.ap50,
        "map50_95": obb_metrics.ap50_95,
        "duration_seconds": duration,
        "per_class_metrics": obb_metrics.per_class_metrics,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
    }
    dataset_storage.write_json(report_key, report)

    return ObbEvaluationResult(
        sample_count=processed_count,
        map50=obb_metrics.ap50,
        map50_95=obb_metrics.ap50_95,
        duration_seconds=duration,
        report_object_key=report_key,
        per_class_metrics=obb_metrics.per_class_metrics,
        predictions_payload=all_preds,
        report_payload=report,
    )


def _parse_obb_manifest_payload(
    *,
    manifest: dict[str, object],
    dataset_storage: LocalDatasetStorage,
) -> tuple[dict[int, dict[str, object]], list[dict], list[dict]]:
    """把 OBB manifest 解析为评估直接使用的 images/annotations/categories。"""

    images_payload = manifest.get("images", [])
    annotations_payload = manifest.get("annotations", [])
    categories_payload = manifest.get("categories", [])
    if (
        isinstance(images_payload, list)
        and isinstance(annotations_payload, list)
        and isinstance(categories_payload, list)
        and images_payload
    ):
        return (
            {int(img["id"]): img for img in images_payload if isinstance(img, dict) and "id" in img},
            [ann for ann in annotations_payload if isinstance(ann, dict)],
            [cat for cat in categories_payload if isinstance(cat, dict)],
        )

    split_entries = manifest.get("splits", [])
    if not isinstance(split_entries, list):
        return {}, [], []

    images: dict[int, dict[str, object]] = {}
    annotations: list[dict] = []
    categories_by_id: dict[int, dict] = {}
    next_image_id = 1
    next_annotation_id = 1
    for split in split_entries:
        if not isinstance(split, dict):
            continue
        image_root = str(split.get("image_root", ""))
        annotation_file = str(split.get("annotation_file", ""))
        if not annotation_file:
            continue
        payload = dataset_storage.read_json(annotation_file)
        if not isinstance(payload, dict):
            continue
        local_categories = payload.get("categories", [])
        if isinstance(local_categories, list):
            for category in local_categories:
                if not isinstance(category, dict):
                    continue
                category_id = int(category.get("id", -1))
                if category_id >= 0:
                    categories_by_id[category_id] = category

        image_map: dict[int, int] = {}
        local_images = payload.get("images", [])
        if isinstance(local_images, list):
            for image in local_images:
                if not isinstance(image, dict):
                    continue
                local_image_id = int(image.get("id", -1))
                images[next_image_id] = {
                    "id": next_image_id,
                    "file_name": f"{image_root}/{image.get('file_name', '')}",
                    "width": image.get("width"),
                    "height": image.get("height"),
                }
                image_map[local_image_id] = next_image_id
                next_image_id += 1

        local_annotations = payload.get("annotations", [])
        if isinstance(local_annotations, list):
            for annotation in local_annotations:
                if not isinstance(annotation, dict):
                    continue
                local_image_id = int(annotation.get("image_id", -1))
                global_image_id = image_map.get(local_image_id)
                if global_image_id is None:
                    continue
                merged_annotation = dict(annotation)
                merged_annotation["id"] = next_annotation_id
                merged_annotation["image_id"] = global_image_id
                next_annotation_id += 1
                annotations.append(merged_annotation)

    categories = [
        categories_by_id[category_id]
        for category_id in sorted(categories_by_id)
    ]
    return images, annotations, categories


def _iter_obb_prediction_instances(result: object):
    """返回当前 runtime contract 下的 OBB instance 列表。"""

    instances = getattr(result, "instances", None)
    if instances is not None:
        return instances
    return getattr(result, "detections", ())


def _build_obb_prediction_bbox(instance: object) -> list[float]:
    """把 OBB prediction instance 归一化为 xywhr。"""

    bbox = getattr(instance, "bbox", None)
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 5:
        return [float(value) for value in bbox[:5]]
    bbox_xyxy = getattr(instance, "bbox_xyxy", None)
    if isinstance(bbox_xyxy, (list, tuple)) and len(bbox_xyxy) >= 4:
        x1, y1, x2, y2 = (float(value) for value in bbox_xyxy[:4])
        return [
            (x1 + x2) / 2.0,
            (y1 + y2) / 2.0,
            max(0.0, x2 - x1),
            max(0.0, y2 - y1),
            float(getattr(instance, "angle", 0.0) or 0.0),
        ]
    return [0.0, 0.0, 0.0, 0.0, 0.0]


def _build_obb_gt_item(annotation: dict) -> dict[str, object] | None:
    """把 OBB annotation 归一化为 COCO-style AP 使用的 GT 项。"""

    polygon = _normalize_obb_polygon(annotation.get("poly") or annotation.get("polygon"))
    bbox = _normalize_obb_bbox(annotation.get("bbox"))
    if polygon is None and bbox is not None:
        polygon = _bbox_to_polygon(bbox)
    if polygon is None and bbox is None:
        return None
    if bbox is None and polygon is not None:
        bbox = _polygon_to_xywhr(polygon)
    return {
        "image_id": int(annotation.get("image_id", -1)),
        "category_id": int(annotation.get("category_id", 0)),
        "bbox": bbox,
        "polygon": polygon,
    }


def _compute_obb_iou(
    polygon1: object,
    polygon2: object,
    bbox1: object,
    bbox2: object,
) -> float:
    """计算两个 OBB 的 rotated IoU。"""

    left_polygon = _normalize_obb_polygon(polygon1)
    right_polygon = _normalize_obb_polygon(polygon2)
    if left_polygon is not None and right_polygon is not None:
        return _polygon_iou(left_polygon, right_polygon)

    left_bbox = _normalize_obb_bbox(bbox1)
    right_bbox = _normalize_obb_bbox(bbox2)
    if left_bbox is None or right_bbox is None:
        return 0.0
    return bbox_iou_xyxy(_bbox_to_xyxy(left_bbox), _bbox_to_xyxy(right_bbox))


def _normalize_obb_bbox(value: object) -> list[float] | None:
    """归一化 OBB bbox，支持 xywhr 或 xywh。"""

    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    numbers = [float(item) for item in value[:5]]
    if len(numbers) >= 5:
        return numbers[:5]
    x, y, width, height = numbers[:4]
    return [x + width / 2.0, y + height / 2.0, width, height, 0.0]


def _normalize_obb_polygon(value: object) -> list[tuple[float, float]] | None:
    """归一化 OBB polygon。"""

    if not isinstance(value, (list, tuple)):
        return None
    if len(value) == 8 and all(isinstance(item, (int, float)) for item in value):
        return [
            (float(value[index]), float(value[index + 1]))
            for index in range(0, 8, 2)
        ]
    points: list[tuple[float, float]] = []
    for point in value:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            points.append((float(point[0]), float(point[1])))
    return points if len(points) >= 3 else None


def _bbox_to_polygon(bbox: list[float]) -> list[tuple[float, float]]:
    """把 xywhr bbox 转为四点 polygon。"""

    if len(bbox) >= 5:
        return _xywhr_to_polygon(bbox)
    x, y, width, height = (float(value) for value in bbox[:4])
    return [
        (x, y),
        (x + width, y),
        (x + width, y + height),
        (x, y + height),
    ]


def _xywhr_to_polygon(bbox: list[float]) -> list[tuple[float, float]]:
    """把 xywhr 旋转框转为四点 polygon。"""

    return xywhr_to_polygon(bbox)


def _polygon_to_xywhr(polygon: list[tuple[float, float]]) -> list[float]:
    """用 polygon 外接矩形生成保底 xywhr。"""

    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)
    return [
        (min_x + max_x) / 2.0,
        (min_y + max_y) / 2.0,
        max_x - min_x,
        max_y - min_y,
        0.0,
    ]


def _bbox_to_xyxy(bbox: list[float]) -> list[float]:
    """把 xywhr bbox 的外接矩形转换为 xyxy。"""

    polygon = _bbox_to_polygon(bbox)
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return [min(xs), min(ys), max(xs), max(ys)]


def _polygon_iou(
    polygon1: list[tuple[float, float]],
    polygon2: list[tuple[float, float]],
) -> float:
    """用 OpenCV 计算两个凸 polygon 的 IoU。"""

    return polygon_iou(polygon1, polygon2)


def _polygon_bounds(polygon: list[tuple[float, float]]) -> list[float]:
    """计算 polygon 外接 xyxy。"""

    return polygon_bounds_xyxy(polygon)
