"""YOLOv8 pose target 编码入口。"""

from __future__ import annotations

from typing import Any

from backend.service.application.models.yolo_core_common.targets.pose import (
    normalize_gt_keypoints_tensor,
)


def normalize_yolov8_gt_keypoints_tensor(
    *,
    torch_module: Any,
    raw_keypoints: Any,
    assigned_indices: Any,
    num_keypoints: int,
    keypoint_dim: int,
    device: Any,
    dtype: Any,
) -> Any:
    """把 YOLOv8 pose GT keypoints 规整为固定张量。"""

    return normalize_gt_keypoints_tensor(
        torch_module=torch_module,
        raw_keypoints=raw_keypoints,
        assigned_indices=assigned_indices,
        num_keypoints=num_keypoints,
        keypoint_dim=keypoint_dim,
        device=device,
        dtype=dtype,
    )


__all__ = ["normalize_yolov8_gt_keypoints_tensor"]
