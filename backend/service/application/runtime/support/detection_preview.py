"""detection 预测预览图渲染工具。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.contracts.detection import (
    DetectionPredictionDetection,
)


def render_detection_preview_image(
    *,
    cv2_module: Any,
    image: Any,
    detections: tuple[DetectionPredictionDetection, ...],
) -> bytes:
    """把 detection 结果叠加到原图并编码为 JPEG。

    参数：
    - cv2_module：OpenCV 模块。
    - image：原始 BGR 图像数组。
    - detections：已完成后处理的 detection 结果。

    返回：
    - bytes：JPEG 预览图二进制内容。
    """

    preview = image.copy()
    for detection in detections:
        x1, y1, x2, y2 = (int(round(value)) for value in detection.bbox_xyxy)
        color = _select_detection_color(detection.class_id)
        cv2_module.rectangle(preview, (x1, y1), (x2, y2), color, 2)
        label_text = (
            f"{detection.class_name}:{detection.score:.2f}"
            if detection.class_name is not None
            else f"{detection.class_id}:{detection.score:.2f}"
        )
        text_origin_y = y1 - 6 if y1 > 18 else y1 + 18
        cv2_module.putText(
            preview,
            label_text,
            (x1, text_origin_y),
            cv2_module.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2_module.LINE_AA,
        )

    success, encoded = cv2_module.imencode(".jpg", preview)
    if success is not True:
        raise InvalidRequestError("预测预览图编码失败")
    return bytes(encoded.tobytes())


def _select_detection_color(class_id: int) -> tuple[int, int, int]:
    """根据类别 id 返回稳定的框颜色。"""

    palette = (
        (40, 110, 240),
        (40, 180, 120),
        (240, 170, 40),
        (210, 80, 80),
    )
    return palette[class_id % len(palette)]
