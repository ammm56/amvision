"""B13 真实 Scope 中的点身份、精度、取消与释放。"""

import numpy as np
import pytest

from backend.contracts.workflows.relation3d_parameters import (
    CircleCenterRelationPoint,
    CoordinateRelationPoint,
    SourceRelationPoint,
)
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.relation_points import resolve_relation_point
from tests.point_cloud_support import policy
from tests.test_metrology3d_dimension_runtime import analytic_circle, ordered
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_metrology3d_relations import parameters


def source(index):
    """行号来自原始采集，不是逻辑数组下标。"""
    return SourceRelationPoint(kind="source-point", source_index=index)


def resolve(runtime, cloud, selected, *, groups=(), cancel=lambda: None):
    """使用真实运行时，不替代借用或来源读取。"""
    return resolve_relation_point(
        runtime, cloud, groups, parameters(), selected, cancel=cancel
    )


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_original_row_survives_reordered_subset_and_preserves_precision(dtype):
    coordinates = np.array([[1.125, 2, 3], [4, 5, 6], [7, 8.125, 9]], dtype=dtype)
    scope, runtime, root = make_cloud(unit="mm", coordinates=coordinates)
    try:
        subset = ordered(
            runtime,
            root,
            [2, 0],
            [
                dict(
                    segment_id="edge",
                    start=0,
                    count=2,
                    closed=False,
                    role="open",
                    orientation="open",
                )
            ],
        )
        before = runtime.budget.used
        result = resolve(runtime, subset, source(0))
        assert result.source_index == 0 and result.logical_index == 1
        assert result.point == (1.125, 2, 3) and result.origin == "measured"
        assert result.reason is None
        missing = resolve(runtime, subset, source(1))
        assert missing.point is None and missing.reason == "source_point_not_in_support"
        assert runtime.source_point_count(subset) == 3
        assert runtime.budget.used == before
        with pytest.raises(InvalidRequestError, match="超出原始点数"):
            resolve(runtime, subset, source(3))
    finally:
        assert scope.close() == () and runtime.budget.used == 0


@pytest.mark.parametrize("invalid", ["nan", "validity"])
def test_invalid_source_point_does_not_invalidate_other_selected_row(invalid):
    coordinates = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)
    if invalid == "nan":
        coordinates[1, 0] = np.nan
    attributes = (
        (("validity", np.array([1, 0], dtype=np.uint8), "1"),)
        if invalid == "validity"
        else ()
    )
    scope, runtime, root = make_cloud(
        unit="mm", coordinates=coordinates, attributes=attributes
    )
    try:
        assert resolve(runtime, root, source(0)).point == (1, 2, 3)
        result = resolve(runtime, root, source(1))
        assert result.point is None and result.reason == "invalid_source_point"
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_specified_point_is_not_given_a_source_identity():
    scope, runtime, root = make_cloud(unit="mm")
    try:
        result = resolve(
            runtime,
            root,
            CoordinateRelationPoint(kind="coordinate", position=(9, 8, 7)),
        )
        assert result.point == (9, 8, 7) and result.origin == "specified"
        assert result.source_index is None and result.logical_index is None
        with pytest.raises(InvalidRequestError, match="不一致"):
            resolve(runtime, root.model_copy(update={"run_id": "other"}), source(0))
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_circle_center_uses_existing_model_and_rejects_bad_identity():
    angle = np.arange(8) * np.pi / 4
    xyz = np.column_stack((4 * np.cos(angle), 4 * np.sin(angle), np.zeros(8)))
    scope, runtime, root = make_cloud(unit="mm", coordinates=xyz)
    try:
        features = analytic_circle(runtime, root)
        point = CircleCenterRelationPoint(kind="circle-center", feature_id="circle")
        result = resolve(runtime, root, point, groups=[features])
        assert result.point == (0, 0, 0) and result.origin == "estimated"
        assert result.feature_id == "circle" and result.source_index is None
        with pytest.raises(InvalidRequestError, match="不一致"):
            resolve(
                runtime,
                root,
                point,
                groups=[features.model_copy(update={"observation_id": "other"})],
            )
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_cancellation_during_scan_releases_borrows():
    scope, runtime, root = make_cloud(
        unit="mm", coordinates=np.ones((8, 3), dtype=np.float32)
    )
    try:
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise InterruptedError("cancelled")

        before = runtime.budget.used
        with pytest.raises(InterruptedError, match="cancelled"):
            resolve(runtime, root, source(7), cancel=cancel)
        assert runtime.budget.used == before
        assert resolve(runtime, root, source(7)).point == (1, 1, 1)
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_duplicate_original_row_across_chunks_is_not_silently_selected():
    scope, runtime, root = make_cloud(unit="mm")
    try:
        subset = ordered(
            runtime,
            root,
            [0, 1, 0],
            [
                dict(
                    segment_id="edge",
                    start=0,
                    count=3,
                    closed=False,
                    role="open",
                    orientation="open",
                )
            ],
        )
        with pytest.raises(InvalidRequestError, match="不唯一"):
            resolve(runtime, subset, source(0))
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_tiny_budget_rejects_before_reading_positions():
    scope, runtime, root = make_cloud(
        unit="mm", runtime_policy=policy(max_working_bytes=256)
    )
    try:
        with pytest.raises(InvalidRequestError, match="一行"):
            resolve(runtime, root, source(0))
    finally:
        assert scope.close() == () and runtime.budget.used == 0
