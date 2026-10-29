"""片段组的独立行号真值、来源/保存与有限支持回归。"""

from copy import deepcopy
from dataclasses import replace
from math import pi

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.boundary3d import BoundarySelection
from backend.contracts.workflows.boundary3d_observations import BoundaryEvidence
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes.metrology3d_nodes.shared.boundary_assets import restore_boundary
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import (
    extract_boundary,
    select_boundary,
)
from custom_nodes.metrology3d_nodes.shared.boundary_targets import select_targets
from custom_nodes.metrology3d_nodes.shared.boundary_topology import OrderedSegment
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from custom_nodes.metrology3d_nodes.shared.fit_boundary import fit_boundary
from tests.integration.metrology3d.representative_recipe import boxes
from tests.integration.metrology3d.test_boundary_extraction import (
    extract_parameters,
    region,
)
from tests.integration.metrology3d.test_boundary_runtime import runtime_policy
from tests.point_cloud_support import create_resource_service
from tests.test_metrology3d_boundary_contracts import circle_parameters
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_point_cloud_assets import POLICY
from tests.integration.metrology3d.test_circle_weighting import robust_parameters


def group_parameters(**changes):
    """明确测试选择和两层质量；不是生产默认值。"""
    target = dict(
        group_id="arc-set",
        role="open",
        region=region(),
        arc=dict(
            center=[0, 0],
            radius_range=[3.9, 4.1],
            start_angle=0,
            sweep=pi,
            max_overlap_angle=0,
        ),
        fragment_quality_policy=dict(
            policy_id="fragment",
            policy_version=1,
            rules=[
                dict(item_id="support_count", unit="1", lower=2),
                dict(item_id="length", unit="mm", lower=0.01),
            ],
        ),
    )
    target.update(changes)
    return extract_parameters(targets=[target])


def arc_points(angles, radius=4):
    """独立解析圆的三维采样，不调用拟合内核。"""
    return np.column_stack(
        (radius * np.cos(angles), radius * np.sin(angles), np.zeros(len(angles)))
    )


def test_group_preserves_disjoint_original_rows_and_rejects_competing_arcs():
    """不跨缺口连线；输入候选顺序不影响组与段身份。"""
    points = arc_points(np.r_[np.linspace(0.2, 1, 12), np.linspace(1.8, 2.8, 14)])
    candidates = [
        OrderedSegment(np.arange(12), False),
        OrderedSegment(np.arange(12, 26), False),
    ]
    p = group_parameters()
    a = select_targets(
        points, candidates, p, max_working_bytes=100_000, cancel=lambda: None
    )
    b = select_targets(
        points, candidates[::-1], p, max_working_bytes=100_000, cancel=lambda: None
    )
    assert a[:2] == (None, None) and a[3] == b[3]
    np.testing.assert_array_equal(a[2], b[2])
    assert set(a[2]) == set(range(26)) and [s.count for s in a[3].segments] == [12, 14]
    assert all(s.group_id == "arc-set" and not s.closed for s in a[3].segments)
    # 两条不同半径曲线占用相同角区，不能隐式混为一个圆。
    competing = np.vstack((points, arc_points(np.linspace(0.3, 0.9, 8), 4.05)))
    c = select_targets(
        competing,
        candidates + [OrderedSegment(np.arange(26, 34), False)],
        p,
        max_working_bytes=100_000,
        cancel=lambda: None,
    )
    assert c[:2] == ("target_ambiguous", "arc-set") and c[2] is None


def test_group_wrapping_empty_singleton_cancel_and_selection_validation():
    """跨零角区、失效引用与取消均不能返回部分成功支持。"""
    p = group_parameters(
        arc=dict(
            center=[0, 0],
            radius_range=[3.9, 4.1],
            start_angle=5.5,
            sweep=1.5,
            max_overlap_angle=0,
        )
    )
    points = arc_points(np.linspace(5.6, 6.8, 20))
    candidates = [OrderedSegment(np.arange(20), False)]
    result = select_targets(
        points, candidates, p, max_working_bytes=100_000, cancel=lambda: None
    )
    assert result[0] is None and result[3].point_count == 20
    selection = BoundarySelection(feature_id="boundary", group_ids=["arc-set"])
    assert selection.resolve(result[3]) == tuple(
        s.segment_id for s in result[3].segments
    )
    with pytest.raises(ValueError, match="不存在"):
        BoundarySelection(feature_id="boundary", group_ids=["missing"]).resolve(
            result[3]
        )
    with pytest.raises(ValidationError):
        BoundarySelection(
            feature_id="boundary", group_ids=["arc-set"], segment_ids=["x"]
        )
    empty = select_targets(
        arc_points(np.linspace(2, 3, 20)),
        candidates,
        p,
        max_working_bytes=100_000,
        cancel=lambda: None,
    )
    assert empty[0] == "target_not_found"
    single = select_targets(
        points[:1],
        [OrderedSegment(np.array([0]), False)],
        p,
        max_working_bytes=100_000,
        cancel=lambda: None,
    )
    assert single[0] == "insufficient_support"

    def cancelled():
        """取消是执行失败，不伪装为几何缺测。"""
        raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        select_targets(
            points, candidates, p, max_working_bytes=100_000, cancel=cancelled
        )


@pytest.mark.parametrize("robust", [False, True])
def test_group_real_runtime_save_restore_fit_and_release(tmp_path, robust):
    """圆盘真实投影经并集裁成两弧，完整原始属性和组质量可跨运行恢复。"""
    points = np.vstack(
        ([[0.0, 0.0, 0.0]], arc_points(np.linspace(0, 2 * pi, 96, endpoint=False)))
    )
    points = points[np.random.default_rng(17).permutation(len(points))]
    serial = np.arange(len(points), dtype="u8") + np.uint64(2**63)
    scope, runtime, root = make_cloud(
        unit="mm",
        coordinates=points,
        attributes=[("serial", serial, "1")],
        runtime_policy=runtime_policy(),
    )
    service = create_resource_service(tmp_path)
    region_data = boxes(
        "two-arcs", [[0.5, 5, 0.5, 5, -1, 1], [-5, -0.5, 0.5, 5, -1, 1]]
    )
    data = group_parameters(region=region_data).model_dump()
    data["surface"] = dict(
        alpha_radius=5, max_edge_length=9, max_normal_step=1, min_projected_area=1e-12
    )
    data["quality_policy"]["rules"][0]["lower"] = 30
    p = type(group_parameters()).model_validate(data)
    asset_policy = replace(POLICY, chunk_bytes=128)
    try:
        feature = extract_boundary(runtime, root, p, cancel=lambda: None)
        boundary = feature.items[0]
        assert (
            boundary.valid
            and len(boundary.geometry.segments) == 2
            and len(boundary.groups) == 1
        )
        assert all(s.count < 30 for s in boundary.geometry.segments)
        with runtime.borrow(boundary.support) as view:
            blocks = [
                (
                    start,
                    min(
                        start + runtime.policy.chunk_rows, boundary.support.point_count
                    ),
                )
                for start in range(
                    0, boundary.support.point_count, runtime.policy.chunk_rows
                )
            ]
            rows = np.concatenate(
                [view.source_indices(start, stop) for start, stop in blocks]
            )
            expected = np.flatnonzero(
                (abs(points[:, 0]) >= 0.5)
                & (points[:, 1] >= 0.5)
                & (np.linalg.norm(points[:, :2], axis=1) >= 3.9)
            )
            assert set(rows) == set(expected)
            np.testing.assert_array_equal(
                np.concatenate(
                    [view.chunk(start, stop)["serial"][:, 0] for start, stop in blocks]
                ),
                serial[rows],
            )
        selection = BoundarySelection(feature_id="boundary", group_ids=["arc-set"])
        fit_parameters = (
            robust_parameters(selection=selection)
            if robust
            else circle_parameters(selection=selection)
        )
        assert (
            select_boundary(runtime, boundary.support, selection, cancel=lambda: None)
            == boundary.support
        )
        circle = fit_boundary(
            runtime, feature, fit_parameters, cancel=lambda: None
        ).items[0]
        assert circle.valid and circle.geometry.radius == pytest.approx(4, abs=1e-10)
        tampered = boundary.model_dump(exclude={"support"})
        tampered["geometry"]["segments"][0]["group_id"] = "wrong"
        with pytest.raises(ValidationError):
            BoundaryEvidence.model_validate(tampered)
        asset = save_cloud(
            runtime,
            boundary.support,
            features=feature,
            service=service,
            project_id="test",
            mode="derived",
            name="groups",
            write_identity="e" * 64,
            policy=asset_policy,
            cancel=lambda: None,
        )
        evidence = service.read(asset, project_id="test").content.point_cloud.boundary
        bad = deepcopy(data)
        bad["targets"][0]["fragment_quality_policy"]["rules"][0]["lower"] = 30
        failure = extract_boundary(
            runtime, root, type(p).model_validate(bad), cancel=lambda: None
        ).items[0]
        assert not failure.valid and failure.failed_segment_id == "arc-set"
        with pytest.raises(InvalidRequestError, match="预算"):
            from custom_nodes.metrology3d_nodes.shared.extract_boundary import (
                extract_boundary_array,
            )

            extract_boundary_array(points, p, max_working_bytes=10, cancel=lambda: None)
    finally:
        assert not scope.close() and runtime.budget.used == 0
    restored_scope = ResourceScope(kind="test")
    restored_runtime = get_cloud_runtime(
        restored_scope, run_id="restored", policy=runtime_policy()
    )
    try:
        cloud = read_asset(
            restored_runtime,
            asset,
            service=service,
            project_id="test",
            policy=asset_policy,
            cancel=lambda: None,
        )
        recovered = restore_boundary(cloud, evidence)
        assert recovered.items[0].groups[0].group_id == boundary.groups[0].group_id
        assert (
            recovered.items[0].groups[0].quality.metrics.observation_id
            == cloud.observation_id
        )
        assert (
            recovered.items[0].groups[0].quality.metrics.items
            == boundary.groups[0].quality.metrics.items
        )
        fitted = fit_boundary(
            restored_runtime, recovered, fit_parameters, cancel=lambda: None
        ).items[0]
        assert fitted.valid and fitted.geometry.radius == pytest.approx(4, abs=1e-10)
        assert fitted.solver == circle.solver and fitted.intervals == circle.intervals
        from backend.contracts.workflows.dimension3d_evidence import CircleSnapshot

        snapshot = CircleSnapshot.model_validate(fitted.model_dump(exclude={"support"}))
        assert (
            CircleSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot
        )
        if robust:
            changed = snapshot.model_dump()
            changed["solver"]["weighting"]["sector_counts"] = list(
                reversed(changed["solver"]["weighting"]["sector_counts"])
            )
            changed["solver"]["weighting"]["sector_counts"].append(0)
            with pytest.raises(ValidationError):
                CircleSnapshot.model_validate(changed)
    finally:
        assert not restored_scope.close() and restored_runtime.budget.used == 0
