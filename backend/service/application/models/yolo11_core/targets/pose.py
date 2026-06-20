"""YOLO11 pose target 编码。"""

from __future__ import annotations

from typing import Any


def normalize_yolo11_gt_keypoints_tensor(
    *,
    torch_module: Any,
    raw_keypoints: Any,
    assigned_indices: Any,
    num_keypoints: int,
    keypoint_dim: int,
    device: Any,
    dtype: Any,
) -> Any:
    """把 YOLO11 pose GT keypoints 规整成固定 shape 张量。"""

    target_width = int(num_keypoints) * int(keypoint_dim)
    target_count = int(assigned_indices.shape[0])
    normalized = torch_module.zeros(
        (target_count, target_width),
        device=device,
        dtype=dtype,
    )

    if isinstance(raw_keypoints, list):
        for output_index, assigned_index in enumerate(assigned_indices.tolist()):
            if assigned_index >= len(raw_keypoints):
                continue
            value = raw_keypoints[assigned_index]
            if not isinstance(value, list | tuple) or len(value) <= 0:
                continue
            limited_values = [float(item) for item in value[:target_width]]
            normalized[output_index, : len(limited_values)] = torch_module.tensor(
                limited_values,
                device=device,
                dtype=dtype,
            )
        return normalized.view(target_count, num_keypoints, keypoint_dim)

    if isinstance(raw_keypoints, torch_module.Tensor):
        selected = raw_keypoints[assigned_indices].to(device=device, dtype=dtype)
        if selected.dim() == 3:
            return selected
        if selected.dim() == 2 and int(selected.shape[1]) == target_width:
            return selected.view(target_count, num_keypoints, keypoint_dim)
        if selected.dim() == 1 and int(selected.shape[0]) == target_width:
            return selected.view(1, num_keypoints, keypoint_dim)

    return normalized.view(target_count, num_keypoints, keypoint_dim)


__all__ = ["normalize_yolo11_gt_keypoints_tensor"]
