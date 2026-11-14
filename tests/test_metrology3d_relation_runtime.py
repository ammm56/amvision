"""B13 与既有特征、质量及有限支持链路的组合回归。"""

import numpy as np
import pytest

from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane
from custom_nodes.metrology3d_nodes.shared.relation_runtime import measure_relation
from tests.point_cloud_support import policy
from tests.test_metrology3d_dimension_runtime import analytic_edges
from tests.test_metrology3d_plane import plane_parameters
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_metrology3d_relations import parameters


def run(runtime, cloud, groups, p, *, cancel=lambda: None):
    """直接调用真实运行时入口，不替换源身份与质量核对。"""
    return measure_relation(runtime, cloud, groups, p, cancel=cancel)


def test_line_relation_reuses_existing_models_without_refitting():
    scope, runtime, root = make_cloud(
        unit="mm",
        coordinates=np.array(
            [
                [0, -2, 0],
                [0, 2, 0],
                [4, -2, 0],
                [4, 2, 0],
            ],
            dtype=float,
        ),
    )
    try:
        group = analytic_edges(runtime, root)
        p = parameters("line-line", support_mode="finite")
        before = runtime.budget.used
        result = run(runtime, root, [group], p)
        assert result.value == 4 and result.quality.usable
        assert result.geometry.contacts_unique is False
        assert result.reference.feature is group.items[0]
        assert runtime.budget.used == before
        raw = p.model_dump(mode="json")
        raw["quality_policy"]["rules"].append(
            dict(item_id="contacts_unique", unit="1", lower=1)
        )
        strict = type(p).model_validate(raw)
        failed = run(runtime, root, [group], strict)
        assert failed.value is None and failed.reason == "insufficient_quality"
        assert failed.geometry.value == 4 and failed.stage == "quality"
        with pytest.raises(InvalidRequestError, match="重复"):
            run(runtime, root, [group, group], p)
        with pytest.raises(InvalidRequestError, match="内容已改变"):
            run(
                runtime, root.model_copy(update={"observation_id": "other"}), [group], p
            )
    finally:
        assert scope.close() == () and runtime.budget.used == 0


@pytest.mark.parametrize(
    "x,edge,expected",
    [(0, 2, None), (3, 2, "outside_support"), (0, 0.1, "insufficient_support_quality")],
)
def test_plane_coverage_uses_real_support_and_original_quality(x, edge, expected):
    xy = np.array([(x, y) for x in (-1, 0, 1) for y in (-1, 0, 1)], dtype=float)
    scope, runtime, root = make_cloud(
        unit="mm",
        coordinates=np.column_stack((xy, np.full(9, 2.0))),
        runtime_policy=policy(max_working_bytes=1024 * 1024),
    )
    try:
        group = fit_plane(
            runtime, root, plane_parameters(feature_id="a"), cancel=lambda: None
        )
        p = parameters(
            "point-plane",
            reference=dict(kind="coordinate", position=(x, 0, 5)),
            support_mode="finite",
            coverage=dict(
                support_radius=2,
                min_support_count=3,
                max_triangle_edge=edge,
                max_plane_residual=0.01,
            ),
        )
        result = run(runtime, root, [group], p)
        assert result.reason == expected
        assert result.value == (3 if expected is None else None)
        assert result.plane_support is not None
        assert result.coverage_quality.usable == (expected is None)
        if expected is None:
            assert result.geometry.target_point == (0, 0, 2)
            assert all(i < 9 for i in result.plane_support.coverage.source_indices)
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_invalid_upstream_is_not_replaced_by_model_mode():
    scope, runtime, root = make_cloud(
        unit="mm", coordinates=np.array([[0, 0, 0], [1, 0, 0]], dtype=float)
    )
    try:
        group = fit_plane(
            runtime, root, plane_parameters(feature_id="a"), cancel=lambda: None
        )
        assert not group.items[0].valid
        result = run(runtime, root, [group], parameters("point-plane"))
        assert result.value is None and result.reason == group.items[0].reason
        assert result.failed_role == "target" and result.stage == "source"
        assert not result.quality.usable
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_point_relation_preserves_both_source_roles():
    scope, runtime, root = make_cloud(unit="mm")
    try:
        p = parameters(
            reference=dict(kind="source-point", source_index=0),
            target=dict(kind="coordinate", position=(2, 2, 3)),
        )
        result = run(runtime, root, [], p)
        assert result.value == 1
        assert result.reference.point.source_index == 0
        assert result.target.point.origin == "specified"
    finally:
        assert scope.close() == () and runtime.budget.used == 0
