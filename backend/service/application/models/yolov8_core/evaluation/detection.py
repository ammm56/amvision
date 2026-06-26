"""YOLOv8 detection 数据集级正式评估入口。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.service.application.models.evaluation.detection_evaluation import (
    DetectionEvaluationRequest,
    DetectionEvaluationResult,
    run_detection_evaluation,
)
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class YoloV8DetectionEvaluationRequest:
    """描述一次 YOLOv8 detection 数据集级评估请求。"""

    dataset_storage: LocalDatasetStorage
    runtime_target: RuntimeTargetSnapshot
    manifest_payload: dict[str, object]
    score_threshold: float = 0.001
    nms_threshold: float = 0.7
    extra_options: dict[str, object] = field(default_factory=dict)


YoloV8DetectionEvaluationResult = DetectionEvaluationResult


def run_yolov8_detection_evaluation(
    request: YoloV8DetectionEvaluationRequest,
) -> YoloV8DetectionEvaluationResult:
    """执行 YOLOv8 detection 数据集级评估。

    这里是 YOLOv8 core 的正式外壳。实际推理会话、COCO-style mAP 和
    per-class 指标仍复用平台通用 detection evaluation 执行器。
    """

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


__all__ = [
    "YoloV8DetectionEvaluationRequest",
    "YoloV8DetectionEvaluationResult",
    "run_yolov8_detection_evaluation",
]
