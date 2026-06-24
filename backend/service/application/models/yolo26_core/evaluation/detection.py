"""YOLO26 detection 数据集级评估入口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.service.application.models.evaluation.detection_evaluation import (
    DetectionEvaluationRequest,
    DetectionEvaluationResult,
    run_detection_evaluation,
)
from backend.service.application.models.yolo26_core.inference import (
    normalize_yolo26_detection_inference_outputs,
)
from backend.service.application.models.yolo26_core.postprocess.detection import (
    postprocess_yolo26_detection_prediction_array,
)
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class Yolo26DetectionEvaluationRequest:
    """描述一次 YOLO26 detection 数据集级评估请求。"""

    dataset_storage: LocalDatasetStorage
    runtime_target: RuntimeTargetSnapshot
    manifest_payload: dict[str, object]
    score_threshold: float = 0.01
    nms_threshold: float = 0.65
    extra_options: dict[str, object] = field(default_factory=dict)


Yolo26DetectionEvaluationResult = DetectionEvaluationResult


def run_yolo26_detection_evaluation(
    request: Yolo26DetectionEvaluationRequest,
) -> Yolo26DetectionEvaluationResult:
    """执行 YOLO26 detection 数据集级评估。"""

    return run_detection_evaluation(
        DetectionEvaluationRequest(
            dataset_storage=request.dataset_storage,
            runtime_target=request.runtime_target,
            manifest_payload=request.manifest_payload,
            score_threshold=request.score_threshold,
            nms_threshold=request.nms_threshold,
            extra_options=dict(request.extra_options),
        )
    )


def convert_yolo26_predictions_to_coco_detections(
    *,
    np_module: Any,
    prediction_tensor: Any,
    batch_targets: tuple[Any, ...],
    input_size: tuple[int, int],
    category_ids: tuple[int, ...],
    confidence_threshold: float,
    nms_threshold: float,
) -> list[dict[str, object]]:
    """把 YOLO26 detection 预测转换为 COCO detection 结果列表。"""

    prediction_array = normalize_yolo26_detection_inference_outputs(
        outputs=prediction_tensor,
        np_module=np_module,
    )
    _ = nms_threshold
    postprocess_results = postprocess_yolo26_detection_prediction_array(
        prediction_array=prediction_array,
        np_module=np_module,
        num_classes=len(category_ids),
        score_threshold=confidence_threshold,
    )
    detections: list[dict[str, object]] = []
    for batch_index, result in enumerate(postprocess_results):
        if result is None:
            continue
        target = batch_targets[batch_index]
        scale_x = float(input_size[1]) / max(1.0, float(target.image_width))
        scale_y = float(input_size[0]) / max(1.0, float(target.image_height))
        for bbox, score, class_id in zip(
            result.boxes_xyxy,
            result.scores,
            result.class_ids,
            strict=True,
        ):
            x1 = max(0.0, min(float(bbox[0]) / scale_x, float(target.image_width)))
            y1 = max(0.0, min(float(bbox[1]) / scale_y, float(target.image_height)))
            x2 = max(0.0, min(float(bbox[2]) / scale_x, float(target.image_width)))
            y2 = max(0.0, min(float(bbox[3]) / scale_y, float(target.image_height)))
            width = max(0.0, x2 - x1)
            height = max(0.0, y2 - y1)
            resolved_class_id = int(class_id)
            if (
                width <= 0
                or height <= 0
                or resolved_class_id < 0
                or resolved_class_id >= len(category_ids)
            ):
                continue
            detections.append(
                {
                    "image_id": target.image_id,
                    "category_id": category_ids[resolved_class_id],
                    "bbox": [x1, y1, width, height],
                    "score": float(score),
                }
            )
    return detections


__all__ = [
    "convert_yolo26_predictions_to_coco_detections",
    "Yolo26DetectionEvaluationRequest",
    "Yolo26DetectionEvaluationResult",
    "run_yolo26_detection_evaluation",
]
