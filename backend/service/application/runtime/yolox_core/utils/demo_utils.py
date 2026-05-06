"""项目内 YOLOX 可视化辅助。"""

from __future__ import annotations

import random

import cv2
import numpy as np


def random_color() -> tuple[int, int, int]:
    """生成一个随机 BGR 颜色。"""

    return random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)


def visualize_assign(
    img: np.ndarray,
    boxes,
    coords,
    match_results,
    save_name: str | None = None,
) -> np.ndarray:
    """绘制 GT 与已匹配锚点的分配可视化结果。"""

    for box_id, box in enumerate(boxes):
        x1, y1, x2, y2 = box
        color = random_color()
        assign_coords = coords[match_results == box_id]
        if assign_coords.numel() == 0:
            color = (0, 0, 255)
            cv2.putText(
                img,
                "未匹配",
                (int(x1), int(y1) - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                1,
            )
        else:
            for coord in assign_coords:
                cv2.circle(img, (int(coord[0]), int(coord[1])), 3, color, -1)
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)

    if save_name is not None:
        cv2.imwrite(save_name, img)
    return img