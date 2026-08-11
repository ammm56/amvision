"""Pose 关键点拓扑的领域级校验规则。"""

from __future__ import annotations


def normalize_pose_flip_indices(
    value: object,
    *,
    keypoint_count: int,
) -> tuple[int, ...] | None:
    """校验并规范化水平翻转的关键点重排索引。

    映射必须覆盖全部关键点、没有重复，并满足两次翻转恢复原索引。
    ``None`` 表示数据集没有声明水平翻转拓扑。
    """

    resolved_count = int(keypoint_count)
    if resolved_count < 1:
        raise ValueError("keypoint_count 必须大于等于 1")
    if value is None:
        return None
    if not isinstance(value, list | tuple):
        raise ValueError("pose flip_idx 必须是整数数组")
    if len(value) != resolved_count:
        raise ValueError(
            "pose flip_idx 数量与 kpt_shape 不一致: "
            f"expected={resolved_count}, actual={len(value)}"
        )
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise ValueError("pose flip_idx 必须只包含整数")
    indices = tuple(int(item) for item in value)
    if sorted(indices) != list(range(resolved_count)):
        raise ValueError("pose flip_idx 必须是 0 到 keypoint_count-1 的完整排列")
    if any(indices[indices[index]] != index for index in range(resolved_count)):
        raise ValueError("pose flip_idx 必须满足两次水平翻转恢复原关键点顺序")
    return indices


__all__ = ["normalize_pose_flip_indices"]
