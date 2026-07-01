"""YOLO11 detection 数据集级评估入口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.postprocess.detection_postprocess import (
    postprocess_detection_prediction_array,
)
from backend.service.application.models.yolo_core_common.geometry import (
    scale_yolo_box_from_letterbox,
)
from backend.service.application.models.evaluation.detection_evaluation import (
    DetectionEvaluationRequest,
    DetectionEvaluationResult,
    run_detection_evaluation,
)
from backend.service.application.models.yolo11_core.postprocess.detection import (
    YOLO11_DETECTION_POSTPROCESS_MODE_NMS,
)
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class Yolo11DetectionEvaluationRequest:
    """描述一次 YOLO11 detection 数据集级评估请求。"""

    dataset_storage: LocalDatasetStorage
    runtime_target: RuntimeTargetSnapshot
    manifest_payload: dict[str, object]
    score_threshold: float = 0.001
    nms_threshold: float = 0.7
    extra_options: dict[str, object] = field(default_factory=dict)


Yolo11DetectionEvaluationResult = DetectionEvaluationResult


def run_yolo11_detection_evaluation(
    request: Yolo11DetectionEvaluationRequest,
) -> Yolo11DetectionEvaluationResult:
    """执行 YOLO11 detection 数据集级评估。"""

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


def convert_yolo11_predictions_to_coco_detections(
    *,
    np_module: Any,
    prediction_tensor: Any,
    batch_targets: tuple[Any, ...],
    input_size: tuple[int, int],
    category_ids: tuple[int, ...],
    confidence_threshold: float,
    nms_threshold: float,
) -> list[dict[str, object]]:
    """把 YOLO11 detection 预测转换为 COCO detection 结果列表。"""

    prediction_tensor = _extract_yolo11_processed_prediction(prediction_tensor)
    prediction_array = prediction_tensor.detach().cpu().numpy()
    postprocess_results = postprocess_detection_prediction_array(
        prediction_array=prediction_array,
        np_module=np_module,
        num_classes=len(category_ids),
        score_threshold=confidence_threshold,
        nms_threshold=nms_threshold,
        postprocess_mode=YOLO11_DETECTION_POSTPROCESS_MODE_NMS,
        box_format="xywh",
        max_detections=None,
    )
    detections: list[dict[str, object]] = []
    for batch_index, result in enumerate(postprocess_results):
        if result is None:
            continue
        target = batch_targets[batch_index]
        if target.letterbox_transform is None:
            raise InvalidRequestError(
                "YOLO11 detection 验证缺少 LetterBox 坐标变换信息",
                details={"image_id": target.image_id, "input_size": input_size},
            )
        for bbox, score, class_id in zip(
            result.boxes_xyxy,
            result.scores,
            result.class_ids,
            strict=True,
        ):
            mapped_box = scale_yolo_box_from_letterbox(
                box_xyxy=(
                    float(bbox[0]),
                    float(bbox[1]),
                    float(bbox[2]),
                    float(bbox[3]),
                ),
                transform=target.letterbox_transform,
            )
            if mapped_box is None:
                continue
            x1, y1, x2, y2 = mapped_box
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


def _extract_yolo11_processed_prediction(prediction_tensor: Any) -> Any:
    """从 YOLO11 eval 输出中取用于后处理的 processed prediction。"""

    if isinstance(prediction_tensor, list | tuple):
        if not prediction_tensor:
            raise InvalidRequestError("YOLO11 detection 预测输出为空")
        return prediction_tensor[0]
    return prediction_tensor


__all__ = [
    "convert_yolo11_predictions_to_coco_detections",
    "Yolo11DetectionEvaluationRequest",
    "Yolo11DetectionEvaluationResult",
    "run_yolo11_detection_evaluation",
]
