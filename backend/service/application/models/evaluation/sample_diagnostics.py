"""从保留的姿态与 OBB 几何计算逐图误差分类。"""

from collections.abc import Callable
from typing import Literal

from backend.service.application.models.evaluation.coco_style_metrics import (
    bbox_iou_xyxy,
    compute_object_keypoint_similarity,
    polygon_iou,
)

GeometryKind = Literal["pose", "obb"]
MATCH_THRESHOLD = 0.50
NEARBY_THRESHOLD = 0.10


def _pose_overlaps(prediction: dict, target: dict) -> float:
    """返回轴对齐框的 IoU，用于关联同位置的关键点。"""
    return bbox_iou_xyxy(prediction["bbox_xyxy"], target["bbox_xyxy"])


def _obb_overlap(prediction: dict, target: dict) -> float:
    """使用报告保存的四角点计算原始旋转框的 IoU。"""
    return polygon_iou(prediction["polygon"], target["polygon"])


def _obb_aligned_overlap(prediction: dict, target: dict) -> float:
    """仅将预测框的长边朝向对齐到标注，测量剩余位置和尺寸误差。"""
    import cv2
    import numpy as np

    def rectangle(item: dict) -> tuple:
        center, (width, height), angle = cv2.minAreaRect(np.asarray(item["polygon"], dtype=np.float32))
        if width < height:
            return center, (height, width), angle + 90
        return center, (width, height), angle

    center, size, _ = rectangle(prediction)
    _, _, target_angle = rectangle(target)
    aligned = cv2.boxPoints((center, size, target_angle)).tolist()
    return polygon_iou(aligned, target["polygon"])


def _matches(remaining: set[int], prediction: dict, targets: list[dict]) -> list[tuple[int, dict]]:
    """提供同类且尚未匹配的标注候选，按标注顺序打破平局。"""
    return [(index, targets[index]) for index in sorted(remaining) if targets[index]["category_id"] == prediction["category_id"]]


def explain_geometry_errors(
    sample: dict, kind: GeometryKind, *, sigmas: tuple[float, ...] = (),
) -> dict[str, int]:
    """按报告里的工作点预测匹配，给出互斥的对象级诊断次数。"""
    targets = sample["ground_truth"]
    if kind == "pose":
        targets = [item for item in targets if any(v > 0 for v in item["keypoints"][2::3])]
    predictions = sorted(sample["predictions"], key=lambda item: item["score"], reverse=True)
    remaining = set(range(len(targets)))
    near: Callable[[dict, dict], float]

    def pose_score(prediction: dict, target: dict) -> float:
        """沿用报告计算 OKS 时保存的 sigma 和标注面积。"""
        return compute_object_keypoint_similarity(
            target["keypoints"], prediction["keypoints"], area=target["area"], sigmas=sigmas,
        )

    score = pose_score if kind == "pose" else _obb_overlap
    near = _pose_overlaps if kind == "pose" else _obb_overlap
    errors: dict[str, int] = {}
    unmatched = []
    for prediction in predictions:
        candidates = _matches(remaining, prediction, targets)
        best_score, index = max(((score(prediction, gt), i) for i, gt in candidates), default=(0.0, -1))
        if best_score >= MATCH_THRESHOLD:
            remaining.remove(index)
        else:
            unmatched.append(prediction)

    extra = 0
    for prediction in unmatched:
        best = (0.0, -1, "")
        for index, target in _matches(remaining, prediction, targets):
            proximity = near(prediction, target)
            if kind == "obb" and _obb_aligned_overlap(prediction, target) >= MATCH_THRESHOLD:
                best = max(best, (1.0 + proximity, index, "angle"))
            elif proximity >= NEARBY_THRESHOLD:
                best = max(best, (proximity, index, "keypoints" if kind == "pose" else "localization"))
        _, index, issue = best
        if index == -1:
            extra += 1
        else:
            remaining.remove(index)
            errors[issue] = errors.get(issue, 0) + 1
    return {**errors, "missed": len(remaining), "extra": extra}
