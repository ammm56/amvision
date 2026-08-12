"""共享 OBB 预测预览图渲染。"""

from __future__ import annotations

from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.evaluation.coco_style_metrics import (
    xywhr_to_polygon,
)


def render_obb_preview_image(
    *,
    cv2_module: Any,
    image: Any,
    instances: tuple[Any, ...],
) -> bytes:
    """按规范 ``bbox_xywhr`` 绘制旋转框并编码 JPEG。"""

    preview = image.copy()
    for instance in instances:
        points = [
            (int(round(x)), int(round(y)))
            for x, y in xywhr_to_polygon(instance.bbox_xywhr)
        ]
        color = _select_obb_preview_color(int(instance.class_id))
        for index, start in enumerate(points):
            cv2_module.line(
                preview,
                start,
                points[(index + 1) % len(points)],
                color,
                2,
                cv2_module.LINE_AA,
            )
        label_text = (
            f"{instance.class_name}:{instance.score:.2f}"
            if instance.class_name is not None
            else f"{instance.class_id}:{instance.score:.2f}"
        )
        x1 = min(point[0] for point in points)
        y1 = min(point[1] for point in points)
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
        raise InvalidRequestError("OBB 预测预览图编码失败")
    return bytes(encoded.tobytes())


def _select_obb_preview_color(class_id: int) -> tuple[int, int, int]:
    """根据类别 id 返回稳定颜色。"""

    palette = (
        (40, 110, 240),
        (40, 180, 120),
        (240, 170, 40),
        (210, 80, 80),
    )
    return palette[class_id % len(palette)]


__all__ = ["render_obb_preview_image"]
