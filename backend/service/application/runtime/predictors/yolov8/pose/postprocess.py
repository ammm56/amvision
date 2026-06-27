"""YOLOv8 pose runtime 结果组装工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolox_core.postprocess import (
    batched_yolox_nms_indices,
)
from backend.service.application.models.yolo_core_common.geometry import (
    YoloLetterboxTransform,
)
from backend.service.application.models.yolov8_core.inference import (
    build_yolov8_pose_inference_instances,
)
from backend.service.application.models.yolov8_core.cfg import get_yolov8_model_config
from backend.service.application.runtime.contracts.pose.prediction import (
    PosePredictionInstance,
    PosePredictionKeypoint,
)
from backend.service.application.runtime.predictors.yolov8.pose.contracts import (
    DEFAULT_YOLOV8_POSE_NMS_THRESHOLD,
)
from backend.service.application.runtime.targets.runtime_target import RuntimeTargetSnapshot


def infer_yolov8_pose_keypoint_shape(runtime_target: RuntimeTargetSnapshot) -> tuple[int, int]:
    """从运行时配置读取 pose keypoint shape。"""

    configured_shape = runtime_target.model_config.get("kpt_shape")
    if isinstance(configured_shape, list | tuple) and len(configured_shape) == 2:
        return int(configured_shape[0]), int(configured_shape[1])
    config = get_yolov8_model_config(task_type="pose")
    kpt_shape = config.get("kpt_shape")
    if isinstance(kpt_shape, list | tuple) and len(kpt_shape) == 2:
        return int(kpt_shape[0]), int(kpt_shape[1])
    return 17, 3


def build_yolov8_pose_runtime_instances(
    *,
    np_module: Any,
    prediction_array: Any,
    labels: tuple[str, ...],
    score_threshold: float,
    keypoint_confidence_threshold: float,
    letterbox_transform: YoloLetterboxTransform,
    default_kpt_shape: tuple[int, int],
) -> tuple[tuple[PosePredictionInstance, ...], tuple[int, int]]:
    """把 YOLOv8 pose 输出数组转换成平台实例记录。"""

    core_instances, core_kpt_shape = build_yolov8_pose_inference_instances(
        np_module=np_module,
        prediction_array=prediction_array,
        labels=labels,
        score_threshold=score_threshold,
        keypoint_confidence_threshold=keypoint_confidence_threshold,
        letterbox_transform=letterbox_transform,
        default_kpt_shape=default_kpt_shape,
        nms_threshold=DEFAULT_YOLOV8_POSE_NMS_THRESHOLD,
        nms_indices_func=batched_yolox_nms_indices,
    )
    return (
        tuple(
            PosePredictionInstance(
                bbox_xyxy=instance.bbox_xyxy,
                score=instance.score,
                class_id=instance.class_id,
                class_name=instance.class_name,
                keypoints=tuple(
                    PosePredictionKeypoint(
                        x=keypoint.x,
                        y=keypoint.y,
                        confidence=keypoint.confidence,
                    )
                    for keypoint in instance.keypoints
                ),
                kpt_shape=instance.kpt_shape,
            )
            for instance in core_instances
        ),
        core_kpt_shape,
    )


__all__ = [
    "build_yolov8_pose_runtime_instances",
    "infer_yolov8_pose_keypoint_shape",
]
