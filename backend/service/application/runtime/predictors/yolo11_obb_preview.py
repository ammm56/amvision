"""YOLO11 OBB runtime 预览图渲染开关。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo11_core.postprocess import (
    render_yolo11_detection_preview_image,
)


def render_yolo11_obb_preview_image_if_requested(
    *,
    cv2_module: Any,
    image: Any,
    instances: tuple[Any, ...],
    save_result_image: bool,
) -> bytes | None:
    """按请求参数决定是否生成 OBB 调试预览图。"""

    if not save_result_image:
        return None
    return render_yolo11_detection_preview_image(
        cv2_module=cv2_module,
        image=image,
        instances=instances,
    )


__all__ = ["render_yolo11_obb_preview_image_if_requested"]
