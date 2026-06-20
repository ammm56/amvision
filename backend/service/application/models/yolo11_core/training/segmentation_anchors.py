"""YOLO11 segmentation 训练 anchor 构建。"""

from __future__ import annotations

from typing import Any


def build_yolo11_segmentation_anchors_from_features(
    *,
    feature_maps: list[Any],
    strides: tuple[int, ...],
    device_name: str,
    torch_module: Any,
) -> tuple[Any, Any]:
    """根据 YOLO11 segmentation 特征图生成 anchor points 和 stride tensor。"""

    anchor_list = []
    stride_list = []
    for feature_map, stride in zip(feature_maps, strides, strict=True):
        _, _, height, width = feature_map.shape
        grid_y, grid_x = torch_module.meshgrid(
            torch_module.arange(height, device=device_name),
            torch_module.arange(width, device=device_name),
            indexing="ij",
        )
        anchors = torch_module.stack((grid_x, grid_y), dim=-1).reshape(-1, 2) * stride
        stride_tensor = torch_module.full(
            (height * width, 1), stride, device=device_name
        )
        anchor_list.append(anchors)
        stride_list.append(stride_tensor)
    return torch_module.cat(anchor_list), torch_module.cat(stride_list)


__all__ = [
    "build_yolo11_segmentation_anchors_from_features",
]
