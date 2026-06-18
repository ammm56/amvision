"""YOLOv8 pose 评估入口。"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any

from backend.service.application.models.pose_evaluation import (
    PoseEvaluationRequest,
    PoseEvaluationResult,
    run_pose_evaluation,
)
from backend.service.application.models.yolov8_core.data import (
    build_yolov8_pose_training_batch,
)
from backend.service.application.models.yolov8_core.postprocess import (
    build_yolov8_pose_postprocess_instances,
)
from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot
from backend.service.application.runtime.support.detection import batched_nms_indices
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class YoloV8PoseEvaluationRequest:
    """描述一次 YOLOv8 pose 数据集级评估请求。"""

    dataset_storage: LocalDatasetStorage
    runtime_target: RuntimeTargetSnapshot
    manifest_payload: dict[str, object]
    score_threshold: float = 0.01
    extra_options: dict[str, object] = field(default_factory=dict)


YoloV8PoseEvaluationResult = PoseEvaluationResult


def run_yolov8_pose_evaluation(
    request: YoloV8PoseEvaluationRequest,
) -> YoloV8PoseEvaluationResult:
    """执行 YOLOv8 pose 数据集级评估。"""

    return run_pose_evaluation(
        PoseEvaluationRequest(
            dataset_storage=request.dataset_storage,
            runtime_target=request.runtime_target,
            manifest_payload=request.manifest_payload,
            score_threshold=request.score_threshold,
            extra_options=dict(request.extra_options),
        ),
    )


def evaluate_yolov8_pose_samples(
    *,
    model: Any,
    samples: list[Any],
    labels: tuple[str, ...],
    input_size: tuple[int, int],
    device: str,
    precision: str,
    score_threshold: float,
    nms_threshold: float,
    keypoint_confidence_threshold: float,
    kpt_shape: tuple[int, int],
    imports: Any,
) -> dict[str, float]:
    """对少量验证样本执行 YOLOv8 pose 训练期评估。"""

    model.eval()
    matched50 = 0
    matched75 = 0
    total_gt = 0
    total_predictions = 0
    with imports.torch.no_grad():
        for sample in samples[:8]:
            batch = build_yolov8_pose_training_batch(
                samples=[sample],
                input_size=input_size,
                device=device,
                precision=precision,
                imports=imports,
            )
            if batch is None:
                continue
            with _yolov8_evaluation_autocast(imports, precision, device):
                outputs = model(batch.images)
            prediction_array = _yolov8_tensor_to_np(outputs, imports)
            instances, _ = build_yolov8_pose_postprocess_instances(
                np_module=imports.np,
                prediction_array=prediction_array,
                labels=labels,
                score_threshold=score_threshold,
                keypoint_confidence_threshold=keypoint_confidence_threshold,
                resize_ratio=1.0,
                image_width=int(input_size[0]),
                image_height=int(input_size[1]),
                input_size=input_size,
                default_kpt_shape=kpt_shape,
                nms_threshold=nms_threshold,
                nms_indices_func=batched_nms_indices,
            )
            gt_boxes = batch.targets[0].boxes_xyxy
            gt_classes = batch.targets[0].category_indexes
            total_gt += len(gt_boxes)
            total_predictions += len(instances)
            image_matched50, image_matched75 = _count_yolov8_pose_matches(
                predictions=instances,
                gt_boxes=gt_boxes,
                gt_classes=gt_classes,
            )
            matched50 += image_matched50
            matched75 += image_matched75
    model.train()
    return {
        "map50": round(matched50 / max(1, total_gt), 6),
        "map50_95": round(((matched50 + matched75) / 2.0) / max(1, total_gt), 6),
        "prediction_count": float(total_predictions),
    }


def _count_yolov8_pose_matches(
    *,
    predictions: tuple[Any, ...],
    gt_boxes: list[list[float]],
    gt_classes: list[int],
) -> tuple[int, int]:
    """按 bbox IoU 统计 YOLOv8 pose 简化匹配数。"""

    used_gt: set[int] = set()
    matched50 = 0
    matched75 = 0
    for prediction in predictions:
        best_index = -1
        best_iou = 0.0
        for gt_index, gt_box in enumerate(gt_boxes):
            if gt_index in used_gt or int(prediction.class_id) != int(gt_classes[gt_index]):
                continue
            iou = _box_iou(prediction.bbox_xyxy, tuple(float(value) for value in gt_box))
            if iou > best_iou:
                best_iou = iou
                best_index = gt_index
        if best_index >= 0 and best_iou >= 0.5:
            matched50 += 1
            used_gt.add(best_index)
            if best_iou >= 0.75:
                matched75 += 1
    return matched50, matched75


def _box_iou(box1: tuple[float, float, float, float], box2: tuple[float, float, float, float]) -> float:
    """计算两个 xyxy box 的 IoU。"""

    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area1 = max(0.0, box1[2] - box1[0]) * max(0.0, box1[3] - box1[1])
    area2 = max(0.0, box2[2] - box2[0]) * max(0.0, box2[3] - box2[1])
    return inter / max(area1 + area2 - inter, 1e-8)


def _yolov8_evaluation_autocast(imports: Any, precision: str, device: str):
    """返回 YOLOv8 训练期评估使用的 autocast 上下文。"""

    if precision != "fp16":
        return nullcontext()
    amp = getattr(imports.torch, "amp", None)
    if amp is not None and hasattr(amp, "autocast"):
        device_type = "cuda" if str(device).startswith("cuda") else "cpu"
        return amp.autocast(device_type=device_type, enabled=True)
    return nullcontext()


def _yolov8_tensor_to_np(outputs: Any, imports: Any) -> Any:
    """把 YOLOv8 pose 输出转换为 NumPy 数组。"""

    tensor = outputs[0] if isinstance(outputs, tuple) else outputs
    if isinstance(tensor, dict):
        tensor = tensor.get("prediction", tensor)
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
    "YoloV8PoseEvaluationRequest",
    "YoloV8PoseEvaluationResult",
    "evaluate_yolov8_pose_samples",
    "run_yolov8_pose_evaluation",
]
