"""基于真实 pycocotools 评估状态提取 COCO AP 指标。"""

from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import dataclass
import io
import math
from typing import Any


YOLO_DETECTION_COCO_MAX_DETECTIONS = 300


@dataclass(frozen=True)
class PycocotoolsCategoryAveragePrecision:
    """描述单个类别在指定 max detections 下的 COCO AP。"""

    category_id: int
    category_name: str
    map50: float | None
    map50_95: float | None


@dataclass(frozen=True)
class PycocotoolsAveragePrecision:
    """描述指定 max detections 下的 COCO AP 指标。"""

    map50: float
    map50_95: float
    max_detections: int
    per_category: tuple[PycocotoolsCategoryAveragePrecision, ...] = ()


def evaluate_pycocotools_average_precision(
    *,
    ground_truth: Any,
    detections: list[dict[str, object]],
    cocoeval_class: Any,
    iou_type: str = "bbox",
    max_detections: int = YOLO_DETECTION_COCO_MAX_DETECTIONS,
    keypoint_oks_sigmas: tuple[float, ...] | None = None,
) -> PycocotoolsAveragePrecision:
    """运行 COCOeval 并显式从 precision 张量提取 AP。

    ``COCOeval.summarize`` 的首个 AP 项把 ``maxDets=100`` 写死在默认参数中。
    当平台需要 300 个候选时，直接读取 ``stats[0]`` 会得到 ``-1``。本函数
    以 ``params.maxDets`` 的真实索引读取 ``eval["precision"]``，从而让
    AP50 和 AP50-95 使用同一 max detections 语义。
    """

    resolved_max_detections = int(max_detections)
    if resolved_max_detections <= 0:
        raise ValueError("COCO max_detections 必须大于 0")
    if not detections:
        return PycocotoolsAveragePrecision(
            map50=0.0,
            map50_95=0.0,
            max_detections=resolved_max_detections,
            per_category=_build_empty_category_metrics(ground_truth),
        )

    with redirect_stdout(io.StringIO()):
        coco_detections = ground_truth.loadRes(detections)
        evaluator = cocoeval_class(ground_truth, coco_detections, iou_type)
        if iou_type == "keypoints" and keypoint_oks_sigmas is not None:
            _configure_keypoint_oks_sigmas(
                evaluator=evaluator,
                sigmas=keypoint_oks_sigmas,
            )
        evaluator.params.maxDets = [resolved_max_detections]
        evaluator.evaluate()
        evaluator.accumulate()

    return extract_pycocotools_average_precision(
        evaluator=evaluator,
        max_detections=resolved_max_detections,
    )


def _configure_keypoint_oks_sigmas(
    *,
    evaluator: Any,
    sigmas: tuple[float, ...],
) -> None:
    """为非 COCO-17 关键点拓扑设置显式、有限且等长的 OKS sigma。"""

    import numpy as np

    resolved = np.asarray(sigmas, dtype=float)
    if resolved.ndim != 1 or resolved.size < 1:
        raise ValueError("keypoint_oks_sigmas 必须是一维非空数组")
    if not np.all(np.isfinite(resolved)) or np.any(resolved <= 0.0):
        raise ValueError("keypoint_oks_sigmas 必须全部是有限正数")
    evaluator.params.kpt_oks_sigmas = resolved


def extract_pycocotools_average_precision(
    *,
    evaluator: Any,
    max_detections: int,
) -> PycocotoolsAveragePrecision:
    """从已经 accumulate 的 COCOeval precision 张量提取 AP。"""

    import numpy as np

    precision = np.asarray(evaluator.eval.get("precision"))
    if precision.ndim != 5:
        raise ValueError("COCOeval precision 张量必须是 [T, R, K, A, M]")

    params = evaluator.params
    area_labels = tuple(str(value) for value in params.areaRngLbl)
    max_detection_values = tuple(int(value) for value in params.maxDets)
    try:
        area_index = area_labels.index("all")
    except ValueError as error:
        raise ValueError("COCOeval 缺少 area=all 指标") from error
    try:
        max_detection_index = max_detection_values.index(int(max_detections))
    except ValueError as error:
        raise ValueError(
            f"COCOeval 缺少 maxDets={int(max_detections)} 指标"
        ) from error

    all_iou_precision = precision[:, :, :, area_index, max_detection_index]
    map50_95 = _mean_valid_coco_precision(
        all_iou_precision,
        metric_name="mAP50-95",
    )

    iou_thresholds = np.asarray(params.iouThrs, dtype=float)
    threshold_indices = np.flatnonzero(np.isclose(iou_thresholds, 0.5))
    if threshold_indices.size != 1:
        raise ValueError("COCOeval 必须且只能包含一个 IoU=0.5 阈值")
    map50 = _mean_valid_coco_precision(
        all_iou_precision[int(threshold_indices[0])],
        metric_name="mAP50",
    )
    category_ids = tuple(int(value) for value in params.catIds)
    if len(category_ids) != int(all_iou_precision.shape[2]):
        raise ValueError("COCOeval category id 与 precision 类别维度不一致")
    ground_truth_categories = getattr(getattr(evaluator, "cocoGt", None), "cats", {})
    per_category = tuple(
        PycocotoolsCategoryAveragePrecision(
            category_id=category_id,
            category_name=_resolve_category_name(
                categories=ground_truth_categories,
                category_id=category_id,
            ),
            map50=_mean_optional_coco_precision(
                all_iou_precision[int(threshold_indices[0]), :, category_index],
            ),
            map50_95=_mean_optional_coco_precision(
                all_iou_precision[:, :, category_index],
            ),
        )
        for category_index, category_id in enumerate(category_ids)
    )
    return PycocotoolsAveragePrecision(
        map50=map50,
        map50_95=map50_95,
        max_detections=int(max_detections),
        per_category=per_category,
    )


def _mean_valid_coco_precision(values: Any, *, metric_name: str) -> float:
    """忽略 pycocotools 的 ``-1`` 缺失项并验证最终 AP。"""

    import numpy as np

    array = np.asarray(values, dtype=float)
    valid_values = array[array > -1.0]
    if valid_values.size == 0:
        raise ValueError(f"COCOeval 没有可用于计算 {metric_name} 的 precision")
    metric_value = float(np.mean(valid_values))
    if not math.isfinite(metric_value) or not 0.0 <= metric_value <= 1.0:
        raise ValueError(f"COCOeval 产生了无效 {metric_name}: {metric_value}")
    return metric_value


def _mean_optional_coco_precision(values: Any) -> float | None:
    """计算单类别 AP；当前 split 没有该类别标注时返回 ``None``。"""

    import numpy as np

    array = np.asarray(values, dtype=float)
    valid_values = array[array > -1.0]
    if valid_values.size == 0:
        return None
    metric_value = float(np.mean(valid_values))
    if not math.isfinite(metric_value) or not 0.0 <= metric_value <= 1.0:
        raise ValueError(f"COCOeval 产生了无效单类别 AP: {metric_value}")
    return metric_value


def _resolve_category_name(*, categories: Any, category_id: int) -> str:
    """从 COCO category 索引读取稳定的类别名称。"""

    if isinstance(categories, dict):
        payload = categories.get(category_id) or categories.get(str(category_id))
        if isinstance(payload, dict):
            name = payload.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return str(category_id)


def _build_empty_category_metrics(
    ground_truth: Any,
) -> tuple[PycocotoolsCategoryAveragePrecision, ...]:
    """在没有任何预测时仍输出有标注类别的零 AP。"""

    categories = getattr(ground_truth, "cats", {})
    category_ids = tuple(sorted(int(value) for value in categories))
    annotations = getattr(ground_truth, "anns", {})
    annotated_category_ids = {
        int(payload["category_id"])
        for payload in annotations.values()
        if isinstance(payload, dict) and "category_id" in payload
    }
    return tuple(
        PycocotoolsCategoryAveragePrecision(
            category_id=category_id,
            category_name=_resolve_category_name(
                categories=categories,
                category_id=category_id,
            ),
            map50=0.0 if category_id in annotated_category_ids else None,
            map50_95=0.0 if category_id in annotated_category_ids else None,
        )
        for category_id in category_ids
    )


__all__ = [
    "PycocotoolsAveragePrecision",
    "PycocotoolsCategoryAveragePrecision",
    "YOLO_DETECTION_COCO_MAX_DETECTIONS",
    "evaluate_pycocotools_average_precision",
    "extract_pycocotools_average_precision",
]
