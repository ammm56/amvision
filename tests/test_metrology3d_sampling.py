"""受控原生采样诊断的独立整数真值、来源与生命周期验证。"""

import numpy as np
import pytest

from backend.contracts.workflows.edge3d import SamplingBoundarySettings
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.edge_sampling import (
    sampling_candidates,
    SamplingStatus,
)
from custom_nodes.metrology3d_nodes.shared.estimate_normals import estimate_normals
from tests.test_metrology3d_normal_estimation import parameters
from tests.test_metrology3d_preprocess import make_cloud
from tests.point_cloud_support import policy


def prepare(dtype="float64", rows=64, *, hole=False, duplicate=False):
    """真实 B03 法向配合解析整数网格，不从被测边界生成期望。"""
    xy = np.asarray(list(np.ndindex(7, 7)), dtype=dtype)
    if hole:
        xy = xy[~((xy >= 2) & (xy <= 4)).all(axis=1)]
    points = np.column_stack((xy, np.zeros(len(xy), dtype=dtype)))
    if duplicate:
        points = np.vstack((points, points[:1]))
    scope, runtime, source = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(
            max_working_bytes=8_000_000,
            max_live_array_bytes=8_000_000,
            max_decoded_bytes=8_000_000,
            chunk_rows=rows,
        ),
    )
    cloud, _ = estimate_normals(
        runtime,
        source,
        parameters(
            "radius",
            neighborhood=dict(kind="radius", radius=1.8),
            frame_id=source.spatial.frame_id,
        ),
        cancel=lambda: None,
    )
    settings = SamplingBoundarySettings(
        kind="sampling-boundary",
        radius=1.5,
        max_neighbors=16,
        min_neighbors=3,
        angle_degrees=120.0,
    )
    return scope, runtime, source, cloud, settings, xy


@pytest.mark.parametrize("dtype", ["float32", "float64"])
@pytest.mark.parametrize("rows", [1, 8, 128])
def test_sampling_grid_truth_and_full_halo(dtype, rows):
    scope, runtime, source, cloud, settings, xy = prepare(dtype, rows)
    try:
        baseline = runtime.budget.used
        result = sampling_candidates(runtime, cloud, settings, cancel=lambda: None)
        expected = ((xy == 0) | (xy == 6)).any(axis=1)
        with result.borrow(runtime) as data:
            np.testing.assert_array_equal(data["candidate"][:, 0], expected)
            np.testing.assert_array_equal(
                data["identity_rows"][:, 0], np.arange(len(xy))
            )
            assert not data["status"].any()
            assert all(not value.flags.writeable for value in data.values())
        assert result.candidate_count == 24
        runtime.storage_scope.close_resource(result.resource_key)
        assert runtime.budget.used == baseline
        with pytest.raises(InvalidRequestError, match="已释放"):
            with result.borrow(runtime):
                pass
    finally:
        assert scope.close() == ()


@pytest.mark.parametrize("radius", [1.0, np.nextafter(1.0, np.inf), np.sqrt(2.0), 1.5])
@pytest.mark.parametrize("rows", [1, 128])
def test_radius_boundary_counts_match_actual_native_search(radius, rows):
    """精确半径邻点不能被 SciPy 闭区间误计入 Open3D 的开区间。"""
    from custom_nodes.metrology3d_nodes.shared.native_geometry import require_open3d

    scope, runtime, _, cloud, settings, _ = prepare(rows=rows)
    try:
        settings = settings.model_copy(update={"radius": float(radius)})
        result = sampling_candidates(runtime, cloud, settings, cancel=lambda: None)
        with runtime.borrow(cloud) as view:
            xyz = np.concatenate(
                [
                    view.chunk(start, min(cloud.point_count, start + rows))["positions"]
                    for start in range(0, cloud.point_count, rows)
                ]
            ).astype("float64")
        o3d = require_open3d()
        tensor = o3d.core.Tensor(xyz)
        index = o3d.core.nns.NearestNeighborSearch(tensor)
        index.hybrid_index()
        _, _, counts = index.hybrid_search(tensor, float(radius), cloud.point_count)
        with result.borrow(runtime) as data:
            np.testing.assert_array_equal(data["neighbors"][:, 0], counts.numpy())
            if radius == 1.0:
                assert np.all(data["neighbors"] == 1)
                assert np.all(data["status"] & int(SamplingStatus.INSUFFICIENT))
                assert result.candidate_count == 0
    finally:
        assert scope.close() == ()


def test_sampling_gap_is_candidate_not_material_classification():
    scope, runtime, _, cloud, settings, xy = prepare(hole=True)
    try:
        settings = settings.model_copy(update={"radius": 1.01, "min_neighbors": 3})
        result = sampling_candidates(runtime, cloud, settings, cancel=lambda: None)
        occupied = set(map(tuple, xy))
        expected = np.array(
            [
                any(
                    (x + dx, y + dy) not in occupied
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                )
                for x, y in xy
            ]
        )
        with result.borrow(runtime) as data:
            expected &= data["status"][:, 0] == 0
            np.testing.assert_array_equal(data["candidate"][:, 0], expected)
        assert result.candidate_count > 0
        assert not hasattr(result, "geometry")
    finally:
        assert scope.close() == ()


def test_duplicate_and_saturated_diagnostics_not_success():
    scope, runtime, _, cloud, settings, _ = prepare(duplicate=True)
    try:
        result = sampling_candidates(runtime, cloud, settings, cancel=lambda: None)
        with result.borrow(runtime) as data:
            assert data["status"][0, 0] & SamplingStatus.DUPLICATE
            assert not data["candidate"][0, 0]
        settings = settings.model_copy(update={"max_neighbors": 4})
        result = sampling_candidates(runtime, cloud, settings, cancel=lambda: None)
        with result.borrow(runtime) as data:
            saturated = data["neighbors"][:, 0] > 4
            assert saturated.any()
            assert np.all(data["status"][saturated, 0] & SamplingStatus.SATURATED)
            assert not data["candidate"][saturated].any()
    finally:
        assert scope.close() == ()


@pytest.mark.parametrize("phase", [1, 10, 25])
def test_sampling_cancel_releases_output(phase):
    scope, runtime, _, cloud, settings, _ = prepare(rows=4)
    try:
        baseline, calls = runtime.budget.used, 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == phase:
                raise InterruptedError("cancel-sampling")

        with pytest.raises(InterruptedError):
            sampling_candidates(runtime, cloud, settings, cancel=cancel)
        assert runtime.budget.used == baseline
        runtime.policy = runtime.policy.model_copy(update={"max_working_bytes": 100})
        with pytest.raises(InvalidRequestError, match="预算"):
            sampling_candidates(runtime, cloud, settings, cancel=lambda: None)
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


def test_sampling_registered_output_cancel_and_parent_release(monkeypatch):
    from custom_nodes.metrology3d_nodes.shared import edge_sampling as module

    scope, runtime, _, cloud, settings, _ = prepare()
    try:
        baseline = runtime.budget.used
        registered = False
        original = module.own_output

        def own(*args):
            nonlocal registered
            result = original(*args)
            registered = True
            return result

        def cancel():
            if registered:
                raise InterruptedError("after-register")

        monkeypatch.setattr(module, "own_output", own)
        with pytest.raises(InterruptedError):
            sampling_candidates(runtime, cloud, settings, cancel=cancel)
        assert runtime.budget.used == baseline
        result = sampling_candidates(runtime, cloud, settings, cancel=lambda: None)
        runtime.close()
        with pytest.raises(InvalidRequestError):
            with result.borrow(runtime):
                pass
    finally:
        assert scope.close() == ()
