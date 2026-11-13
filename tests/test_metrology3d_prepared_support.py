"""批量基准支持与原标量规则逐证据对照；数值仅为测试配置。"""

import numpy as np
import pytest

from backend.contracts.workflows.measurement3d_parameters import DirectionalEvaluation
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.measurement_support import (
    plane_coverage,
    support_snapshot,
)
from custom_nodes.metrology3d_nodes.shared.measurement_reference import (
    reference_coverage,
)
from custom_nodes.metrology3d_nodes.shared.prepared_plane_support import (
    prepare_plane_support,
)
from tests.test_metrology3d_height_step import two_planes
from tests.test_metrology3d_measurement_contracts import measurement_policy
from tests.test_metrology3d_reference_extension import offset_planes
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_metrology3d_plane import plane_parameters
from tests.point_cloud_support import policy
from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane


def settings(point=(0, 0, 0), radius=2, direction=(0, 0, 1)):
    """已解析的测量线，沿用高度/高差公开参数及质量。"""
    return DirectionalEvaluation(
        query_position=point,
        direction=direction,
        support_radius=radius,
        quality_policy=measurement_policy(),
        reference_policy=dict(kind="plane-extension", max_extension_distance=1),
    )


def assert_same(left, right):
    """逐字段精确对照，不只比较最终高度。"""
    assert left.support.model_dump(mode="json") == right.support.model_dump(mode="json")
    assert left.point == right.point
    assert left.nearest == right.nearest


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("slope,hole", [(0, False), (0.25, False), (0, True)])
def test_prepared_matches_scan_for_covered_holes_edges_and_parallel(dtype, slope, hole):
    scope, runtime, _, _, _, groups = two_planes(dtype=dtype, slope=slope, hole=hole)
    used = runtime.budget.used
    for group in groups:
        support_snapshot(
            runtime,
            group.items[0].support,
            "reference",
            cancel=lambda: None,
            plane=group.items[0],
        )
    resources = runtime.storage_scope.resource_count
    try:
        for feature in (g.items[0] for g in groups):
            with prepare_plane_support(
                runtime, feature, "reference", cancel=lambda: None
            ) as prepared:
                for point in (
                    (0, 0, 2),
                    (1, 0, 2),
                    (1.0000000000000002, 0, 2),
                    (10, 10, 2),
                ):
                    for radius in (0.1, 1, 2, 10):
                        p = settings(point, radius)
                        assert_same(
                            reference_coverage(
                                runtime, feature, p, cancel=lambda: None
                            ),
                            reference_coverage(
                                runtime,
                                feature,
                                p,
                                cancel=lambda: None,
                                prepared=prepared,
                            ),
                        )
                p = settings(direction=(0, 1, 0))
                assert_same(
                    reference_coverage(runtime, feature, p, cancel=lambda: None),
                    reference_coverage(
                        runtime, feature, p, cancel=lambda: None, prepared=prepared
                    ),
                )
            assert runtime.budget.used == used
            assert runtime.storage_scope.resource_count == resources
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


@pytest.mark.parametrize("shift", [0, 1e8])
@pytest.mark.parametrize("reverse", [False, True])
def test_inclined_large_coordinates_nearest_ties_and_extension_boundary(shift, reverse):
    angle = np.pi / 6
    rotation = np.array(
        [
            [np.cos(angle), 0, np.sin(angle)],
            [0, 1, 0],
            [-np.sin(angle), 0, np.cos(angle)],
        ]
    )
    origin = np.array([shift, -shift, shift])
    scope, runtime, _, groups = offset_planes(
        transform=(rotation, origin), reverse=reverse, nonuniform=True
    )
    # 原始点重复仍按最小原始行号选最近点，重复记录不得丢失。
    runtime.policy = runtime.policy.model_copy(
        update={"max_live_array_bytes": 1024 * 1024}
    )
    runtime.budget.limit = 1024 * 1024
    try:
        feature = groups[0].items[0]
        with prepare_plane_support(
            runtime, feature, "reference", cancel=lambda: None
        ) as prepared:
            for x in (0, -1, -2, -3, np.nextafter(0.0, 1.0)):
                p = settings(
                    np.array([x, 0, 0]) @ rotation.T + origin, 0.25, rotation[:, 2]
                )
                assert_same(
                    reference_coverage(runtime, feature, p, cancel=lambda: None),
                    reference_coverage(
                        runtime, feature, p, cancel=lambda: None, prepared=prepared
                    ),
                )
    finally:
        assert not scope.close()


def test_prepared_rejects_closed_foreign_or_changed_identity():
    scope, runtime, _, _, _, groups = two_planes()
    other_scope, other_runtime, *_ = two_planes()
    try:
        feature = groups[0].items[0]
        with prepare_plane_support(
            runtime, feature, "reference", cancel=lambda: None
        ) as prepared:
            for run, target, role in (
                (other_runtime, feature, "reference"),
                (runtime, groups[1].items[0], "reference"),
                (runtime, feature, "target"),
            ):
                with pytest.raises(InvalidRequestError, match="身份不一致"):
                    plane_coverage(
                        run,
                        target,
                        settings(),
                        role,
                        cancel=lambda: None,
                        prepared=prepared,
                    )
        with pytest.raises(InvalidRequestError, match="失效"):
            reference_coverage(
                runtime, feature, settings(), cancel=lambda: None, prepared=prepared
            )
    finally:
        assert not scope.close()
        assert not other_scope.close()


@pytest.mark.parametrize("stage", [1, 3, 8, 10])
def test_prepare_cancel_returns_all_reservations(stage):
    scope, runtime, _, _, _, groups = two_planes()
    used = runtime.budget.used
    support_snapshot(
        runtime,
        groups[0].items[0].support,
        "reference",
        cancel=lambda: None,
        plane=groups[0].items[0],
    )
    resources = runtime.storage_scope.resource_count
    calls = 0

    def cancel():
        """确定性注入，包括支持快照、读取和原生索引前后。"""
        nonlocal calls
        calls += 1
        if calls == stage:
            raise RuntimeError("cancel")

    try:
        with pytest.raises(RuntimeError, match="cancel"):
            with prepare_plane_support(
                runtime, groups[0].items[0], "reference", cancel=cancel
            ):
                cancel()
        assert runtime.budget.used == used
        assert runtime.storage_scope.resource_count == resources
    finally:
        assert not scope.close()


def test_preparation_and_query_budgets_reject_without_leaks():
    scope, runtime, _, _, _, groups = two_planes()
    used = runtime.budget.used
    try:
        feature = groups[0].items[0]
        original = runtime.policy
        runtime.policy = original.model_copy(update={"max_working_bytes": 2000})
        with pytest.raises(InvalidRequestError, match="预算"):
            with prepare_plane_support(
                runtime, feature, "reference", cancel=lambda: None
            ):
                pytest.fail("must reject before allocation")
        assert runtime.budget.used == used
        runtime.policy = original
        with prepare_plane_support(
            runtime, feature, "reference", cancel=lambda: None
        ) as prepared:
            held = runtime.budget.used
            runtime.policy = original.model_copy(
                update={"max_working_bytes": prepared.held_bytes + 1024}
            )
            with pytest.raises(InvalidRequestError, match="候选超过"):
                reference_coverage(
                    runtime, feature, settings(), cancel=lambda: None, prepared=prepared
                )
            assert runtime.budget.used == held
            runtime.policy = original
        assert runtime.budget.used == used
    finally:
        assert not scope.close()


def test_full_parent_layer_is_not_hidden_by_inlier_support():
    """以独立解析内点构造真实派生支持，父层异面仍必须计入残差。"""
    from hashlib import sha256
    from backend.contracts.workflows.point_cloud import canonical_cloud_json
    from backend.contracts.workflows.point_cloud_runtime import PlaneSupportMethod
    from tests.test_point_cloud_runtime import own

    xy = np.array([(x, y) for x in (-1, 0, 1) for y in (-1, 0, 1)])
    points = np.concatenate(
        [np.column_stack((xy, np.full(len(xy), z))) for z in (0, 0.2)]
    )
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(max_working_bytes=1024**2, max_live_array_bytes=1024**2),
    )
    try:
        p = plane_parameters()
        indices = np.arange(9, dtype="<u4").reshape(-1, 1)
        subset = runtime.register_subset(
            parent=cloud,
            indices=own(runtime, {"indices": indices}),
            cancel=lambda: None,
            method=PlaneSupportMethod(
                method_id="fit-plane-support",
                method_version=1,
                parameters=p,
                parameters_sha256=sha256(
                    canonical_cloud_json(p.model_dump(mode="json"))
                ).hexdigest(),
                indices_sha256=sha256(indices).hexdigest(),
            ),
        )
        feature = fit_plane(runtime, subset, p, cancel=lambda: None).items[0]
        with prepare_plane_support(
            runtime, feature, "reference", cancel=lambda: None
        ) as prepared:
            scan = reference_coverage(
                runtime, feature, settings(), cancel=lambda: None, prepared=prepared
            )
            assert_same(
                reference_coverage(runtime, feature, settings(), cancel=lambda: None),
                scan,
            )
            assert scan.support.coverage.count == 9
            assert scan.support.coverage.max_residual == 0.2
            assert all(i < 9 for i in scan.support.coverage.source_indices)
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


def test_repeated_queries_do_not_read_source_rows_and_scope_close_invalidates(
    monkeypatch,
):
    """身份借用继续执行，但准备后不得再扫描源数组。"""
    from custom_nodes.metrology3d_nodes.shared import prepared_plane_support as module

    scope, runtime, _, _, _, groups = two_planes()
    feature = groups[0].items[0]
    try:
        with prepare_plane_support(
            runtime, feature, "reference", cancel=lambda: None
        ) as prepared:
            monkeypatch.setattr(
                module, "_positions", lambda *args: pytest.fail("source rescanned")
            )
            for x in np.linspace(-0.8, 0.8, 21):
                assert reference_coverage(
                    runtime,
                    feature,
                    settings((x, 0, 0)),
                    cancel=lambda: None,
                    prepared=prepared,
                ).support.coverage.covered
            assert not scope.close()
            assert prepared.closed and prepared.index is None
            with pytest.raises(InvalidRequestError, match="失效"):
                reference_coverage(
                    runtime, feature, settings(), cancel=lambda: None, prepared=prepared
                )
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


@pytest.mark.parametrize("stage", [1, 3, 5, 7])
def test_query_cancel_returns_scratch_budget(stage):
    """查询取消后支持索引仍归 Scope，临时邻域预算归还，可重新查询。"""
    scope, runtime, _, _, _, groups = two_planes()
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == stage:
            raise InterruptedError("cancel-query")

    try:
        feature = groups[0].items[0]
        with prepare_plane_support(
            runtime, feature, "reference", cancel=lambda: None
        ) as prepared:
            used = runtime.budget.used
            with pytest.raises(InterruptedError, match="cancel-query"):
                reference_coverage(
                    runtime, feature, settings(), cancel=cancel, prepared=prepared
                )
            assert runtime.budget.used == used
            assert reference_coverage(
                runtime, feature, settings(), cancel=lambda: None, prepared=prepared
            ).support.coverage.covered
    finally:
        assert not scope.close()


def test_invalid_plane_has_no_index_and_preserves_invalid_evidence():
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=np.array([[0.0, 0, 0], [1, 0, 0], [2, 0, 0]]),
    )
    try:
        feature = fit_plane(
            runtime, cloud, plane_parameters(), cancel=lambda: None
        ).items[0]
        assert not feature.valid
        with prepare_plane_support(
            runtime, feature, "reference", cancel=lambda: None
        ) as prepared:
            assert prepared.index is None
            assert_same(
                reference_coverage(runtime, feature, settings(), cancel=lambda: None),
                reference_coverage(
                    runtime, feature, settings(), cancel=lambda: None, prepared=prepared
                ),
            )
    finally:
        assert not scope.close()


def test_near_zero_distance_is_independent_of_scan_and_candidate_row_counts(
    monkeypatch,
):
    """完整云发现的 GEMM/GEMV 差异回归；保持精确证据比较而非放宽容差。"""
    from custom_nodes.metrology3d_nodes.shared import measurement_support as module

    angle = 0.017
    rotation = np.array(
        [
            [np.cos(angle), 0, np.sin(angle)],
            [0, 1, 0],
            [-np.sin(angle), 0, np.cos(angle)],
        ]
    )
    points = np.array([(x, y, 0.0) for x in (-3, -2, -1) for y in (-1, 0, 1)])
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=points @ rotation.T + np.array([-44.0, -3.0, -16.0]),
        runtime_policy=policy(chunk_rows=65536, max_working_bytes=1024**2),
    )
    try:
        feature = fit_plane(
            runtime,
            cloud,
            plane_parameters(positive_normal=rotation[:, 2]),
            cancel=lambda: None,
        ).items[0]
        with runtime.borrow(feature.support) as view:
            point = view.chunk(0, 1)["positions"][0].astype(float)
        p = settings(point, radius=0.25, direction=feature.geometry.normal)
        expected = reference_coverage(runtime, feature, p, cancel=lambda: None)
        with prepare_plane_support(
            runtime, feature, "reference", cancel=lambda: None
        ) as prepared:
            for rows in (1, 2, 3, 7, 65536):
                monkeypatch.setattr(module, "_rows", lambda *args, **kwargs: rows)
                assert_same(
                    expected,
                    reference_coverage(runtime, feature, p, cancel=lambda: None),
                )
                assert_same(
                    expected,
                    reference_coverage(
                        runtime, feature, p, cancel=lambda: None, prepared=prepared
                    ),
                )
    finally:
        assert not scope.close()


def test_active_query_cannot_be_closed_or_reentered():
    """强制关闭不提前释放本地原生索引；重复调用立即拒绝，不排队。"""
    scope, runtime, _, _, _, groups = two_planes()
    try:
        feature = groups[0].items[0]
        with prepare_plane_support(
            runtime, feature, "reference", cancel=lambda: None
        ) as prepared:
            used = runtime.budget.used
            checked = False

            def cancel():
                """在原生查询前模拟关闭和重入请求。"""
                nonlocal checked
                if checked:
                    return
                checked = True
                with pytest.raises(RuntimeError, match="活跃查询"):
                    prepared.close()
                with pytest.raises(InvalidRequestError, match="活跃查询"):
                    reference_coverage(
                        runtime,
                        feature,
                        settings(),
                        cancel=lambda: None,
                        prepared=prepared,
                    )
                assert runtime.budget.used == used
                assert prepared.index is not None and not prepared.closed

            result = reference_coverage(
                runtime, feature, settings(), cancel=cancel, prepared=prepared
            )
            assert checked and result.support.coverage.covered
        assert prepared.closed
    finally:
        assert not scope.close()
