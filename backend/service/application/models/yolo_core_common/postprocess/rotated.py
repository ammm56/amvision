"""YOLO 主线共享 rotated NMS 实现。"""

from __future__ import annotations

import math
from typing import Any

from backend.service.application.errors import ServiceConfigurationError


def class_aware_rotated_nms_indices(
    *,
    np_module: Any,
    boxes_xywhr: Any,
    scores: Any,
    class_ids: Any,
    nms_threshold: float,
    max_detections: int,
) -> Any:
    """通过 OpenCV 的原生 rotated NMS 执行按类别抑制。

    平台内部统一使用弧度，OpenCV ``RotatedRect`` 接口使用角度，因此只在
    这个运行时边界转换单位。按类别分别执行，避免不同类别互相抑制。
    """

    try:
        import cv2
    except ImportError as error:  # pragma: no cover - OpenCV 是平台强依赖。
        raise ServiceConfigurationError("OBB rotated NMS 需要 OpenCV") from error

    if int(len(boxes_xywhr)) <= 0:
        return np_module.asarray([], dtype=np_module.int64)

    kept: list[int] = []
    for class_id in np_module.unique(class_ids):
        class_indices = np_module.flatnonzero(class_ids == class_id)
        rotated_rectangles = [
            (
                (float(boxes_xywhr[index][0]), float(boxes_xywhr[index][1])),
                (
                    max(float(boxes_xywhr[index][2]), 0.0),
                    max(float(boxes_xywhr[index][3]), 0.0),
                ),
                math.degrees(float(boxes_xywhr[index][4])),
            )
            for index in class_indices
        ]
        class_scores = [float(scores[index]) for index in class_indices]
        raw_indices = cv2.dnn.NMSBoxesRotated(
            rotated_rectangles,
            class_scores,
            score_threshold=0.0,
            nms_threshold=float(nms_threshold),
            # OpenCV 的 top_k 会在 NMS 前截断候选，不能用最终 max_det 代替。
            top_k=0,
        )
        for local_index in np_module.asarray(raw_indices).reshape(-1):
            kept.append(int(class_indices[int(local_index)]))

    kept.sort(key=lambda index: float(scores[index]), reverse=True)
    return np_module.asarray(kept[: int(max_detections)], dtype=np_module.int64)


__all__ = ["class_aware_rotated_nms_indices"]
