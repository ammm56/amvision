"""Pose 数据集拓扑到训练增强的契约测试。"""

from __future__ import annotations

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolo_core_common.training.pose_topology import (
    prepare_pose_augmentation_options,
)
from backend.service.domain.datasets.pose_topology import normalize_pose_flip_indices


def test_pose_flip_indices_require_complete_involutive_permutation() -> None:
    """三循环虽然是排列，但不是合法的左右翻转映射。"""

    with pytest.raises(ValueError, match="两次水平翻转"):
        normalize_pose_flip_indices([1, 2, 0], keypoint_count=3)


def test_pose_manifest_flip_indices_are_injected_into_augmentation() -> None:
    """自定义拓扑由 DatasetExport manifest 进入模型增强选项。"""

    result = prepare_pose_augmentation_options(
        extra_options={"flip_prob": 0.5},
        manifest_payload={
            "metadata": {
                "kpt_shape": [2, 3],
                "keypoint_flip_indices": [1, 0],
            }
        },
        keypoint_shape=(2, 3),
    )

    assert result["keypoint_flip_indices"] == [1, 0]


def test_custom_pose_topology_cannot_silently_skip_enabled_flip() -> None:
    """自定义拓扑缺少映射时，启用 flip 必须在训练开始前明确失败。"""

    with pytest.raises(InvalidRequestError, match="必须由数据集声明 flip_idx"):
        prepare_pose_augmentation_options(
            extra_options={"flip_prob": 0.5},
            manifest_payload={"metadata": {"kpt_shape": [21, 3]}},
            keypoint_shape=(21, 3),
        )


def test_custom_pose_topology_without_mapping_can_disable_flip() -> None:
    """显式关闭水平翻转后，自定义拓扑不强制提供左右交换映射。"""

    result = prepare_pose_augmentation_options(
        extra_options={"flip_prob": 0.0},
        manifest_payload={"metadata": {"kpt_shape": [21, 3]}},
        keypoint_shape=(21, 3),
    )

    assert result == {"flip_prob": 0.0}
