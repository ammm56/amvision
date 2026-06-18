"""YOLOv8 detection runtime 预览图渲染开关。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolov8_core.postprocess import (
    render_yolov8_detection_preview_image,
)


def render_yolov8_detection_preview_image_if_requested(
    *,
    cv2_module: Any,
    image: Any,
    detections: Any,
    save_result_image: bool,
) -> bytes | None:
    """按请求参数决定是否生成带检测框的调试预览图。"""

    if not save_result_image:
        return None
    return render_yolov8_detection_preview_image(
        cv2_module=cv2_module,
        image=image,
        instances=detections,
    )


__all__ = ["render_yolov8_detection_preview_image_if_requested"]
