"""COCO-style 评估指标工具。"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Callable

from backend.service.application.models.evaluation.pycocotools_metrics import (
    YOLO_DETECTION_COCO_MAX_DETECTIONS,
    evaluate_pycocotools_average_precision,
)


@dataclass(frozen=True)
class CocoStyleMetricResult:
    """描述一组 COCO-style AP 指标。"""

    ap50: float
    ap50_95: float
    per_class_metrics: list[dict[str, object]] = field(default_factory=list)


def resolve_segmentation_primary_metrics(
    *,
    bbox_metrics: CocoStyleMetricResult,
    mask_metrics: CocoStyleMetricResult,
    has_ground_truth_masks: bool,
) -> CocoStyleMetricResult:
    """选择 segmentation best-checkpoint 使用的主指标。

    只要验证集声明了实例 mask，主指标就必须是 mask AP。模型没有生成任何
    mask 时，``mask_metrics`` 会自然得到 0；不得回退到 bbox AP，否则会把
    segmentation head 失效的模型错误登记为 best checkpoint。
    """

    return mask_metrics if has_ground_truth_masks else bbox_metrics


SimilarityFunc = Callable[[dict[str, object], dict[str, object]], float]


def limit_segmentation_prediction_instances(
    instances: Any,
    *,
    max_detections: int = YOLO_DETECTION_COCO_MAX_DETECTIONS,
) -> tuple[Any, ...]:
    """在生成 dense mask 前按置信度限制单图候选数量。"""

    resolved_max_detections = int(max_detections)
    if resolved_max_detections < 1:
        raise ValueError("max_detections 必须大于等于 1")
    return tuple(
        sorted(
            tuple(instances),
            key=lambda instance: float(getattr(instance, "score", 0.0)),
            reverse=True,
        )[:resolved_max_detections]
    )


def encode_binary_mask_to_coco_rle(mask: object) -> dict[str, object]:
    """把单个 dense binary mask 立即压缩为 JSON-safe COCO RLE。

    训练期验证可能为每张图保留数百个候选。如果把 ``H×W`` dense mask
    保存到整个 split 结束，内存占用会随 ``image_count × maxDets × H × W``
    线性增长。这里在单图后处理阶段立即压缩，并把 pycocotools 返回的
    ``bytes`` counts 转为可持久化的 ASCII 字符串。
    """

    import numpy as np

    try:
        from pycocotools import mask as coco_mask
    except ImportError as error:  # pragma: no cover - 由调用环境依赖测试覆盖
        raise RuntimeError("segmentation COCO AP 评估需要 pycocotools") from error

    array = np.asarray(mask, dtype=np.uint8)
    if array.ndim != 2:
        raise ValueError("COCO RLE 仅支持二维 binary mask")
    encoded = coco_mask.encode(np.asfortranarray(array))
    counts = encoded.get("counts")
    if isinstance(counts, bytes):
        counts = counts.decode("ascii")
    return {
        "size": [int(value) for value in encoded["size"]],
        "counts": str(counts),
    }


def resize_binary_mask_for_coco_evaluation(
    *,
    binary_mask: Any,
    image_size: tuple[int, int],
    cv2_module: Any,
    np_module: Any,
) -> Any:
    """把训练期下采样 mask 恢复到 COCO image 的 H×W 尺寸。"""

    mask = np_module.asarray(binary_mask)
    if mask.ndim != 2:
        raise ValueError("COCO evaluation binary mask 必须是二维数组")
    target_height, target_width = (int(value) for value in image_size)
    if target_height < 1 or target_width < 1:
        raise ValueError("COCO evaluation image_size 必须包含正整数")
    if tuple(mask.shape) == (target_height, target_width):
        return (mask > 0).astype(np_module.uint8, copy=False)
    resized = cv2_module.resize(
        mask.astype(np_module.uint8, copy=False),
        (target_width, target_height),
        interpolation=cv2_module.INTER_NEAREST,
    )
    return (resized > 0).astype(np_module.uint8, copy=False)


def encode_coco_polygons_to_rle(
    segments: object,
    *,
    width: int,
    height: int,
) -> dict[str, object] | None:
    """用 pycocotools C 路径把预测 polygon 直接转换为 compressed RLE。"""

    try:
        from pycocotools import mask as coco_mask
    except ImportError as error:  # pragma: no cover - 由调用环境依赖测试覆盖
        raise RuntimeError("segmentation COCO AP 评估需要 pycocotools") from error

    polygons: list[list[float]] = []
    if not isinstance(segments, (list, tuple)):
        return None
    for segment in segments:
        if not isinstance(segment, (list, tuple)):
            continue
        flattened: list[float] = []
        for point in segment:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                flattened.extend((float(point[0]), float(point[1])))
        if len(flattened) >= 6:
            polygons.append(flattened)
    if not polygons:
        return None
    rles = coco_mask.frPyObjects(polygons, int(height), int(width))
    encoded = coco_mask.merge(rles) if isinstance(rles, list) else rles
    counts = encoded.get("counts")
    if isinstance(counts, bytes):
        counts = counts.decode("ascii")
    return {
        "size": [int(value) for value in encoded["size"]],
        "counts": str(counts),
    }


def compute_pycocotools_segmentation_ap(
    *,
    gt_bbox_items: list[dict[str, object]],
    pred_bbox_items: list[dict[str, object]],
    gt_mask_items: list[dict[str, object]],
    pred_mask_items: list[dict[str, object]],
    category_names: dict[int, str],
    image_count: int,
    image_size: tuple[int, int],
    max_detections_per_image: int = YOLO_DETECTION_COCO_MAX_DETECTIONS,
) -> tuple[CocoStyleMetricResult, CocoStyleMetricResult]:
    """用真实 pycocotools 统一计算 segmentation bbox AP 与 mask AP。

    输入 mask 必须已经是 compressed COCO RLE，避免本函数及其调用方在
    split 级别保存 dense mask。bbox 与 mask 各自构建只包含有效标注的
    COCO ground truth，确保缺少实例 mask 时不会把 bbox 标注误作 mask。
    """

    if image_count < 1:
        raise ValueError("image_count 必须大于等于 1")
    height, width = (int(value) for value in image_size)
    if height < 1 or width < 1:
        raise ValueError("image_size 必须包含有限的正整数")
    if not category_names:
        raise ValueError("category_names 不能为空")

    try:
        from pycocotools.coco import COCO
        from pycocotools.cocoeval import COCOeval
        from pycocotools import mask as coco_mask
    except ImportError as error:  # pragma: no cover - 由调用环境依赖测试覆盖
        raise RuntimeError("segmentation COCO AP 评估需要 pycocotools") from error

    images = [
        {"id": image_id, "width": width, "height": height}
        for image_id in range(image_count)
    ]
    categories = [
        {"id": int(category_id), "name": str(category_name)}
        for category_id, category_name in sorted(category_names.items())
    ]
    bbox_ground_truth = _build_pycocotools_ground_truth(
        coco_class=COCO,
        images=images,
        categories=categories,
        items=gt_bbox_items,
        annotation_builder=lambda annotation_id, item: {
            "id": annotation_id,
            "image_id": int(item["image_id"]),
            "category_id": int(item["category_id"]),
            "bbox": _xyxy_to_xywh(item["bbox_xyxy"]),
            "area": _xyxy_area(item["bbox_xyxy"]),
            "iscrowd": 0,
        },
    )
    mask_ground_truth = _build_pycocotools_ground_truth(
        coco_class=COCO,
        images=images,
        categories=categories,
        items=gt_mask_items,
        annotation_builder=lambda annotation_id, item: _build_coco_mask_annotation(
            annotation_id=annotation_id,
            item=item,
            coco_mask=coco_mask,
        ),
    )
    bbox_detections = [
        {
            "image_id": int(item["image_id"]),
            "category_id": int(item["category_id"]),
            "bbox": _xyxy_to_xywh(item["bbox_xyxy"]),
            "score": float(item.get("score", 0.0)),
        }
        for item in pred_bbox_items
    ]
    mask_detections = [
        {
            "image_id": int(item["image_id"]),
            "category_id": int(item["category_id"]),
            "segmentation": _require_coco_rle(item),
            "score": float(item.get("score", 0.0)),
        }
        for item in pred_mask_items
    ]
    bbox_average_precision = evaluate_pycocotools_average_precision(
        ground_truth=bbox_ground_truth,
        detections=bbox_detections,
        cocoeval_class=COCOeval,
        iou_type="bbox",
        max_detections=max_detections_per_image,
    )
    mask_average_precision = evaluate_pycocotools_average_precision(
        ground_truth=mask_ground_truth,
        detections=mask_detections,
        cocoeval_class=COCOeval,
        iou_type="segm",
        max_detections=max_detections_per_image,
    )
    return (
        _convert_pycocotools_metric_result(
            average_precision=bbox_average_precision,
            gt_items=gt_bbox_items,
            pred_items=pred_bbox_items,
        ),
        _convert_pycocotools_metric_result(
            average_precision=mask_average_precision,
            gt_items=gt_mask_items,
            pred_items=pred_mask_items,
        ),
    )


def compute_pycocotools_detection_ap(
    *,
    gt_items: list[dict[str, object]],
    pred_items: list[dict[str, object]],
    category_names: dict[int, str],
    image_count: int,
    max_detections_per_image: int = YOLO_DETECTION_COCO_MAX_DETECTIONS,
) -> CocoStyleMetricResult:
    """用真实 pycocotools 计算规范 bbox AP。"""

    if image_count < 1:
        raise ValueError("image_count 必须大于等于 1")
    if not category_names:
        raise ValueError("category_names 不能为空")
    try:
        from pycocotools.coco import COCO
        from pycocotools.cocoeval import COCOeval
    except ImportError as error:  # pragma: no cover - 由调用环境依赖测试覆盖
        raise RuntimeError("detection COCO AP 评估需要 pycocotools") from error

    ground_truth = _build_pycocotools_ground_truth(
        coco_class=COCO,
        images=[{"id": image_id} for image_id in range(image_count)],
        categories=[
            {"id": int(category_id), "name": str(category_name)}
            for category_id, category_name in sorted(category_names.items())
        ],
        items=gt_items,
        annotation_builder=lambda annotation_id, item: {
            "id": annotation_id,
            "image_id": int(item["image_id"]),
            "category_id": int(item["category_id"]),
            "bbox": _xyxy_to_xywh(item["bbox_xyxy"]),
            "area": _xyxy_area(item["bbox_xyxy"]),
            "iscrowd": 0,
        },
    )
    detections = [
        {
            "image_id": int(item["image_id"]),
            "category_id": int(item["category_id"]),
            "bbox": _xyxy_to_xywh(item["bbox_xyxy"]),
            "score": float(item.get("score", 0.0)),
        }
        for item in pred_items
    ]
    average_precision = evaluate_pycocotools_average_precision(
        ground_truth=ground_truth,
        detections=detections,
        cocoeval_class=COCOeval,
        iou_type="bbox",
        max_detections=max_detections_per_image,
    )
    return _convert_pycocotools_metric_result(
        average_precision=average_precision,
        gt_items=gt_items,
        pred_items=pred_items,
    )


def compute_pycocotools_pose_ap(
    *,
    gt_items: list[dict[str, object]],
    pred_items: list[dict[str, object]],
    category_names: dict[int, str],
    image_count: int,
    keypoint_count: int,
    keypoint_oks_sigmas: tuple[float, ...],
    max_detections_per_image: int = YOLO_DETECTION_COCO_MAX_DETECTIONS,
) -> CocoStyleMetricResult:
    """用真实 pycocotools 计算 pose keypoints AP。"""

    if image_count < 1:
        raise ValueError("image_count 必须大于等于 1")
    if keypoint_count < 1:
        raise ValueError("keypoint_count 必须大于等于 1")
    if len(keypoint_oks_sigmas) != keypoint_count:
        raise ValueError("keypoint_oks_sigmas 数量必须与 keypoint_count 一致")
    if not category_names:
        raise ValueError("category_names 不能为空")

    try:
        from pycocotools.coco import COCO
        from pycocotools.cocoeval import COCOeval
    except ImportError as error:  # pragma: no cover - 由调用环境依赖测试覆盖
        raise RuntimeError("pose COCO AP 评估需要 pycocotools") from error

    keypoint_names = [f"keypoint_{index}" for index in range(keypoint_count)]
    ground_truth = _build_pycocotools_ground_truth(
        coco_class=COCO,
        images=[{"id": image_id} for image_id in range(image_count)],
        categories=[
            {
                "id": int(category_id),
                "name": str(category_name),
                "keypoints": keypoint_names,
                "skeleton": [],
            }
            for category_id, category_name in sorted(category_names.items())
        ],
        items=gt_items,
        annotation_builder=_build_coco_pose_annotation,
    )
    detections = [
        {
            "image_id": int(item["image_id"]),
            "category_id": int(item["category_id"]),
            "keypoints": _require_coco_keypoints(
                item,
                keypoint_count=keypoint_count,
            ),
            "score": float(item.get("score", 0.0)),
        }
        for item in pred_items
    ]
    average_precision = evaluate_pycocotools_average_precision(
        ground_truth=ground_truth,
        detections=detections,
        cocoeval_class=COCOeval,
        iou_type="keypoints",
        max_detections=max_detections_per_image,
        keypoint_oks_sigmas=keypoint_oks_sigmas,
    )
    return _convert_pycocotools_metric_result(
        average_precision=average_precision,
        gt_items=gt_items,
        pred_items=pred_items,
    )


def _build_pycocotools_ground_truth(
    *,
    coco_class: Any,
    images: list[dict[str, object]],
    categories: list[dict[str, object]],
    items: list[dict[str, object]],
    annotation_builder: Callable[[int, dict[str, object]], dict[str, object]],
) -> Any:
    """从已经规范化的轻量项构建内存 COCO ground truth。"""

    from contextlib import redirect_stdout
    import io

    ground_truth = coco_class()
    ground_truth.dataset = {
        "info": {"description": "amvision training evaluation"},
        "images": images,
        "categories": categories,
        "annotations": [
            annotation_builder(annotation_id, item)
            for annotation_id, item in enumerate(items, start=1)
        ],
    }
    with redirect_stdout(io.StringIO()):
        ground_truth.createIndex()
    return ground_truth


def _build_coco_mask_annotation(
    *,
    annotation_id: int,
    item: dict[str, object],
    coco_mask: Any,
) -> dict[str, object]:
    """构建包含 RLE、area 与 bbox 的 COCO mask 标注。"""

    rle = _require_coco_rle(item)
    area = float(coco_mask.area(rle))
    bbox = [float(value) for value in coco_mask.toBbox(rle)]
    return {
        "id": annotation_id,
        "image_id": int(item["image_id"]),
        "category_id": int(item["category_id"]),
        "segmentation": rle,
        "bbox": bbox,
        "area": area,
        "iscrowd": 0,
    }


def _build_coco_pose_annotation(
    annotation_id: int,
    item: dict[str, object],
) -> dict[str, object]:
    """构建 pycocotools keypoints ground-truth 标注。"""

    keypoints = [float(value) for value in item.get("keypoints", ())]
    if not keypoints or len(keypoints) % 3 != 0:
        raise ValueError("pose ground truth keypoints 必须是非空的 x/y/v 三元组")
    box = _resolve_pose_bbox_xywh(item=item, keypoints=keypoints)
    area = float(item.get("area", box[2] * box[3]))
    if not math.isfinite(area) or area <= 0.0:
        raise ValueError("pose ground truth area 必须是有限正数")
    return {
        "id": annotation_id,
        "image_id": int(item["image_id"]),
        "category_id": int(item["category_id"]),
        "keypoints": keypoints,
        "num_keypoints": sum(keypoints[index] > 0.0 for index in range(2, len(keypoints), 3)),
        "bbox": box,
        "area": area,
        "iscrowd": 0,
    }


def _resolve_pose_bbox_xywh(
    *,
    item: dict[str, object],
    keypoints: list[float],
) -> list[float]:
    """读取 pose bbox；缺失时仅从可见关键点构建。"""

    bbox_xyxy = item.get("bbox_xyxy")
    if isinstance(bbox_xyxy, (list, tuple)) and len(bbox_xyxy) == 4:
        return _xyxy_to_xywh(bbox_xyxy)
    visible_points = [
        (keypoints[index], keypoints[index + 1])
        for index in range(0, len(keypoints), 3)
        if keypoints[index + 2] > 0.0
    ]
    if not visible_points:
        raise ValueError("pose ground truth 缺少 bbox 且没有可见关键点")
    xs = [point[0] for point in visible_points]
    ys = [point[1] for point in visible_points]
    return [min(xs), min(ys), max(max(xs) - min(xs), 1.0), max(max(ys) - min(ys), 1.0)]


def _require_coco_keypoints(
    item: dict[str, object],
    *,
    keypoint_count: int,
) -> list[float]:
    """读取并校验预测 keypoints 数量和有限性。"""

    keypoints = [float(value) for value in item.get("keypoints", ())]
    if len(keypoints) != keypoint_count * 3:
        raise ValueError("pose prediction keypoints 数量与 keypoint_count 不一致")
    if not all(math.isfinite(value) for value in keypoints):
        raise ValueError("pose prediction keypoints 必须全部为有限数")
    return keypoints


def _require_coco_rle(item: dict[str, object]) -> dict[str, object]:
    """读取并校验 item 中已经压缩的 COCO RLE。"""

    rle = item.get("segmentation")
    if not isinstance(rle, dict) or "size" not in rle or "counts" not in rle:
        raise ValueError("segmentation item 缺少 compressed COCO RLE")
    return rle


def _xyxy_to_xywh(box: object) -> list[float]:
    """把 xyxy box 转为 COCO xywh。"""

    values = [float(value) for value in box]  # type: ignore[arg-type]
    if len(values) != 4:
        raise ValueError("bbox_xyxy 必须包含 4 个值")
    return [
        values[0],
        values[1],
        max(0.0, values[2] - values[0]),
        max(0.0, values[3] - values[1]),
    ]


def _xyxy_area(box: object) -> float:
    """返回 xyxy box 的非负面积。"""

    _x, _y, width, height = _xyxy_to_xywh(box)
    return width * height


def _convert_pycocotools_metric_result(
    *,
    average_precision: Any,
    gt_items: list[dict[str, object]],
    pred_items: list[dict[str, object]],
) -> CocoStyleMetricResult:
    """把共享 pycocotools 指标转为现有训练公开结构。"""

    per_class_metrics = []
    for category_metric in average_precision.per_category:
        category_id = int(category_metric.category_id)
        per_class_metrics.append(
            {
                "category_id": category_id,
                "category_name": str(category_metric.category_name),
                "gt_count": sum(
                    int(item.get("category_id", -1)) == category_id
                    for item in gt_items
                ),
                "pred_count": sum(
                    int(item.get("category_id", -1)) == category_id
                    for item in pred_items
                ),
                "ap50": category_metric.map50,
                "ap50_95": category_metric.map50_95,
            }
        )
    return CocoStyleMetricResult(
        ap50=float(average_precision.map50),
        ap50_95=float(average_precision.map50_95),
        per_class_metrics=per_class_metrics,
    )


def compute_coco_style_ap(
    *,
    gt_items: list[dict[str, object]],
    pred_items: list[dict[str, object]],
    category_names: dict[int, str] | None = None,
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
    ),
    max_detections_per_image: int = 300,
    similarity_func: SimilarityFunc,
) -> CocoStyleMetricResult:
    """按类别计算 COCO-style AP。

    该函数只负责 AP 插值和匹配流程；bbox、mask、OKS 或 rotated IoU
    的具体相似度由调用方传入。
    """

    if not gt_items:
        return CocoStyleMetricResult(ap50=0.0, ap50_95=0.0)

    categories = sorted(
        {int(item["category_id"]) for item in gt_items if "category_id" in item},
    )
    per_class_metrics: list[dict[str, object]] = []
    ap50_values: list[float] = []
    ap50_95_values: list[float] = []
    limited_pred_items = _limit_predictions_per_image_and_category(
        pred_items,
        max_detections_per_image=max_detections_per_image,
    )

    for category_id in categories:
        class_gt = [
            item for item in gt_items if int(item.get("category_id", -1)) == category_id
        ]
        class_pred = [
            item
            for item in limited_pred_items
            if int(item.get("category_id", -1)) == category_id
        ]
        if not class_gt:
            continue

        threshold_aps = [
            _compute_ap_at_threshold(
                gt_items=class_gt,
                pred_items=class_pred,
                threshold=threshold,
                similarity_func=similarity_func,
            )
            for threshold in iou_thresholds
        ]
        ap50 = threshold_aps[0] if threshold_aps else 0.0
        ap50_95 = sum(threshold_aps) / max(len(threshold_aps), 1)
        ap50_values.append(ap50)
        ap50_95_values.append(ap50_95)
        per_class_metrics.append(
            {
                "category_id": category_id,
                "category_name": (category_names or {}).get(
                    category_id, str(category_id)
                ),
                "gt_count": len(class_gt),
                "pred_count": len(class_pred),
                "ap50": ap50,
                "ap50_95": ap50_95,
            },
        )

    return CocoStyleMetricResult(
        ap50=sum(ap50_values) / max(len(ap50_values), 1),
        ap50_95=sum(ap50_95_values) / max(len(ap50_95_values), 1),
        per_class_metrics=per_class_metrics,
    )


def _limit_predictions_per_image_and_category(
    pred_items: list[dict[str, object]],
    *,
    max_detections_per_image: int,
) -> list[dict[str, object]]:
    """按 COCO evaluator 语义限制每张图、每个类别的预测数。

    COCOeval 的 ``evaluateImg`` 以 ``(image_id, category_id)`` 为单位应用
    ``maxDets``。如果先跨类别截断，某个类别的高分误检会错误挤掉另一个
    类别的有效预测，产生与标准 COCO AP 不一致的结果。
    """

    if max_detections_per_image < 1:
        raise ValueError("max_detections_per_image 必须大于等于 1")
    predictions_by_group: dict[tuple[int, int], list[dict[str, object]]] = {}
    for item in pred_items:
        image_id = int(item.get("image_id", -1))
        category_id = int(item.get("category_id", -1))
        predictions_by_group.setdefault((image_id, category_id), []).append(item)

    limited: list[dict[str, object]] = []
    for group_predictions in predictions_by_group.values():
        limited.extend(
            sorted(
                group_predictions,
                key=lambda item: float(item.get("score", 0.0)),
                reverse=True,
            )[:max_detections_per_image]
        )
    return limited


def _compute_ap_at_threshold(
    *,
    gt_items: list[dict[str, object]],
    pred_items: list[dict[str, object]],
    threshold: float,
    similarity_func: SimilarityFunc,
) -> float:
    """计算单类别、单阈值下的 101 点插值 AP。"""

    if not gt_items or not pred_items:
        return 0.0

    gt_by_image: dict[int, list[tuple[int, dict[str, object]]]] = {}
    for global_gt_index, gt_item in enumerate(gt_items):
        image_id = int(gt_item.get("image_id", -1))
        gt_by_image.setdefault(image_id, []).append((global_gt_index, gt_item))

    matched_gt: set[int] = set()
    true_positives: list[int] = []
    false_positives: list[int] = []
    tp_count = 0
    fp_count = 0

    sorted_predictions = sorted(
        pred_items,
        key=lambda item: float(item.get("score", 0.0)),
        reverse=True,
    )
    for pred_item in sorted_predictions:
        image_id = int(pred_item.get("image_id", -1))
        best_score = 0.0
        best_gt_index = -1
        for global_gt_index, gt_item in gt_by_image.get(image_id, []):
            if global_gt_index in matched_gt:
                continue
            score = similarity_func(pred_item, gt_item)
            if score > best_score:
                best_score = score
                best_gt_index = global_gt_index
        if best_score >= threshold and best_gt_index >= 0:
            tp_count += 1
            matched_gt.add(best_gt_index)
        else:
            fp_count += 1
        true_positives.append(tp_count)
        false_positives.append(fp_count)

    if not true_positives:
        return 0.0

    precisions: list[float] = []
    recalls: list[float] = []
    for tp_value, fp_value in zip(true_positives, false_positives, strict=True):
        precisions.append(tp_value / max(tp_value + fp_value, 1))
        recalls.append(tp_value / max(len(gt_items), 1))

    interpolated: list[float] = []
    for index in range(101):
        recall_threshold = index / 100.0
        best_precision = 0.0
        for precision, recall in zip(precisions, recalls, strict=True):
            if recall >= recall_threshold and precision > best_precision:
                best_precision = precision
        interpolated.append(best_precision)
    return sum(interpolated) / 101.0


def bbox_iou_xyxy(
    box1: tuple[float, float, float, float] | list[float],
    box2: tuple[float, float, float, float] | list[float],
) -> float:
    """计算两个 xyxy bbox 的 IoU。"""

    x1 = max(float(box1[0]), float(box2[0]))
    y1 = max(float(box1[1]), float(box2[1]))
    x2 = min(float(box1[2]), float(box2[2]))
    y2 = min(float(box1[3]), float(box2[3]))
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area1 = max(0.0, float(box1[2]) - float(box1[0])) * max(
        0.0, float(box1[3]) - float(box1[1])
    )
    area2 = max(0.0, float(box2[2]) - float(box2[0])) * max(
        0.0, float(box2[3]) - float(box2[1])
    )
    return intersection / max(area1 + area2 - intersection, 1e-8)


def mask_iou(mask1: object, mask2: object) -> float:
    """计算两个二值 mask 的 IoU。"""

    import numpy as np

    left = np.asarray(mask1, dtype=bool)
    right = np.asarray(mask2, dtype=bool)
    if left.shape != right.shape:
        return 0.0
    intersection = np.logical_and(left, right).sum()
    union = np.logical_or(left, right).sum()
    return float(intersection / max(float(union), 1.0))


def compute_object_keypoint_similarity(
    gt_keypoints: list[float] | tuple[float, ...],
    pred_keypoints: list[float] | tuple[float, ...],
    *,
    area: float,
    sigmas: tuple[float, ...] | None = None,
) -> float:
    """计算 COCO Object Keypoint Similarity。"""

    if not gt_keypoints or not pred_keypoints:
        return 0.0
    resolved_sigmas = sigmas or default_coco_keypoint_sigmas()
    keypoint_count = min(len(gt_keypoints) // 3, len(pred_keypoints) // 3)
    if keypoint_count <= 0:
        return 0.0

    oks_sum = 0.0
    visible_count = 0
    for keypoint_index in range(keypoint_count):
        base_index = keypoint_index * 3
        gt_visibility = float(gt_keypoints[base_index + 2])
        if gt_visibility <= 0.0:
            continue
        dx = float(gt_keypoints[base_index]) - float(pred_keypoints[base_index])
        dy = float(gt_keypoints[base_index + 1]) - float(pred_keypoints[base_index + 1])
        sigma = (
            resolved_sigmas[keypoint_index]
            if keypoint_index < len(resolved_sigmas)
            else 0.05
        )
        # COCO OKS: exp(-d² / (((2 * sigma)²) * area * 2))。
        denominator = 8.0 * (sigma**2) * max(float(area), 1.0)
        oks_sum += math.exp(-((dx * dx + dy * dy) / max(denominator, 1e-8)))
        visible_count += 1
    if visible_count <= 0:
        return 0.0
    return oks_sum / visible_count


def default_coco_keypoint_sigmas() -> tuple[float, ...]:
    """返回 COCO person 17 点默认 OKS sigma。"""

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


def resolve_keypoint_oks_sigmas(num_keypoints: int) -> tuple[float, ...]:
    """按 Ultralytics 规则解析当前 pose 拓扑的 OKS sigma。

    COCO person 的 17 点拓扑使用官方 sigma；其他拓扑没有通用的解剖学
    sigma 定义，参考实现使用 ``1 / num_keypoints`` 的等权配置。显式返回
    与关键点数量等长的数组，避免 21 点等任务静默复用 17 点配置。
    """

    resolved_count = int(num_keypoints)
    if resolved_count < 1:
        raise ValueError("num_keypoints 必须大于等于 1")
    coco_sigmas = default_coco_keypoint_sigmas()
    if resolved_count == len(coco_sigmas):
        return coco_sigmas
    sigma = 1.0 / float(resolved_count)
    return tuple(sigma for _ in range(resolved_count))


def rotated_iou_xywhr(
    box1: list[float] | tuple[float, ...],
    box2: list[float] | tuple[float, ...],
) -> float:
    """按 xywhr 旋转框计算 rotated IoU。"""

    return polygon_iou(
        xywhr_to_polygon(box1),
        xywhr_to_polygon(box2),
    )


def xywhr_to_polygon(
    box: list[float] | tuple[float, ...],
) -> list[tuple[float, float]]:
    """把 xywhr 旋转框转换为四点 polygon。"""

    cx, cy, width, height, angle = (float(value) for value in box[:5])
    # 平台统一 xywhr contract 的 angle 始终为弧度；禁止按数值大小猜测单位。
    cos_value = math.cos(angle)
    sin_value = math.sin(angle)
    half_width = width / 2.0
    half_height = height / 2.0
    corners = (
        (-half_width, -half_height),
        (half_width, -half_height),
        (half_width, half_height),
        (-half_width, half_height),
    )
    return [
        (
            cx + x_offset * cos_value - y_offset * sin_value,
            cy + x_offset * sin_value + y_offset * cos_value,
        )
        for x_offset, y_offset in corners
    ]


def polygon_iou(
    polygon1: list[tuple[float, float]],
    polygon2: list[tuple[float, float]],
) -> float:
    """计算两个凸 polygon 的 IoU。"""

    try:
        import cv2
        import numpy as np
    except ImportError:
        return bbox_iou_xyxy(
            polygon_bounds_xyxy(polygon1), polygon_bounds_xyxy(polygon2)
        )

    left = np.asarray(polygon1, dtype=np.float32)
    right = np.asarray(polygon2, dtype=np.float32)
    if left.shape[0] < 3 or right.shape[0] < 3:
        return 0.0
    left_area = float(abs(cv2.contourArea(left)))
    right_area = float(abs(cv2.contourArea(right)))
    if left_area <= 0.0 or right_area <= 0.0:
        return 0.0
    _status, intersection = cv2.intersectConvexConvex(left, right)
    intersection_area = (
        0.0 if intersection is None else float(abs(cv2.contourArea(intersection)))
    )
    return intersection_area / max(left_area + right_area - intersection_area, 1e-8)


def polygon_bounds_xyxy(
    polygon: list[tuple[float, float]],
) -> list[float]:
    """返回 polygon 的外接 xyxy box。"""

    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return [min(xs), min(ys), max(xs), max(ys)]
