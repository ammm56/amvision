"""断线审计本身使用解析已知的平面斜坡和空带验证，不以真实样本输出作真值。"""

import numpy as np
import pytest

from tests.integration.metrology3d.boundary_audit import (
    audit_surface,
    verify_endpoint_context,
)


@pytest.mark.parametrize("gap", [False, True])
@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_audit_proves_support_gap_without_intersection_loss(gap, dtype):
    """z=x 与 z=0 交于 x=0；空带应为两条开链而不是误闭合。"""
    ys = (0, 1, 4, 5) if gap else (0, 1, 2, 3)
    points = np.array([(x, y, x) for y in ys for x in (-1, 1)], dtype=dtype)
    rows = np.arange(20, 20 + len(points), dtype="<u8")
    evaluation = dict(origin=[0, 0, 0], rotation=np.eye(3).tolist())
    report, section = audit_surface(
        points,
        rows,
        evaluation,
        dict(
            alpha_radius=1.25,
            max_edge_length=2.5,
            max_normal_step=3,
            min_projected_area=1e-8,
        ),
        budget=1048576,
        tolerance=1e-9,
    )
    assert report["segment_count"] == (2 if gap else 1)
    assert all(not s["closed"] for s in report["segments"])
    np.testing.assert_allclose(section.positions[:, [0, 2]], 0, atol=1e-12)
    assert report["crossing_faces"] == 6
    assert report["accepted_crossing_faces"] == (4 if gap else 6)
    if gap:
        assert report["rejection_combinations"] == {"passed": 4, "edge+alpha": 2}
        assert not np.any((section.positions[:, 1] > 1) & (section.positions[:, 1] < 4))
    context = verify_endpoint_context(points, rows, evaluation, report)
    assert context["same_endpoint_neighbor_faces"] == context["endpoint_neighbor_count"]


def test_audit_does_not_silently_ignore_coplanar_vertices():
    """限制诊断适用范围，避免独立检查遗漏共面分支却显示通过。"""
    with pytest.raises(AssertionError, match="共面顶点"):
        audit_surface(
            np.array([[0.0, 0, 0], [1, 0, 1], [0, 1, -1]]),
            np.arange(3, dtype="<u8"),
            dict(origin=[0, 0, 0], rotation=np.eye(3)),
            {},
            budget=1048576,
            tolerance=1e-9,
        )
