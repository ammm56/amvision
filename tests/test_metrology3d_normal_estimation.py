"""法向内核独立距离矩阵/SVD 真值；尚未冒充公开节点链路验收。"""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.cloud_normals import EstimateNormalsParameters
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.normal_estimation import (
    estimate_normal_arrays,
    NormalReason,
)


def parameters(kind="knn", **changes):
    """显式解析平面验收值，不写入生产 Catalog。"""
    values = dict(
        neighborhood=dict(kind="knn", neighbors=8, support=dict(kind="unrestricted"))
        if kind == "knn"
        else dict(
            kind=kind, radius=1.8, **(dict(max_neighbors=8) if kind == "hybrid" else {})
        ),
        quality=dict(
            min_support_points=3,
            min_normal_gap=0.01,
            max_rms=1e-5,
            max_surface_variation=1e-8,
        ),
        orientation=dict(kind="direction", direction=[0, 0, 1], min_abs_cosine=0.1),
        frame_id="sensor",
        length_unit="mm",
        existing_normals="reject",
        diagnostics=True,
    )
    values.update(changes)
    return EstimateNormalsParameters(**values)


def execute(points, p, *, rows=4, budget=1_000_000, cancel=lambda: None):
    """稳定身份故意反序且大于 JS 整数精度范围。"""
    ids = np.arange(len(points), dtype="u8")[::-1] + 2**53 + 1
    return estimate_normal_arrays(
        points, ids, p, max_working_bytes=budget, chunk_rows=rows, cancel=cancel
    )


@pytest.mark.parametrize("kind", ["knn", "radius", "hybrid"])
@pytest.mark.parametrize("dtype", ["f4", "f8"])
def test_plane_independent_svd_and_unchanged_input(kind, dtype):
    xy = np.array([(x, y) for x in range(5) for y in range(5)], dtype=dtype)
    points = np.column_stack((xy, xy[:, 0] * 0.25 - xy[:, 1] * 0.5 + 2)).astype(dtype)
    original = points.tobytes()
    p = parameters(kind)
    result = execute(points, p)
    for i, point in enumerate(points):
        distance = np.linalg.norm(points.astype(float) - point, axis=1)
        ids = np.arange(len(points), dtype="u8")[::-1] + 2**53 + 1
        candidates = sorted(
            (
                j
                for j in range(len(points))
                if i != j and (kind == "knn" or distance[j] <= 1.8)
            ),
            key=lambda j: (distance[j], int(ids[j]), j),
        )
        if kind != "radius":
            candidates = candidates[:8]
        support = points[[i, *candidates]].astype(float)
        _, _, vh = np.linalg.svd(support - support.mean(axis=0), full_matrices=False)
        expected = vh[-1] * (1 if vh[-1, 2] >= 0 else -1)
        np.testing.assert_allclose(
            result["normals"][i],
            expected,
            rtol=0,
            atol=2e-7 if dtype == "f4" else 2e-14,
        )
        assert result["normal_neighbors"][i, 0] == len(candidates)
    assert result["normal_valid"].all() and result["normal_oriented"].all()
    assert not result["normal_reason"].any()
    assert points.tobytes() == original and result["normals"].dtype == points.dtype
    alternate = execute(points, p, rows=11)
    for name in result:
        np.testing.assert_array_equal(result[name], alternate[name])


@pytest.mark.parametrize("kind", ["knn", "radius", "hybrid"])
def test_degenerate_sparse_duplicate_and_cancel(kind):
    p = parameters(kind)
    for points in (
        np.zeros((9, 3), dtype="f4"),
        np.column_stack((np.arange(9), np.zeros((9, 2)))).astype("f4"),
    ):
        result = execute(points, p)
        assert not result["normal_valid"].any() and not result["normals"].any()
        assert np.isin(
            result["normal_reason"],
            [NormalReason.DEGENERATE_SUPPORT, NormalReason.INSUFFICIENT_SUPPORT],
        ).all()
    one = execute(np.zeros((1, 3), dtype="f4"), p)
    assert one["normal_reason"][0, 0] == NormalReason.INSUFFICIENT_SUPPORT
    points = np.array([(x, y, 0) for x in range(3) for y in range(3)], dtype="f8")
    completed = False
    for at in range(1, 200):
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == at:
                raise RuntimeError("cancel")

        try:
            execute(points, p, cancel=cancel)
            completed = True
            break
        except RuntimeError as e:
            assert str(e) == "cancel"
    assert completed


def test_orientation_is_independent_of_axis_validity():
    points = np.array([(x, y, 0) for x in range(3) for y in range(3)], dtype="f8")
    unsigned = execute(points, parameters(orientation=dict(kind="unoriented")))
    assert unsigned["normal_valid"].all() and not unsigned["normal_oriented"].any()
    perpendicular = execute(
        points,
        parameters(
            orientation=dict(kind="direction", direction=[1, 0, 0], min_abs_cosine=0.1)
        ),
    )
    assert (
        perpendicular["normal_valid"].all()
        and not perpendicular["normal_oriented"].any()
    )
    assert (perpendicular["normal_reason"] == NormalReason.ORIENTATION_AMBIGUOUS).all()
    for facing, sign in (("toward", 1), ("away", -1)):
        result = execute(
            points,
            parameters(
                orientation=dict(
                    kind="viewpoint",
                    position=[1, 1, 10],
                    facing=facing,
                    min_abs_cosine=0.1,
                )
            ),
        )
        assert result["normal_oriented"].all()
        np.testing.assert_allclose(
            result["normals"], np.tile([0, 0, sign], (9, 1)), rtol=0, atol=1e-14
        )
    coincident = execute(
        points,
        parameters(
            orientation=dict(
                kind="viewpoint",
                position=[1, 1, 0],
                facing="toward",
                min_abs_cosine=0.1,
            )
        ),
    )
    assert coincident["normal_valid"][4] and not coincident["normal_oriented"][4]


def test_budget_precision_and_contract_errors():
    p = parameters("radius")
    points = np.zeros((50, 3), dtype="f4")
    for budget in (1, 16000):
        with pytest.raises(InvalidRequestError, match="预算"):
            execute(points, p, budget=budget)
    with pytest.raises(ValidationError):
        parameters(
            orientation=dict(kind="direction", direction=[0, 0, 0], min_abs_cosine=0.1)
        )
    with pytest.raises(ValidationError):
        parameters(neighborhood=dict(kind="hybrid", radius=1, max_neighbors=1))
    with pytest.raises(ValidationError):
        parameters(neighborhood=dict(kind="radius", radius=float("inf")))
    empty = execute(np.empty((0, 3), dtype="f4"), parameters(diagnostics=False))
    assert set(empty) == {"normals", "normal_valid", "normal_oriented", "normal_reason"}
    assert all(len(v) == 0 for v in empty.values())


@pytest.mark.parametrize("scale", [1e-100, 1.0, 1e100])
def test_scaled_plane_and_tie_identity(scale):
    """协方差量纲不影响轴；等距壳层按真实身份选取而非 KDTree 顺序。"""
    points = (
        np.array(
            [(x, y, 0.25 * x - 0.5 * y) for x in range(4) for y in range(4)], dtype="f8"
        )
        * scale
    )
    p = parameters(
        quality=dict(
            min_support_points=3,
            min_normal_gap=0.01,
            max_rms=scale * 1e-6,
            max_surface_variation=1e-10,
        )
    )
    out = execute(points, p)
    expected = np.array([-0.25, 0.5, 1.0])
    expected /= np.linalg.norm(expected)
    assert out["normal_valid"].all()
    np.testing.assert_allclose(
        out["normals"], np.tile(expected, (len(points), 1)), rtol=0, atol=1e-13
    )
    with pytest.raises(InvalidRequestError, match="数值范围"):
        execute(np.array([[1e200, 0, 0], [-1e200, 0, 0], [0, 1, 0]], dtype="f8"), p)


def test_spherical_patch_and_quality_failure_against_independent_svd():
    """球面解析方向及非共面 SVD 对照，质量失败不得写出成功法向。"""
    xy = np.array(
        [(x, y) for x in np.linspace(-0.2, 0.2, 9) for y in np.linspace(-0.2, 0.2, 9)]
    )
    points = np.column_stack((xy, np.sqrt(4 - (xy * xy).sum(axis=1))))
    p = parameters(
        quality=dict(
            min_support_points=3,
            min_normal_gap=0.01,
            max_rms=0.1,
            max_surface_variation=0.1,
        )
    )
    result = execute(points, p)
    assert result["normal_valid"].all()
    np.testing.assert_allclose(result["normals"][40], [0, 0, 1], atol=1e-13, rtol=0)
    ids = np.arange(len(points), dtype="u8")[::-1] + 2**53 + 1
    for i in (0, 23, 40, 80):
        d = np.linalg.norm(points - points[i], axis=1)
        selected = sorted(
            (j for j in range(len(points)) if j != i),
            key=lambda j: (d[j], int(ids[j]), j),
        )[:8]
        support = points[[i, *selected]]
        _, s, vh = np.linalg.svd(support - support.mean(axis=0), full_matrices=False)
        expected = vh[-1] * (1 if vh[-1, 2] >= 0 else -1)
        np.testing.assert_allclose(result["normals"][i], expected, rtol=0, atol=1e-13)
        assert result["normal_rms"][i, 0] == pytest.approx(s[-1] / 3, abs=1e-15)
    strict = execute(
        points,
        parameters(
            quality=dict(
                min_support_points=3,
                min_normal_gap=0.01,
                max_rms=0,
                max_surface_variation=0,
            )
        ),
    )
    assert not strict["normal_valid"].any() and not strict["normals"].any()
    assert (strict["normal_reason"] == NormalReason.QUALITY_FAILED).all()


@pytest.mark.parametrize("kind", ["knn", "hybrid"])
def test_equal_shell_batched_pca_matches_single_row_exactly(kind):
    """密集等距壳层按原始身份截断，批量 PCA 与逐点输出逐位相同。"""
    points = np.array([(x, y, 0) for x in range(20) for y in range(20)], dtype="f4")
    p = parameters(kind)
    single = execute(points, p, rows=1)
    batch = execute(points, p, rows=200)
    for name in single:
        np.testing.assert_array_equal(single[name], batch[name])
