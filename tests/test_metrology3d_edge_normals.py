"""法向候选使用实际 B03 输出，独立距离/夹角真值与完整支持反例。"""

import numpy as np
import pytest

from backend.contracts.workflows.edge3d import NormalCreaseSettings
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.edge_normal_candidates import (
    normal_crease_candidates,
    NormalNeighborhoodStatus,
    SUPPORT_REASONS,
)
from custom_nodes.metrology3d_nodes.shared.estimate_normals import estimate_normals
from tests.test_metrology3d_normal_estimation import parameters
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_metrology3d_edge_support import crease_settings
from tests.integration.metrology3d.representative_recipe import boxes
from tests.point_cloud_support import policy


def prepare(*, dtype="float64", rows=32, flat=False, missing=False):
    """解析 60 度折面，法向来自已有节点计算，不手填算法结果。"""
    angle = 0 if flat else np.pi / 3
    side = np.asarray(
        [(x, y, 0) for x in (0.2, 0.4, 0.6, 0.8, 1) for y in np.arange(-1, 1.01, 0.2)],
        dtype=float,
    )
    left = side.copy()
    left[:, 0] *= -1
    side[:, 2] = side[:, 0] * np.sin(angle)
    side[:, 0] *= np.cos(angle)
    points = np.vstack((left, side)).astype(dtype)
    if missing:
        points = np.vstack((points, [[5, 5, 5]])).astype(dtype)
    scope, runtime, source = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(
            max_working_bytes=5_000_000, max_live_array_bytes=5_000_000, chunk_rows=rows
        ),
    )
    normal, _ = estimate_normals(
        runtime,
        source,
        parameters(
            "radius",
            neighborhood=dict(kind="radius", radius=0.26),
            frame_id=source.spatial.frame_id,
            length_unit="mm",
            orientation=dict(kind="unoriented"),
        ),
        cancel=lambda: None,
    )
    raw = crease_settings().model_dump()
    raw.update(
        radius=0.5,
        max_neighbors=64,
        max_pair_distance=0.38,
        support_a=boxes("a", [[-2, -0.01, -2, 2, -2, 2]]),
        support_b=boxes("b", [[0.01, 2, -2, 2, -2, 2]]),
    )
    raw["support"].update(radius=0.9, min_tangent_ratio=0.01, min_normal_gap=0.01)
    return scope, runtime, source, normal, NormalCreaseSettings.model_validate(raw)


@pytest.mark.parametrize("dtype,rows", [("float32", 1), ("float64", 32)])
def test_real_normals_exact_candidate_pairs_and_support(dtype, rows):
    scope, runtime, source, cloud, settings = prepare(dtype=dtype, rows=rows)
    try:
        baseline = runtime.budget.used
        result = normal_crease_candidates(runtime, cloud, settings, cancel=lambda: None)
        with runtime.borrow(cloud) as view:
            blocks = [
                view.chunk(i, min(i + rows, cloud.point_count))
                for i in range(0, cloud.point_count, rows)
            ]
            points = np.concatenate([v["positions"] for v in blocks]).astype(float)
        distances = np.linalg.norm(points[:, None] - points, axis=2)
        # 两侧仅距 y 轴最近的一排、相同 Y 可以落入 0.38 mm。
        half = cloud.point_count // 2
        expected = [
            (a, b)
            for a in range(half)
            for b in range(half, len(points))
            if distances[a, b] <= 0.38
        ]
        assert len(expected) == 11
        assert result.candidate_count == result.supported_count == len(expected)
        with result.borrow(runtime) as arrays:
            np.testing.assert_array_equal(arrays["pairs"], expected)
            np.testing.assert_allclose(arrays["angle"], np.pi / 3, atol=2e-6)
            np.testing.assert_array_equal(
                arrays["neighbors"][:, 0], (distances <= 0.5).sum(axis=1)
            )
            np.testing.assert_array_equal(
                arrays["source_rows"][:, 0], np.arange(cloud.point_count)
            )
            assert not arrays["status"].any() and not arrays["reason"].any()
            assert all(not a.flags.writeable for a in arrays.values())
        runtime.storage_scope.close_resource(result.resource_key)
        assert runtime.budget.used == baseline
        with pytest.raises(InvalidRequestError, match="已释放"):
            with result.borrow(runtime):
                pass
    finally:
        assert scope.close() == ()


def test_flat_plane_and_saturated_neighbors_never_form_crease():
    for flat in (False, True):
        scope, runtime, _, cloud, settings = prepare(flat=flat)
        try:
            if not flat:
                settings = settings.model_copy(update={"max_neighbors": 3})
            result = normal_crease_candidates(
                runtime, cloud, settings, cancel=lambda: None
            )
            assert result.candidate_count == 0
            with result.borrow(runtime) as data:
                if not flat:
                    assert (data["status"] == NormalNeighborhoodStatus.SATURATED).all()
                    assert data["neighbors"].min() > 3
        finally:
            assert scope.close() == ()


def test_invalid_normal_is_retained_and_missing_support_is_not_success():
    scope, runtime, _, cloud, settings = prepare(missing=True)
    try:
        result = normal_crease_candidates(runtime, cloud, settings, cancel=lambda: None)
        with result.borrow(runtime) as data:
            assert data["status"][-1, 0] == NormalNeighborhoodStatus.INVALID_NORMAL
            assert data["source_rows"][-1, 0] == cloud.point_count - 1
        raw = settings.model_dump()
        raw["support_b"] = boxes("empty", [[10, 11, 10, 11, 10, 11]])
        failed = normal_crease_candidates(
            runtime,
            cloud,
            NormalCreaseSettings.model_validate(raw),
            cancel=lambda: None,
        )
        assert failed.candidate_count == 11 and failed.supported_count == 0
        with failed.borrow(runtime) as data:
            assert all(
                SUPPORT_REASONS[int(v)]
                in ("unassigned_support", "insufficient_support")
                for v in data["reason"][:, 0]
            )
    finally:
        assert scope.close() == ()


@pytest.mark.parametrize("phase", [1, 20, 150, 500])
def test_cancel_and_budget_do_not_retain_output(phase):
    scope, runtime, _, cloud, settings = prepare()
    try:
        baseline, calls = runtime.budget.used, 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == phase:
                raise InterruptedError("cancel-crease")

        with pytest.raises(InterruptedError):
            normal_crease_candidates(runtime, cloud, settings, cancel=cancel)
        assert runtime.budget.used == baseline
        runtime.policy = runtime.policy.model_copy(update={"max_working_bytes": 1024})
        with pytest.raises(InvalidRequestError, match="预算"):
            normal_crease_candidates(runtime, cloud, settings, cancel=lambda: None)
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


def test_missing_normal_rejected_and_registration_cancelled():
    scope, runtime, source, cloud, settings = prepare()
    try:
        with pytest.raises(InvalidRequestError, match="已有计算法向"):
            normal_crease_candidates(runtime, source, settings, cancel=lambda: None)
        baseline = runtime.budget.used

        def cancel():
            if runtime.budget.used > baseline:
                raise InterruptedError("owner")

        with pytest.raises(InterruptedError, match="owner"):
            normal_crease_candidates(runtime, cloud, settings, cancel=cancel)
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


def test_noncontiguous_source_rows_and_normal_sign_invariance(monkeypatch):
    from custom_nodes.metrology3d_nodes.shared import estimate_normals as module
    from custom_nodes.metrology3d_nodes.shared.resample import resample_cloud
    from tests.test_metrology3d_resample import parameters as resample_parameters

    original = module.estimate_normal_arrays

    def reversed_normals(*args, **kwargs):
        values = original(*args, **kwargs)
        values["normals"][::2] *= -1
        return values

    records = []
    for flip in (False, True):
        if flip:
            monkeypatch.setattr(module, "estimate_normal_arrays", reversed_normals)
        scope, runtime, _, cloud, settings = prepare()
        try:
            subset, _ = resample_cloud(
                runtime, cloud, resample_parameters("stride"), cancel=lambda: None
            )
            result = normal_crease_candidates(
                runtime, subset, settings, cancel=lambda: None
            )
            with result.borrow(runtime) as data:
                np.testing.assert_array_equal(
                    data["source_rows"][:, 0], np.arange(1, cloud.point_count, 2)
                )
                records.append({k: a.copy() for k, a in data.items()})
            assert runtime.source_point_count(subset) == cloud.point_count
        finally:
            assert scope.close() == ()
    for key in records[0]:
        np.testing.assert_allclose(records[0][key], records[1][key], rtol=0, atol=0)


def test_invalid_nearby_normal_is_not_silently_dropped(monkeypatch):
    from custom_nodes.metrology3d_nodes.shared import estimate_normals as module

    original = module.estimate_normal_arrays

    def invalid_neighbor(*args, **kwargs):
        values = original(*args, **kwargs)
        values["normals"][5] = 0
        values["normal_valid"][5] = 0
        values["normal_oriented"][5] = 0
        values["normal_reason"][5] = 1
        return values

    monkeypatch.setattr(module, "estimate_normal_arrays", invalid_neighbor)
    scope, runtime, _, cloud, settings = prepare()
    try:
        result = normal_crease_candidates(runtime, cloud, settings, cancel=lambda: None)
        with result.borrow(runtime) as data:
            assert data["status"][5, 0] == NormalNeighborhoodStatus.INVALID_NORMAL
            assert np.any(
                data["status"] == NormalNeighborhoodStatus.INVALID_NEIGHBOR_NORMAL
            )
            assert 5 not in data["pairs"]
            assert len(data["source_rows"]) == cloud.point_count
    finally:
        assert scope.close() == ()


def test_two_observed_points_keep_candidate_but_fail_fitting_support():
    """搜索不隐含三点门槛，真正的拟面最少点数仍严格检查。"""
    from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi

    scope, runtime, _, cloud, settings = prepare()
    try:
        subset, _ = crop_roi(
            runtime,
            cloud,
            boxes(
                "two",
                [
                    [-0.21, -0.19, -0.01, 0.01, -1, 1],
                    [0.09, 0.11, -0.01, 0.01, -1, 1],
                ],
            ),
            cancel=lambda: None,
        )
        assert subset.point_count == 2
        result = normal_crease_candidates(
            runtime, subset, settings, cancel=lambda: None
        )
        assert result.candidate_count == 1 and result.supported_count == 0
        with result.borrow(runtime) as data:
            assert not data["status"].any()
            assert SUPPORT_REASONS[int(data["reason"][0, 0])] == "insufficient_support"
    finally:
        assert scope.close() == ()
