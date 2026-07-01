"""YOLOv8 segmentation 评估入口。"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
import time
from typing import Any

from backend.service.application.models.yolo_core_common.geometry import (
    build_yolo_letterbox_transform,
)

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.evaluation.coco_style_metrics import (
    bbox_iou_xyxy,
    compute_coco_style_ap,
    mask_iou,
)
from backend.service.application.models.yolo_core_common.training.task_dataloader import (
    build_yolo_task_evaluation_dataloader,
    load_yolo_task_dataloader_imports,
    move_yolo_task_batch_to_device,
    resolve_yolo_task_evaluation_dataloader_plan,
)
from backend.service.application.models.support.yolo_dataset_manifest_support import (
    build_coco_payload_from_yolo_segmentation_split,
    normalize_yolo_category_names,
)
from backend.service.application.models.yolov8_core.data import (
    build_yolov8_segmentation_training_batch,
)
from backend.service.application.models.yolov8_core.postprocess import (
    build_yolov8_segmentation_postprocess_instances,
    normalize_yolov8_segmentation_outputs,
    postprocess_yolov8_segmentation_prediction_array,
)
from backend.service.application.runtime.tasks.segmentation_model_runtime import (
    DefaultSegmentationModelRuntime,
)
from backend.service.application.runtime.contracts.segmentation.prediction import (
    SegmentationPredictionRequest,
)
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot
from backend.service.application.runtime.support.detection import batched_nms_indices
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class YoloV8SegmentationEvaluationRequest:
    """描述一次 YOLOv8 segmentation 数据集级评估请求。"""

    dataset_storage: LocalDatasetStorage
    runtime_target: RuntimeTargetSnapshot
    manifest_payload: dict[str, object]
    score_threshold: float = 0.001
    mask_threshold: float = 0.5
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
    )
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloV8SegmentationEvaluationResult:
    """描述一次 YOLOv8 segmentation 数据集级评估结果。"""

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


def run_yolov8_segmentation_evaluation(
    request: YoloV8SegmentationEvaluationRequest,
) -> YoloV8SegmentationEvaluationResult:
    """执行 YOLOv8 segmentation 数据集级评估。"""

    dataset_storage = request.dataset_storage
    runtime_target = request.runtime_target
    split_name, samples, label_names = _parse_yolov8_segmentation_manifest(
        request.manifest_payload,
        dataset_storage,
    )
    if not samples:
        return YoloV8SegmentationEvaluationResult(
            split_name=split_name,
            sample_count=0,
            duration_seconds=0.0,
            map50=0.0,
            map50_95=0.0,
            mask_map50=0.0,
            mask_map50_95=0.0,
        )

    runtime = DefaultSegmentationModelRuntime()
    session = runtime.load_session(
        dataset_storage=dataset_storage,
        runtime_target=runtime_target,
    )

    started = time.monotonic()
    gt_bbox_items: list[dict[str, object]] = []
    pred_bbox_items: list[dict[str, object]] = []
    gt_mask_items: list[dict[str, object]] = []
    pred_mask_items: list[dict[str, object]] = []
    predictions_payload: list[dict[str, object]] = []
    category_names = {index: name for index, name in enumerate(label_names)}

    for image_index, sample in enumerate(samples):
        image_path = sample["image_path"]
        gt_annotations = sample.get("annotations", [])
        resolved_image_path = dataset_storage.resolve(image_path) if image_path else None
        if resolved_image_path is None or not resolved_image_path.is_file():
            continue

        prediction_request = SegmentationPredictionRequest(
            score_threshold=request.score_threshold,
            mask_threshold=request.mask_threshold,
            save_result_image=False,
            input_image_bytes=resolved_image_path.read_bytes(),
        )
        try:
            prediction_result = session.predict(prediction_request)
        except Exception:
            continue

        image_width = int(prediction_result.image_width)
        image_height = int(prediction_result.image_height)
        for annotation in gt_annotations:
            category_id = int(annotation.get("category_id", 0))
            bbox = annotation.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4:
                x, y, width, height = (float(value) for value in bbox)
                gt_bbox_items.append(
                    {
                        "image_id": image_index,
                        "category_id": category_id,
                        "bbox_xyxy": [x, y, x + width, y + height],
                    },
                )
            mask = _build_yolov8_segmentation_annotation_mask(
                annotation=annotation,
                width=image_width,
                height=image_height,
            )
            if mask is not None:
                gt_mask_items.append(
                    {
                        "image_id": image_index,
                        "category_id": category_id,
                        "mask": mask,
                    },
                )

        for instance in prediction_result.instances:
            pred_bbox_items.append(
                {
                    "image_id": image_index,
                    "category_id": int(instance.class_id),
                    "bbox_xyxy": list(instance.bbox_xyxy),
                    "score": float(instance.score),
                },
            )
            mask = _build_yolov8_segmentation_instance_mask(
                segments=instance.segments,
                width=image_width,
                height=image_height,
            )
            if mask is not None:
                pred_mask_items.append(
                    {
                        "image_id": image_index,
                        "category_id": int(instance.class_id),
                        "mask": mask,
                        "score": float(instance.score),
                    },
                )

        predictions_payload.append(
            {
                "image_index": image_index,
                "image_path": str(image_path),
                "gt_count": len(gt_annotations),
                "pred_count": len(prediction_result.instances),
                "latency_ms": prediction_result.latency_ms,
            },
        )

    duration = time.monotonic() - started
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
    per_class_metrics = _merge_yolov8_segmentation_per_class_metrics(
        bbox_metrics=bbox_metrics.per_class_metrics,
        mask_metrics=mask_metrics.per_class_metrics,
    )
    sample_count = len(predictions_payload)
    report_payload = {
        "task_type": "segmentation",
        "model_type": runtime_target.model_type,
        "split_name": split_name,
        "sample_count": sample_count,
        "duration_seconds": round(duration, 3),
        "map50": round(bbox_metrics.ap50, 6),
        "map50_95": round(bbox_metrics.ap50_95, 6),
        "mask_map50": round(mask_metrics.ap50, 6),
        "mask_map50_95": round(mask_metrics.ap50_95, 6),
        "score_threshold": request.score_threshold,
        "mask_threshold": request.mask_threshold,
        "per_class_metrics": per_class_metrics,
    }
    return YoloV8SegmentationEvaluationResult(
        split_name=split_name,
        sample_count=sample_count,
        duration_seconds=duration,
        map50=bbox_metrics.ap50,
        map50_95=bbox_metrics.ap50_95,
        mask_map50=mask_metrics.ap50,
        mask_map50_95=mask_metrics.ap50_95,
        per_class_metrics=per_class_metrics,
        report_payload=report_payload,
        predictions_payload=predictions_payload,
    )


def _parse_yolov8_segmentation_manifest(
    manifest: dict[str, object],
    dataset_storage: LocalDatasetStorage,
) -> tuple[str, list[dict[str, object]], tuple[str, ...]]:
    """解析 YOLOv8 segmentation DatasetExport manifest。"""

    splits = manifest.get("splits", [])
    chosen_split: dict[str, object] | None = None
    for split in splits or []:
        if not isinstance(split, dict):
            continue
        split_name = str(split.get("name", "")).lower()
        if split_name in {"val", "valid", "validation", "test"}:
            chosen_split = split
            break
    if chosen_split is None and splits:
        chosen_split = next((item for item in splits if isinstance(item, dict)), None)
    if chosen_split is None:
        raise InvalidRequestError("YOLOv8 segmentation manifest 不包含可用 split")

    split_name = str(chosen_split.get("name", "unknown"))
    image_root = str(chosen_split.get("image_root", "")).strip()
    annotation_file = str(chosen_split.get("annotation_file", "")).strip()
    label_root = str(chosen_split.get("label_root", "")).strip()
    if annotation_file:
        annotation_payload = dataset_storage.read_json(annotation_file)
        if not isinstance(annotation_payload, dict):
            raise InvalidRequestError(
                "YOLOv8 segmentation annotation 文件格式无效",
                details={"annotation_file": annotation_file},
            )
        categories = annotation_payload.get("categories", [])
        label_names = tuple(
            str(category.get("name", category.get("id", "")))
            for category in categories
            if isinstance(category, dict)
        )
        return (
            split_name,
            _build_yolov8_segmentation_samples(
                image_root=image_root,
                payload=annotation_payload,
            ),
            label_names,
        )
    if label_root:
        category_names = normalize_yolo_category_names(
            category_names=manifest.get("category_names"),
            format_label="YOLOv8 segmentation",
        )
        image_root_path = dataset_storage.resolve(image_root)
        label_root_path = dataset_storage.resolve(label_root)
        if not image_root_path.is_dir():
            raise InvalidRequestError(
                "YOLOv8 segmentation 图片目录不存在",
                details={"image_root": image_root, "split_name": split_name},
            )
        if not label_root_path.is_dir():
            raise InvalidRequestError(
                "YOLOv8 segmentation 标签目录不存在",
                details={"label_root": label_root, "split_name": split_name},
            )
        payload = build_coco_payload_from_yolo_segmentation_split(
            split_name=split_name,
            image_root=image_root_path,
            label_root=label_root_path,
            category_names=category_names,
        )
        return (
            split_name,
            _build_yolov8_segmentation_samples(
                image_root=image_root,
                payload=payload,
            ),
            category_names,
        )
    categories = manifest.get("categories", [])
    label_names = tuple(
        str(category.get("name", category.get("id", "")))
        for category in categories
        if isinstance(category, dict)
    )
    return (
        split_name,
        _build_yolov8_segmentation_samples(
            image_root=image_root,
            payload=chosen_split,
        ),
        label_names,
    )


def _build_yolov8_segmentation_samples(
    *,
    image_root: str,
    payload: dict[str, object],
) -> list[dict[str, object]]:
    """把 COCO 风格 images / annotations 组装为 YOLOv8 segmentation 评估样本。"""

    images_by_id: dict[int, str] = {}
    for image_item in payload.get("images") or []:
        if isinstance(image_item, dict):
            images_by_id[int(image_item.get("id", -1))] = str(
                image_item.get("file_name", ""),
            )

    annotations_by_image: dict[int, list[dict[str, object]]] = {}
    for annotation in payload.get("annotations") or []:
        if isinstance(annotation, dict):
            image_id = int(annotation.get("image_id", -1))
            annotations_by_image.setdefault(image_id, []).append(annotation)

    samples: list[dict[str, object]] = []
    for image_id, file_name in images_by_id.items():
        full_path = f"{image_root}/{file_name}" if image_root else file_name
        samples.append(
            {
                "image_path": full_path,
                "annotations": annotations_by_image.get(image_id, []),
            },
        )
    return samples


def _build_yolov8_segmentation_annotation_mask(
    *,
    annotation: dict[str, object],
    width: int,
    height: int,
) -> Any:
    """把 YOLOv8 segmentation 标注 polygon 转换为二值 mask。"""

    polygons = _normalize_yolov8_segmentation_polygons(annotation.get("segmentation"))
    if not polygons:
        return None
    return _rasterize_yolov8_polygons(polygons=polygons, width=width, height=height)


def _build_yolov8_segmentation_instance_mask(
    *,
    segments: object,
    width: int,
    height: int,
) -> Any:
    """把 YOLOv8 segmentation 预测 polygon 转换为二值 mask。"""

    polygons: list[list[tuple[float, float]]] = []
    if not isinstance(segments, (list, tuple)):
        return None
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
    return _rasterize_yolov8_polygons(polygons=polygons, width=width, height=height)


def _normalize_yolov8_segmentation_polygons(
    segmentation: object,
) -> list[list[tuple[float, float]]]:
    """归一化 COCO polygon segmentation。"""

    polygons: list[list[tuple[float, float]]] = []
    if not isinstance(segmentation, list):
        return polygons
    raw_polygons = segmentation
    if raw_polygons and all(isinstance(value, int | float) for value in raw_polygons):
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


def _rasterize_yolov8_polygons(
    *,
    polygons: list[list[tuple[float, float]]],
    width: int,
    height: int,
) -> Any:
    """用 Pillow 把 polygon 列表栅格化为 NumPy bool mask。"""

    import numpy as np
    from PIL import Image, ImageDraw

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


def _merge_yolov8_segmentation_per_class_metrics(
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


def evaluate_yolov8_segmentation_samples(
    *,
    model: Any,
    samples: list[Any],
    labels: tuple[str, ...],
    input_size: tuple[int, int],
    device: str,
    precision: str,
    evaluation_confidence_threshold: float,
    evaluation_nms_threshold: float,
    imports: Any,
) -> dict[str, float]:
    """对少量验证样本执行 YOLOv8 segmentation 训练期评估。"""

    model.eval()
    gt_bbox_items: list[dict[str, object]] = []
    pred_bbox_items: list[dict[str, object]] = []
    gt_mask_items: list[dict[str, object]] = []
    pred_mask_items: list[dict[str, object]] = []
    total_predictions = 0
    evaluation_loader = build_yolo_task_evaluation_dataloader(
        torch_module=imports.torch,
        samples=samples,
        input_size=input_size,
        plan=resolve_yolo_task_evaluation_dataloader_plan(device=device),
        build_batch=build_yolov8_segmentation_training_batch,
        load_imports=load_yolo_task_dataloader_imports,
    )
    with imports.torch.no_grad():
        for image_index, batch in enumerate(evaluation_loader):
            if batch is None:
                continue
            batch = move_yolo_task_batch_to_device(
                batch=batch,
                device=device,
                precision=precision,
                torch_module=imports.torch,
            )
            with _yolov8_segmentation_autocast(imports, precision, device):
                outputs = model(batch.images)
            target = batch.targets[0]
            _append_yolov8_segmentation_gt_items(
                image_index=image_index,
                target=target,
                gt_bbox_items=gt_bbox_items,
                gt_mask_items=gt_mask_items,
                imports=imports,
            )
            bbox_items, mask_items, prediction_count = _build_yolov8_segmentation_prediction_items(
                outputs=outputs,
                labels=labels,
                input_size=input_size,
                score_threshold=evaluation_confidence_threshold,
                nms_threshold=evaluation_nms_threshold,
                mask_threshold=0.5,
                imports=imports,
                image_index=image_index,
            )
            pred_bbox_items.extend(bbox_items)
            pred_mask_items.extend(mask_items)
            total_predictions += prediction_count
    model.train()
    bbox_metrics = compute_coco_style_ap(
        gt_items=gt_bbox_items,
        pred_items=pred_bbox_items,
        category_names={index: name for index, name in enumerate(labels)},
        similarity_func=lambda pred, gt: bbox_iou_xyxy(
            pred["bbox_xyxy"],
            gt["bbox_xyxy"],
        ),
    )
    mask_metrics = compute_coco_style_ap(
        gt_items=gt_mask_items,
        pred_items=pred_mask_items,
        category_names={index: name for index, name in enumerate(labels)},
        similarity_func=lambda pred, gt: mask_iou(pred["mask"], gt["mask"]),
    )
    primary_metrics = mask_metrics if gt_mask_items and pred_mask_items else bbox_metrics
    return {
        "map50": round(primary_metrics.ap50, 6),
        "map50_95": round(primary_metrics.ap50_95, 6),
        "bbox_map50": round(bbox_metrics.ap50, 6),
        "bbox_map50_95": round(bbox_metrics.ap50_95, 6),
        "mask_map50": round(mask_metrics.ap50, 6),
        "mask_map50_95": round(mask_metrics.ap50_95, 6),
        "prediction_count": float(total_predictions),
    }


def _append_yolov8_segmentation_gt_items(
    *,
    image_index: int,
    target: dict[str, Any],
    gt_bbox_items: list[dict[str, object]],
    gt_mask_items: list[dict[str, object]],
    imports: Any,
) -> None:
    """把训练 batch target 转成 COCO-style AP 的 GT 项。"""

    boxes = list(target.get("boxes", []))
    class_ids = list(target.get("class_ids", []))
    masks = _yolov8_segmentation_tensor_to_np(target.get("masks"), imports) if target.get("masks") is not None else None
    mask_valid = (
        _yolov8_segmentation_tensor_to_np(target.get("mask_valid"), imports).astype(bool)
        if target.get("mask_valid") is not None
        else None
    )
    for object_index, (box, class_id) in enumerate(zip(boxes, class_ids, strict=True)):
        gt_bbox_items.append(
            {
                "image_id": image_index,
                "category_id": int(class_id),
                "bbox_xyxy": [float(value) for value in box],
            }
        )
        if masks is None:
            continue
        if mask_valid is not None and object_index < int(mask_valid.shape[0]) and not bool(mask_valid[object_index]):
            continue
        gt_mask_items.append(
            {
                "image_id": image_index,
                "category_id": int(class_id),
                "mask": masks[object_index] > 0.5,
            }
        )


def _build_yolov8_segmentation_prediction_items(
    *,
    outputs: Any,
    labels: tuple[str, ...],
    input_size: tuple[int, int],
    score_threshold: float,
    nms_threshold: float,
    mask_threshold: float,
    imports: Any,
    image_index: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]], int]:
    """把 YOLOv8 segmentation 输出转成 bbox / mask AP 预测项。"""

    bbox_items: list[dict[str, object]] = []
    mask_items: list[dict[str, object]] = []
    try:
        prediction_array, proto_array = normalize_yolov8_segmentation_outputs(
            outputs=outputs,
            np_module=imports.np,
        )
        letterbox_transform = build_yolo_letterbox_transform(
            source_width=int(input_size[1]),
            source_height=int(input_size[0]),
            input_size=input_size,
        )
        instances = build_yolov8_segmentation_postprocess_instances(
            cv2_module=imports.cv2,
            np_module=imports.np,
            prediction_array=prediction_array,
            proto_array=proto_array,
            labels=labels,
            score_threshold=score_threshold,
            nms_threshold=nms_threshold,
            mask_threshold=mask_threshold,
            letterbox_transform=letterbox_transform,
            nms_indices_func=batched_nms_indices,
        )
        for instance in instances:
            bbox_items.append(
                {
                    "image_id": image_index,
                    "category_id": int(instance.class_id),
                    "bbox_xyxy": list(instance.bbox_xyxy),
                    "score": float(instance.score),
                }
            )
            mask = _build_yolov8_segmentation_instance_mask(
                segments=instance.segments,
                width=int(input_size[1]),
                height=int(input_size[0]),
            )
            if mask is not None:
                mask_items.append(
                    {
                        "image_id": image_index,
                        "category_id": int(instance.class_id),
                        "mask": mask,
                        "score": float(instance.score),
                    }
                )
        return bbox_items, mask_items, len(instances)
    except Exception:
        prediction_array = _yolov8_segmentation_tensor_to_np(
            outputs[0] if isinstance(outputs, tuple) else outputs,
            imports,
        )
    if prediction_array.ndim < 3:
        return bbox_items, mask_items, 0
    postprocess_results = postprocess_yolov8_segmentation_prediction_array(
        prediction_array=prediction_array,
        np_module=imports.np,
        num_classes=len(labels),
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        nms_indices_func=batched_nms_indices,
    )
    prediction = postprocess_results[0] if postprocess_results else None
    if prediction is None or int(prediction.scores.shape[0]) == 0:
        return bbox_items, mask_items, 0
    for box, score, class_id in zip(
        prediction.boxes_xyxy,
        prediction.scores,
        prediction.class_ids,
        strict=True,
    ):
        bbox_items.append(
            {
                "image_id": image_index,
                "category_id": int(class_id),
                "bbox_xyxy": [float(value) for value in box],
                "score": float(score),
            }
        )
    return bbox_items, mask_items, int(prediction.scores.shape[0])


def _yolov8_segmentation_autocast(imports: Any, precision: str, device: str):
    """返回 YOLOv8 segmentation 训练期评估使用的 autocast 上下文。"""

    if precision != "fp16":
        return nullcontext()
    amp = getattr(imports.torch, "amp", None)
    if amp is not None and hasattr(amp, "autocast"):
        device_type = "cuda" if str(device).startswith("cuda") else "cpu"
        return amp.autocast(device_type=device_type, enabled=True)
    autocast = getattr(imports.torch.cuda, "amp", None)
    if autocast is not None and hasattr(autocast, "autocast"):
        return autocast.autocast(enabled=True)
    return nullcontext()


def _yolov8_segmentation_tensor_to_np(tensor: Any, imports: Any) -> Any:
    """把 YOLOv8 segmentation tensor 输出转换为 NumPy 数组。"""

    if hasattr(tensor, "detach"):
        tensor = tensor.detach()
    if hasattr(tensor, "cpu"):
        tensor = tensor.cpu()
    if hasattr(tensor, "numpy"):
        tensor = tensor.numpy()
    array = imports.np.asarray(tensor, dtype=imports.np.float32)
    if array.ndim == 2:
        array = imports.np.expand_dims(array, axis=0)
    return array


__all__ = [
    "YoloV8SegmentationEvaluationRequest",
    "YoloV8SegmentationEvaluationResult",
    "evaluate_yolov8_segmentation_samples",
    "run_yolov8_segmentation_evaluation",
]
