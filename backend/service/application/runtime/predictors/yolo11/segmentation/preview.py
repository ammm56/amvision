"""YOLO11 segmentation runtime 预览图渲染开关。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo11_core.postprocess import (
    render_yolo11_detection_preview_image,
)
from backend.service.application.runtime.contracts.detection.prediction import (
    DetectionPredictionDetection,
)


def render_yolo11_segmentation_preview_image_if_requested(
    *,
    cv2_module: Any,
    image: Any,
    instances: tuple[Any, ...],
    save_result_image: bool,
) -> bytes | None:
    """按请求参数决定是否生成 segmentation 调试预览图。"""

    if not save_result_image:
        return None
    preview_detections = tuple(
        _as_preview_detection(instance) for instance in instances
    )
    return render_yolo11_detection_preview_image(
        cv2_module=cv2_module,
        image=image,
        instances=preview_detections,
    )


def _as_preview_detection(instance: Any) -> DetectionPredictionDetection:
    """把 segmentation 实例转换为预览绘制用 detection 记录。"""

    return DetectionPredictionDetection(
        bbox_xyxy=instance.bbox_xyxy,
        score=instance.score,
        class_id=instance.class_id,
        class_name=instance.class_name,
    )


__all__ = ["render_yolo11_segmentation_preview_image_if_requested"]
