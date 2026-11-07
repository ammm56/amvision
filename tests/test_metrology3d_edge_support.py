"""法向折边的双侧支持复用：独立折角，不依赖高度方向或理论交线造点。"""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.edge3d import NormalCreaseSettings
from custom_nodes.metrology3d_nodes.shared.edge_support import verify_edge_support
from tests.test_metrology3d_edge_candidates import settings


def crease_settings():
    """解析测试参数，不作为节点默认。"""
    height = settings()
    return NormalCreaseSettings(
        kind="normal-crease",
        radius=2,
        max_neighbors=64,
        min_angle=0.5,
        support=height.support,
        support_a=height.support_a,
        support_b=height.support_b,
        max_unassigned_fraction=0.2,
        max_pair_distance=0.5,
    )


def fold(angle):
    """两块解析矩形分别在 y 轴两侧，夹角由直接刚体旋转确定。"""
    plane = np.array(
        [(x, y, 0) for x in (0.1, 0.3, 0.6, 0.9) for y in (-1, -0.5, 0, 0.5, 1)],
        dtype=float,
    )
    other = plane.copy()
    other[:, 0] *= -1
    plane[:, 2] = plane[:, 0] * np.sin(angle)
    plane[:, 0] *= np.cos(angle)
    points = np.vstack((other, plane))
    masks = np.zeros((len(points), 2), dtype=bool)
    masks[: len(plane), 0] = True
    masks[len(plane) :, 1] = True
    return points, masks


@pytest.mark.parametrize("chunk", [1, 7, 256])
@pytest.mark.parametrize("rotate", [False, True])
def test_fold_support_angle_is_independent_of_height_axis(chunk, rotate):
    points, masks = fold(np.pi / 3)
    if rotate:
        points = points[:, (2, 0, 1)] + (100, -200, 300)
    counts, _, _, rms, _, _, models, reason = verify_edge_support(
        points, masks, crease_settings(), chunk, lambda: None
    )
    assert reason is None and counts == (20, 20)
    assert max(rms) < 1e-12
    cosine = abs(models[0][1] @ models[1][1])
    np.testing.assert_allclose(np.arccos(cosine), np.pi / 3, atol=1e-12)


def test_flat_and_separated_parallel_surfaces_are_not_folds():
    points, masks = fold(0)
    for height in (0, 2):
        points[masks[:, 1], 2] = height
        *_, reason = verify_edge_support(
            points, masks, crease_settings(), 5, lambda: None
        )
        assert reason == "normal_angle_insufficient"


def test_fold_keeps_overlap_and_full_support_quality():
    points, masks = fold(np.pi / 3)
    masks[0, 1] = True
    *_, reason = verify_edge_support(points, masks, crease_settings(), 5, lambda: None)
    assert reason == "support_overlap"
    masks[0, 1] = False
    points[3, 2] += 0.1
    *_, reason = verify_edge_support(points, masks, crease_settings(), 5, lambda: None)
    assert reason == "side_quality_failed"


def test_normal_search_extent_is_explicit():
    raw = crease_settings().model_dump()
    raw["max_pair_distance"] = 3
    with pytest.raises(ValidationError, match="搜索半径"):
        NormalCreaseSettings.model_validate(raw)
