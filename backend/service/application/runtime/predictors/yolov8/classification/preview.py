"""YOLOv8 classification runtime 预览图渲染开关。"""

from __future__ import annotations

from typing import Any

from backend.service.application.runtime.predictors.yolov8.classification.contracts import (
    YoloV8ClassificationPredictionCategory,
)
from backend.service.application.runtime.predictors.classification_preview import (
    render_classification_preview_image_if_requested,
)


def render_yolov8_classification_preview_image_if_requested(
    *,
    cv2_module: Any,
    image: Any,
    categories: tuple[YoloV8ClassificationPredictionCategory, ...],
    save_result_image: bool,
) -> bytes | None:
    """按请求参数决定是否生成 classification 调试预览图。"""

    return render_classification_preview_image_if_requested(
        cv2_module=cv2_module,
        image=image,
        categories=categories,
        save_result_image=save_result_image,
    )


__all__ = ["render_yolov8_classification_preview_image_if_requested"]
