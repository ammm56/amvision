"""YOLO11 segmentation 训练 anchor 构建。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.geometry import make_anchors


def build_yolo11_segmentation_anchors_from_features(
    *,
    feature_maps: list[Any],
    strides: tuple[int, ...],
    device_name: str,
    torch_module: Any,
) -> tuple[Any, Any]:
    """根据 YOLO11 segmentation 特征图生成 anchor points 和 stride tensor。"""

    _ = device_name, torch_module
    return make_anchors(feature_maps=feature_maps, strides=strides)


__all__ = [
    "build_yolo11_segmentation_anchors_from_features",
]
