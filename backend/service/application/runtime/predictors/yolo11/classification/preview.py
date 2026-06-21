"""YOLO11 classification runtime 预览图渲染开关。"""

from __future__ import annotations

from typing import Any

from backend.service.application.runtime.predictors.yolo11.classification.contracts import (
    Yolo11ClassificationPredictionCategory,
)


def render_yolo11_classification_preview_image_if_requested(
    *,
    cv2_module: Any,
    image: Any,
    categories: tuple[Yolo11ClassificationPredictionCategory, ...],
    save_result_image: bool,
) -> bytes | None:
    """按请求参数决定是否生成 classification 调试预览图。"""

    if not save_result_image:
        return None
    preview = image.copy()
    overlay_lines = categories or (
        Yolo11ClassificationPredictionCategory(
            class_id=-1,
            class_name="no-result",
            probability=0.0,
        ),
    )
    for line_index, category in enumerate(overlay_lines, start=1):
        label = category.class_name or str(category.class_id)
        text = f"top{line_index} {label}: {category.probability:.3f}"
        cv2_module.putText(
            preview,
            text,
            (12, 24 * line_index),
            cv2_module.FONT_HERSHEY_SIMPLEX,
            0.6,
            (40, 180, 120),
            2,
            cv2_module.LINE_AA,
        )
    ok, encoded = cv2_module.imencode(".jpg", preview)
    if not ok:
        return None
    return bytes(encoded.tobytes())


__all__ = ["render_yolo11_classification_preview_image_if_requested"]
