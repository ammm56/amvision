"""B08 固定格、逐行真值、生成来源与取消回收；不使用被测分箱生成期望。"""

import math
import statistics
from dataclasses import replace

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.height_map3d import HeightMapParameters
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.height_grid import grid_working_bytes
from custom_nodes.metrology3d_nodes.shared.height_map import cloud_to_height_map
from tests.point_cloud_support import policy
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_point_cloud_runtime import method, own


def parameters(aggregation="mean", **changes):
    """显式解析例网格；不作为节点的默认格距或容量。"""
    return HeightMapParameters.model_validate(
        dict(
            frame=dict(kind="current-frame", frame_id="fixture"),
            length_unit="mm",
            grid=dict(
                kind="orthographic-height",
                origin=(0, 0, 0),
                column_direction=(1, 0, 0),
                row_direction=(0, 1, 0),
                height_direction=(0, 0, 1),
                column_step=1,
                row_step=2,
            ),
            width=3,
            height=2,
            aggregation=aggregation,
            **changes,
        )
    )


def truth(points, params):
    """逐行比较各格的显式半开区间，不调用 NumPy 分箱或被测投影。"""
    groups = [[] for _ in range(params.cell_count())]
    for index, (x, y, _) in enumerate(points):
        for row in range(params.height):
            for column in range(params.width):
                if (
                    column - 0.5 <= float(x) < column + 0.5
                    and 2 * row - 1 <= float(y) < 2 * row + 1
                ):
                    groups[row * params.width + column].append(index)
    return groups


@pytest.mark.parametrize("aggregation", ["minimum", "maximum", "mean", "median"])
@pytest.mark.parametrize("dtype", ["float32", "float64"])
@pytest.mark.parametrize("rows", [1, 7, 1000])
def test_independent_half_open_cells_precision_and_empty(aggregation, dtype, rows):
    positions = np.array(
        [
            [-0.5, -1, 1],
            [0, 0, 2],
            [0.1, 0, 8],
            [0.2, 0, -2],
            [0.5, 1, 10],
            [1.4, 1, 20],
            [2.5, 0, 300],
            [0, 3, 400],
            [-0.6, 0, 500],
            [0, -1.1, 600],
            [np.nextafter(np.array(0.5, dtype=dtype), np.array(-1, dtype=dtype)), 0, 3],
        ],
        dtype=dtype,
    )
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=positions,
        runtime_policy=policy(max_working_bytes=1_000_000, chunk_rows=rows),
    )
    baseline = runtime.budget.used
    p = parameters(aggregation)
    try:
        result = cloud_to_height_map(runtime, cloud, p, cancel=lambda: None)
        groups = truth(positions, p)
        with result.borrow(runtime) as arrays:
            assert arrays["heights"].dtype == np.dtype(dtype)
            assert all(not a.flags.writeable for a in arrays.values())
            for cell, group in enumerate(groups):
                start, stop = arrays["member_offsets"][cell : cell + 2, 0]
                np.testing.assert_array_equal(
                    arrays["input_rows"][start:stop, 0], group
                )
                np.testing.assert_array_equal(
                    arrays["source_rows"][start:stop, 0], group
                )
                assert arrays["counts"][cell, 0] == len(group)
                if not group:
                    assert all(
                        np.isnan(arrays[k][cell, 0])
                        for k in ("heights", "minimum", "maximum")
                    )
                    continue
                values = [float(positions[i, 2]) for i in group]
                expected = {
                    "minimum": min,
                    "maximum": max,
                    "mean": statistics.mean,
                    "median": statistics.median,
                }[aggregation](values)
                assert arrays["heights"][cell, 0] == np.array(expected, dtype=dtype)
                assert arrays["minimum"][cell, 0] == min(values)
                assert arrays["maximum"][cell, 0] == max(values)
        assert result.outside_count == 4
        assert result.occupied_count == sum(bool(g) for g in groups)
        runtime.storage_scope.close_resource(result.resource_key)
        assert runtime.budget.used == baseline
        with pytest.raises((InvalidRequestError, RuntimeError)):
            with result.borrow(runtime):
                pass
    finally:
        assert scope.close() == ()
    assert runtime.budget.used == 0


@pytest.mark.parametrize("aggregation", ["minimum", "maximum", "mean", "median"])
def test_subset_original_source_identity(aggregation):
    points = np.array([[0, 0, 1.2], [0, 0, 8.3], [1, 0, 4.4], [0, 0, -2.1]], dtype="f8")
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(max_working_bytes=1_000_000),
    )
    try:
        child = runtime.register_subset(
            parent=cloud,
            method=method(),
            indices=own(runtime, {"indices": np.array([[1], [2], [3]], dtype="u4")}),
            cancel=lambda: None,
        )
        result = cloud_to_height_map(
            runtime, child, parameters(aggregation), cancel=lambda: None
        )
        with result.borrow(runtime) as arrays:
            np.testing.assert_array_equal(arrays["source_rows"][:, 0], [1, 3, 2])
            np.testing.assert_array_equal(arrays["input_rows"][:, 0], [0, 2, 1])
            assert runtime.source_point_count(child) == 4
    finally:
        scope.close()


@pytest.mark.parametrize("aggregation", ["mean", "median"])
@pytest.mark.parametrize("values", [[1.6e308, 1.7e308], [-1.6e308, 1.6e308], [0, 0]])
def test_finite_large_values_do_not_overflow_sum(aggregation, values):
    points = np.array([[0, 0, z] for z in values], dtype="f8")
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(max_working_bytes=1_000_000),
    )
    try:
        result = cloud_to_height_map(
            runtime, cloud, parameters(aggregation), cancel=lambda: None
        )
        with result.borrow(runtime) as arrays:
            assert math.isfinite(arrays["heights"][0, 0])
            assert arrays["heights"][0, 0] == pytest.approx(statistics.mean(values))
    finally:
        scope.close()


@pytest.mark.parametrize("empty", [True, False])
def test_empty_or_all_outside_is_not_zero_height(empty):
    points = np.array([[100, 0, 3]], dtype="f4")
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(max_working_bytes=1_000_000),
    )
    try:
        if empty:
            cloud = runtime.register_subset(
                parent=cloud,
                method=method(),
                indices=own(runtime, {"indices": np.empty((0, 1), dtype="u4")}),
                cancel=lambda: None,
            )
        result = cloud_to_height_map(runtime, cloud, parameters(), cancel=lambda: None)
        with result.borrow(runtime) as a:
            assert np.isnan(a["heights"]).all() and not a["counts"].any()
            assert a["input_rows"].shape == (0, 1)
        assert result.occupied_count == 0
    finally:
        scope.close()


@pytest.mark.parametrize("case", ["width", "product", "mirror", "overflow", "unknown"])
def test_contract_rejects_ambiguous_or_unrepresentable_grid(case):
    raw = parameters().model_dump()
    if case == "width":
        raw["width"] = True
    elif case == "product":
        raw.update(width=2**40, height=2**40)
    elif case == "mirror":
        raw["grid"]["height_direction"] = [0, 0, -1]
    elif case == "overflow":
        raw["grid"]["column_step"] = 1e308
    else:
        raw["fill_holes"] = True
    with pytest.raises(ValidationError):
        HeightMapParameters.model_validate(raw)


def test_tilted_pose_truth_and_stale_reference_rejected():
    from tests.test_metrology3d_pose_query import tilted_fixture

    scope, runtime, cloud, _, pose, _, _, _ = tilted_fixture()
    p = parameters().model_dump()
    p.update(
        frame=dict(
            kind="pose-frame",
            pose_id=pose.pose_id,
            target_frame_id=pose.target_frame_id,
        ),
        width=9,
        height=9,
    )
    p["grid"].update(origin=(-2, -2, 0), column_step=0.5, row_step=0.5)
    p = HeightMapParameters.model_validate(p)
    try:
        result = cloud_to_height_map(runtime, cloud, p, pose=pose, cancel=lambda: None)
        with result.borrow(runtime) as a:
            np.testing.assert_array_equal(a["counts"][:, 0], np.full(81, 2))
            expected = np.tile((5 + 0.2 * np.linspace(-2, 2, 9)) / 2, 9)
            np.testing.assert_allclose(a["heights"][:, 0], expected, atol=1e-12)
        assert result.pose_json is not None
        used = runtime.budget.used
        with pytest.raises(InvalidRequestError):
            cloud_to_height_map(
                runtime,
                cloud,
                p,
                pose=pose.model_copy(update={"run_id": "stale"}),
                cancel=lambda: None,
            )
        assert runtime.budget.used == used
    finally:
        scope.close()


def test_failed_pose_propagates_and_invalid_input_is_not_silently_filtered():
    from tests.test_metrology3d_pose_query import tilted_fixture
    from custom_nodes.metrology3d_nodes.shared.build_frame import build_frame

    scope, runtime, cloud, groups, pose, config, rotation, _ = tilted_fixture()
    try:
        p = parameters().model_dump()
        p["frame"] = dict(
            kind="pose-frame",
            pose_id=pose.pose_id,
            target_frame_id=pose.target_frame_id,
        )
        bad_config = config.model_copy(
            update={
                "x_axis": config.x_axis.model_copy(
                    update={"direction": tuple(rotation[:, 2])}
                )
            }
        )
        # X 与 Z 重合产生真实无效位姿，不伪造运行记录。
        failed = build_frame(runtime, groups[:1], bad_config, cancel=lambda: None)
        if failed.state == "found":
            pytest.fail("测试需要无效的真实位姿")
        result = cloud_to_height_map(
            runtime,
            cloud,
            HeightMapParameters.model_validate(p),
            pose=failed,
            cancel=lambda: None,
        )
        assert result.owner is None and result.reason is not None
    finally:
        scope.close()
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=np.array([[0, 0, np.nan]], dtype="f4"),
        runtime_policy=policy(max_working_bytes=1_000_000),
    )
    try:
        baseline = runtime.budget.used
        with pytest.raises(InvalidRequestError, match="Filter Valid"):
            cloud_to_height_map(runtime, cloud, parameters(), cancel=lambda: None)
        assert runtime.budget.used == baseline
    finally:
        scope.close()


def test_budget_rejection_and_cancel_after_owner_registration(monkeypatch):
    import custom_nodes.metrology3d_nodes.shared.height_map as module

    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=np.array([[0, 0, 1]], dtype="f4"),
        runtime_policy=policy(max_working_bytes=1_000_000),
    )
    baseline = runtime.budget.used
    try:
        original_policy = runtime.policy
        runtime.policy = original_policy.model_copy(
            update={"max_working_bytes": grid_working_bytes(1, parameters())}
        )
        with pytest.raises(InvalidRequestError, match="工作预算"):
            cloud_to_height_map(runtime, cloud, parameters(), cancel=lambda: None)
        runtime.policy = original_policy
        captured = []
        original = module.own_output

        def capture(*args):
            owner = original(*args)
            captured.append(owner)
            return owner

        def cancel():
            if captured:
                raise InterruptedError("cancel after ownership")

        monkeypatch.setattr(module, "own_output", capture)
        with pytest.raises(InterruptedError):
            cloud_to_height_map(runtime, cloud, parameters(), cancel=cancel)
        assert captured[0].closed and runtime.budget.used == baseline
    finally:
        scope.close()


def test_generated_members_keep_input_identity_not_fake_source_rows():
    from custom_nodes.metrology3d_nodes.shared.resample import resample_cloud
    from backend.contracts.workflows.cloud_preprocess import ResampleCloudParameters

    points = np.array([[0, 0, 0], [0.1, 0, 2], [1, 0, 3]], dtype="f4")
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(max_working_bytes=1_000_000),
    )
    try:
        generated, _ = resample_cloud(
            runtime,
            cloud,
            ResampleCloudParameters(
                settings=dict(
                    kind="voxel-centroid",
                    grid_origin=(0, 0, 0),
                    voxel_size=10,
                    frame_id="fixture",
                    length_unit="mm",
                    max_position_error=1e-5,
                    attributes="positions-only",
                )
            ),
            cancel=lambda: None,
        )
        result = cloud_to_height_map(
            runtime, generated, parameters(), cancel=lambda: None
        )
        with result.borrow(runtime) as a:
            assert "source_rows" not in a
            np.testing.assert_array_equal(a["input_rows"], [[0]])
            assert a["counts"].sum() == 1
        with runtime.borrow(generated) as view:
            np.testing.assert_array_equal(
                view.lineage_chunk(0, 1)["source_rows"][:, 0], [0, 1, 2]
            )
        assert runtime.source_point_count(generated) == 3
    finally:
        scope.close()
    assert runtime.budget.used == 0


def test_mean_cancellation_keeps_small_height_contribution():
    points = np.array([[0, 0, 1e20], [0, 0, 1], [0, 0, -1e20]], dtype="f8")
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(max_working_bytes=1_000_000),
    )
    try:
        result = cloud_to_height_map(runtime, cloud, parameters(), cancel=lambda: None)
        with result.borrow(runtime) as a:
            assert a["heights"][0, 0] == pytest.approx(1 / 3)
    finally:
        scope.close()


def test_every_cancel_point_returns_live_budget():
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=np.array([[0, 0, 1], [1, 0, 3]], dtype="f4"),
        runtime_policy=policy(max_working_bytes=1_000_000),
    )
    try:
        base, calls = runtime.budget.used, 0

        def count():
            nonlocal calls
            calls += 1

        result = cloud_to_height_map(runtime, cloud, parameters(), cancel=count)
        runtime.storage_scope.close_resource(result.resource_key)
        for fail_at in range(1, calls + 1):
            counter = 0

            def cancel():
                nonlocal counter
                counter += 1
                if counter == fail_at:
                    raise InterruptedError("explicit cancellation")

            with pytest.raises(InterruptedError):
                cloud_to_height_map(runtime, cloud, parameters(), cancel=cancel)
            assert runtime.budget.used == base
    finally:
        scope.close()


@pytest.mark.parametrize("generated", [False, True])
def test_saved_input_restores_same_height_members(tmp_path, generated):
    from custom_nodes.metrology3d_nodes.shared.cloud_assets import (
        save_cloud,
        read_asset,
    )
    from custom_nodes.metrology3d_nodes.shared.resample import resample_cloud
    from backend.contracts.workflows.cloud_preprocess import ResampleCloudParameters
    from tests.point_cloud_support import create_resource_service
    from tests.test_point_cloud_assets import POLICY

    points = np.array([[0, 0, 0], [0.1, 0, 2], [1, 0, 3]], dtype="f4")
    scope, runtime, source = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(max_working_bytes=1_000_000),
    )
    try:
        if generated:
            source, _ = resample_cloud(
                runtime,
                source,
                ResampleCloudParameters(
                    settings=dict(
                        kind="voxel-centroid",
                        grid_origin=(0, 0, 0),
                        voxel_size=10,
                        frame_id="fixture",
                        length_unit="mm",
                        max_position_error=1e-5,
                        attributes="positions-only",
                    )
                ),
                cancel=lambda: None,
            )
        service = create_resource_service(tmp_path)
        asset = save_cloud(
            runtime,
            source,
            service=service,
            project_id="test",
            mode="derived",
            name="height-input",
            write_identity="a" * 64,
            policy=replace(POLICY, chunk_bytes=128),
            cancel=lambda: None,
        )
        restored = read_asset(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=replace(POLICY, chunk_bytes=128),
            cancel=lambda: None,
        )
        a = cloud_to_height_map(runtime, source, parameters(), cancel=lambda: None)
        b = cloud_to_height_map(runtime, restored, parameters(), cancel=lambda: None)
        with a.borrow(runtime) as first, b.borrow(runtime) as second:
            for key in first:
                assert first[key].tobytes() == second[key].tobytes()
            with pytest.raises(RuntimeError, match="活跃借用"):
                a.owner.close()
        assert runtime.source_point_count(source) == runtime.source_point_count(
            restored
        )
        assert source.lineage_kind == restored.lineage_kind
    finally:
        assert scope.close() == () and runtime.budget.used == 0
