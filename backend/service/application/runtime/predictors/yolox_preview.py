"""YOLOX runtime 预览图渲染开关。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolox_core.postprocess import (
    render_yolox_detection_preview_image,
)


def render_yolox_preview_image_if_requested(
    *,
    cv2_module: Any,
    image: Any,
    detections: Any,
    save_result_image: bool,
) -> bytes | None:
    """按请求参数决定是否生成带检测框的预览图。

    参数：
    - cv2_module：OpenCV 模块。
    - image：原始 BGR 图像。
    - detections：YOLOX detection 结果。
    - save_result_image：是否返回预览图。

    返回：
    - bytes | None：需要预览时返回图片字节，否则返回 None。
    """

    if not save_result_image:
        return None
    return render_yolox_detection_preview_image(
        cv2_module=cv2_module,
        image=image,
        detections=detections,
    )
