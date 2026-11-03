"""Run 内分块摘要的逐行等价、完整验证、预算和生命周期。"""

import numpy as np
import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.point_cloud.runtime import CloudView
from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
from tests.point_cloud_support import policy
from tests.test_metrology3d_crop import box, parameters
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_metrology3d_roi_union import union


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_reused_blocks_preserve_rows_fields_and_closed_union(dtype, monkeypatch):
    """第一次单遍建立摘要，第二次只读可能命中块，闭端点仍逐行验证。"""
    points = np.array([[x, 0, 0] for x in range(40)], dtype=dtype)
    scope, runtime, source = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(chunk_rows=4),
        attributes=(("label", np.arange(40, dtype=np.uint64) + 2**63, "1"),),
    )
    reads = []
    original = CloudView.chunk

    def read(view, start, stop):
        if view.reference.cloud_id == source.cloud_id:
            reads.append((start, stop))
        return original(view, start, stop)

    monkeypatch.setattr(CloudView, "chunk", read)
    left, right = box(center=[1, 0, 0]), box(center=[37, 0, 0])
    left["roi_id"], right["roi_id"] = "left", "right"
    config = parameters(union("parts", "left", "right"), left, right)
    try:
        first, _ = crop_roi(runtime, source, config, cancel=lambda: None)
        assert reads == [(i, i + 4) for i in range(0, 40, 4)]
        reads.clear()
        second, _ = crop_roi(runtime, source, config, cancel=lambda: None)
        assert reads == [(0, 4), (36, 40)]
        for result in (first, second):
            with runtime.borrow(result) as view:
                actual = np.concatenate(
                    [view.source_indices(i, min(i + 4, 6)) for i in (0, 4)]
                )
                np.testing.assert_array_equal(actual, [0, 1, 2, 36, 37, 38])
                np.testing.assert_array_equal(
                    view.chunk(0, 4)["label"][:, 0],
                    np.array([0, 1, 2, 36], dtype=np.uint64) + 2**63,
                )
        with pytest.raises(InvalidRequestError):
            crop_roi(
                runtime,
                source.model_copy(update={"point_count": 39}),
                config,
                cancel=lambda: None,
            )
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_invalid_points_outside_roi_are_not_skipped():
    """首次完整扫描不能以不相交为理由漏检坏点。"""
    points = np.array([[0, 0, 0], [100, 0, 0], [200, 0, np.nan]], dtype=np.float64)
    scope, runtime, source = make_cloud(unit="mm", coordinates=points)
    before = runtime.budget.used
    try:
        with pytest.raises(InvalidRequestError, match="无效位置"):
            crop_roi(runtime, source, parameters(box()), cancel=lambda: None)
        assert runtime.budget.used == before
    finally:
        assert not scope.close() and runtime.budget.used == 0


@pytest.mark.parametrize("stage", [5, 15, 30, 35, 40])
def test_cancel_never_retains_partial_summary(stage):
    """摘要生成、掩码或索引阶段取消均归还新增容量。"""
    points = np.arange(60, dtype=np.float64).reshape(20, 3)
    scope, runtime, source = make_cloud(unit="mm", coordinates=points)
    before, calls = runtime.budget.used, 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == stage:
            raise RuntimeError("cancelled")

    try:
        with pytest.raises(RuntimeError, match="cancelled"):
            crop_roi(
                runtime, source, parameters(box(size=[100, 100, 100])), cancel=cancel
            )
        assert runtime.budget.used == before
        result, _ = crop_roi(
            runtime, source, parameters(box(size=[100, 100, 100])), cancel=lambda: None
        )
        assert result.point_count == 17
    finally:
        assert not scope.close() and runtime.budget.used == 0


@pytest.mark.parametrize("center", [0.1, 1e9, -1e9])
def test_block_rejection_never_drops_nextafter_boundary(center):
    """远原点和一个 ULP 的闭边界，与原始逐行 mask 独立比对。"""
    from custom_nodes.metrology3d_nodes.shared.roi_mask import RoiMaskPlan

    values = np.array([center - 1, center + 1, center])
    points = np.column_stack(
        [np.r_[values, np.nextafter(values, -np.inf), np.nextafter(values, np.inf)]] * 3
    )
    plan = RoiMaskPlan(
        parameters(box(center=[center] * 3, size=[2] * 3)),
        max_working_bytes=65536,
        cancel=lambda: None,
    )
    for start in range(len(points)):
        part = points[start : start + 1]
        expected = bool((np.abs(part - center) <= 1).all(axis=1).any())
        assert (
            plan.may_intersect(part.min(axis=0), part.max(axis=0), cancel=lambda: None)
            == expected
        )
