"""R5 A：并集逐行真值、共享依赖、精度与所有权反例。"""

from copy import deepcopy

import numpy as np
import pytest
from pydantic import ValidationError

from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes.metrology3d_nodes.shared.roi_mask import roi_mask
from tests.point_cloud_support import policy
from tests.test_metrology3d_crop import box, parameters
from tests.test_metrology3d_preprocess import make_cloud


def union(key, *members):
    """显式测试并集，不提供生产空间默认。"""
    return dict(
        kind="union",
        roi_id=key,
        frame_id="fixture",
        length_unit="mm",
        geometry=dict(roi_ids=list(members)),
    )


def boxes():
    """重叠和分离窗口；闭边界以独立坐标判断。"""
    result = []
    for key, center in (("left", 0), ("overlap", 1), ("right", 5)):
        value = box()
        value.update(roi_id=key)
        value["geometry"].update(center=[center, 0, 0], size=[2, 2, 2])
        result.append(value)
    return result


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("reverse", [False, True])
def test_union_exact_rows_fields_and_subset_lineage(dtype, reverse):
    points = np.array(
        [[x, y, 0] for x in [-2, -1, 0, 1, 2, 3, 4, 5, 6, 7] for y in [-1, 0, 1, 2]]
        + [[1, 0, 0], [1, 0, 0]],
        dtype=dtype,
    )
    members = boxes()
    ids = [r["roi_id"] for r in members]
    config = parameters(union("all", *(ids[::-1] if reverse else ids)), *members)
    expected = [
        i
        for i, (x, y, _) in enumerate(points)
        if -1 <= y <= 1 and (-1 <= x <= 2 or 4 <= x <= 6)
    ]
    labels = np.arange(len(points), dtype=np.uint64) + 2**63
    scope, runtime, source = make_cloud(
        unit="mm",
        coordinates=points,
        attributes=(("label", labels, "1"),),
        runtime_policy=policy(max_working_bytes=32768),
    )
    try:
        result, summary = crop_roi(runtime, source, config, cancel=lambda: None)
        assert summary["kept_count"] == len(expected)
        with runtime.borrow(result) as view:
            for start in range(0, len(expected), 2):
                stop = min(start + 2, len(expected))
                selected = expected[start:stop]
                np.testing.assert_array_equal(
                    view.source_indices(start, stop), selected
                )
                np.testing.assert_array_equal(
                    view.chunk(start, stop)["positions"], points[selected]
                )
                np.testing.assert_array_equal(
                    view.chunk(start, stop)["label"][:, 0], labels[selected]
                )
        second, _ = crop_roi(runtime, result, config, cancel=lambda: None)
        with runtime.borrow(second) as view:
            for start in range(0, len(expected), 2):
                stop = min(start + 2, len(expected))
                np.testing.assert_array_equal(
                    view.source_indices(start, stop), expected[start:stop]
                )
        assert runtime.source_point_count(second) == len(points)
        assert result.fields == source.fields and result.topology is None
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_mixed_section_union_and_boundary_consumer():
    members = boxes()
    section = dict(
        kind="section-band",
        roi_id="slice",
        frame_id="fixture",
        length_unit="mm",
        geometry=dict(
            origin=[0, 0, 0], normal=[0, 0, 1], thickness=1, bounds_roi_id="parts"
        ),
    )
    config = parameters(
        union("all", "slice", "right"),
        section,
        union("parts", "left", "overlap"),
        *members,
    )
    points = np.array(
        [[x, 0, z] for x in [-1, 0, 1, 2, 3, 4, 5, 6] for z in [-1, -0.5, 0, 0.5, 1]],
        dtype=np.float32,
    )
    expected = [
        (-1 <= x <= 2 and abs(z) <= 0.5) or (4 <= x <= 6 and abs(z) <= 1)
        for x, _, z in points
    ]
    actual = roi_mask(points, config, max_working_bytes=8192, cancel=lambda: None)
    np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize(
    "case",
    ["empty", "duplicate", "missing", "self", "mixed-cycle", "unused-cycle", "space"],
)
def test_union_rejects_invalid_graphs(case):
    root = union("all", "left", "right")
    members = boxes()
    if case == "empty":
        root["geometry"]["roi_ids"] = []
    elif case == "duplicate":
        root["geometry"]["roi_ids"] = ["left", "left"]
    elif case == "missing":
        root["geometry"]["roi_ids"].append("missing")
    elif case == "self":
        root["geometry"]["roi_ids"].append("all")
    elif case in {"mixed-cycle", "unused-cycle"}:
        members.append(
            dict(
                kind="section-band",
                roi_id="slice",
                frame_id="fixture",
                length_unit="mm",
                geometry=dict(
                    origin=[0, 0, 0],
                    normal=[0, 0, 1],
                    thickness=1,
                    bounds_roi_id="cycle",
                ),
            )
        )
        members.append(union("cycle", "slice"))
        if case == "mixed-cycle":
            root["geometry"]["roi_ids"].append("cycle")
    else:
        members[-1]["frame_id"] = "other"
    with pytest.raises(ValidationError):
        parameters(root, *members)


def test_deep_shared_dag_is_iterative_and_evaluates_once_per_node():
    members = [box()]
    last = "roi"
    for i in range(1200):
        key = f"u{i}"
        members.append(union(key, last, "roi") if last != "roi" else union(key, last))
        last = key
    config = parameters(members[-1], *members[:-1])
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1

    np.testing.assert_array_equal(
        roi_mask(
            np.array([[0, 0, 0], [99, 0, 0]], dtype=np.float64),
            config,
            max_working_bytes=4 * 1024**2,
            cancel=cancel,
        ),
        [True, False],
    )
    assert calls < 20 * len(members)


def test_working_budget_rejection_and_empty_union_result():
    config = parameters(union("all", "left", "right"), *boxes())
    scope, runtime, source = make_cloud(
        unit="mm", runtime_policy=policy(max_working_bytes=256)
    )
    before = runtime.budget.used
    with pytest.raises(InvalidRequestError, match="预算"):
        crop_roi(runtime, source, config, cancel=lambda: None)
    assert runtime.budget.used == before
    assert not scope.close() and runtime.budget.used == 0
    scope, runtime, source = make_cloud(
        unit="mm", coordinates=np.array([[99, 0, 0]], dtype=np.float32)
    )
    try:
        result, _ = crop_roi(runtime, source, config, cancel=lambda: None)
        assert result.point_count == 0 and runtime.source_point_count(result) == 1
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_cancel_at_every_checkpoint_reclaims_indices():
    config = parameters(union("all", "left", "right"), *boxes())
    points = np.array([[0, 0, 0], [5, 0, 0], [1, 0, 0]], dtype=np.float64)
    scope, runtime, source = make_cloud(unit="mm", coordinates=points)
    count = 0

    def tally():
        nonlocal count
        count += 1

    crop_roi(runtime, source, config, cancel=tally)
    assert not scope.close()
    for checkpoint in range(1, count + 1):
        scope, runtime, source = make_cloud(unit="mm", coordinates=deepcopy(points))
        before, calls = runtime.budget.used, 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == checkpoint:
                raise RuntimeError("cancelled")

        try:
            with pytest.raises(RuntimeError, match="cancelled"):
                crop_roi(runtime, source, config, cancel=cancel)
            assert runtime.budget.used == before
        finally:
            assert not scope.close() and runtime.budget.used == 0


def test_index_admission_rejects_without_partial_subset():
    """活跃数组预算耗尽时拒绝新索引，已有父云仍可借用。"""
    scope, runtime, source = make_cloud(unit="mm")
    held = runtime.budget.reserve(
        runtime.policy.max_live_array_bytes - runtime.budget.used
    )
    before = runtime.budget.used
    try:
        with pytest.raises(InvalidRequestError, match="预算"):
            crop_roi(
                runtime,
                source,
                parameters(union("all", "roi"), box()),
                cancel=lambda: None,
            )
        assert runtime.budget.used == before
        with runtime.borrow(source) as view:
            assert len(view.chunk(0, 1)["positions"]) == 1
    finally:
        held.close()
        assert not scope.close() and runtime.budget.used == 0
