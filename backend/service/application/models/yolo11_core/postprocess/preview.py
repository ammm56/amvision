"""YOLO11 调试预览图渲染。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError


def render_yolo11_detection_preview_image(
    *,
    cv2_module: Any,
    image: Any,
    instances: tuple[Any, ...],
) -> bytes:
    """把 YOLO11 实例结果叠加到原图并编码为 JPEG。"""

    preview = image.copy()
    for instance in instances:
        x1, y1, x2, y2 = (int(round(value)) for value in instance.bbox_xyxy)
        color = _select_yolo11_preview_color(int(instance.class_id))
        cv2_module.rectangle(preview, (x1, y1), (x2, y2), color, 2)
        label_text = (
            f"{instance.class_name}:{instance.score:.2f}"
            if instance.class_name is not None
            else f"{instance.class_id}:{instance.score:.2f}"
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
        raise InvalidRequestError("YOLO11 预测预览图编码失败")
    return bytes(encoded.tobytes())


def _select_yolo11_preview_color(class_id: int) -> tuple[int, int, int]:
    """根据类别 id 返回稳定的 YOLO11 预览颜色。"""

    palette = (
        (40, 110, 240),
        (40, 180, 120),
        (240, 170, 40),
        (210, 80, 80),
    )
    return palette[class_id % len(palette)]


__all__ = ["render_yolo11_detection_preview_image"]
