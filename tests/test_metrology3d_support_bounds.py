"""支持摘要复用必须保持引用校验、独立真值和 Scope 释放。"""

import numpy as np
import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.point_cloud.runtime import CloudView
from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes.metrology3d_nodes.shared.support_bounds import support_bounds
from tests.test_metrology3d_crop import box, parameters
from tests.test_metrology3d_preprocess import make_cloud


def test_bounds_reuses_same_cloud_but_not_subset_or_other_runtime(monkeypatch):
    """缓存只保留标量；不同子集、运行即使同名也不共用摘要。"""
    scope, runtime, cloud = make_cloud(
        unit="mm", coordinates=np.array([[0, 0, 0], [10, 20, 30]], dtype=np.float32)
    )
    calls = []
    original = CloudView.chunk

    def chunk(self, start, stop):
        calls.append((self.reference.cloud_id, start, stop))
        return original(self, start, stop)

    monkeypatch.setattr(CloudView, "chunk", chunk)
    first = support_bounds(runtime, cloud, cancel=lambda: None)
    assert first.min == (0, 0, 0) and first.max == (10, 20, 30)
    assert len(calls) == 1
    assert support_bounds(runtime, cloud, cancel=lambda: None) is first
    assert len(calls) == 1
    cropped, _ = crop_roi(runtime, cloud, parameters(box()), cancel=lambda: None)
    bounded = support_bounds(runtime, cropped, cancel=lambda: None)
    assert bounded.min == bounded.max == (0, 0, 0)
    other_scope, other_runtime, other = make_cloud(unit="mm")
    try:
        assert support_bounds(other_runtime, other, cancel=lambda: None).min == (
            1,
            2,
            3,
        )
        for change in ({"point_count": 1}, {"revision": 2}, {"run_id": "other"}):
            with pytest.raises(InvalidRequestError):
                support_bounds(
                    runtime, cloud.model_copy(update=change), cancel=lambda: None
                )
    finally:
        assert not other_scope.close() and other_runtime.budget.used == 0
        assert not scope.close() and runtime.budget.used == 0
    assert runtime.storage_scope.resource_count == 0
    with pytest.raises(RuntimeError):
        support_bounds(runtime, cloud, cancel=lambda: None)


@pytest.mark.parametrize("cancel_at", [1, 2, 3])
def test_cancel_does_not_publish_partial_summary(cancel_at):
    """每个检查点中断后可重新计算，不留下摘要或借用。"""
    scope, runtime, cloud = make_cloud(unit="mm")
    before = runtime.storage_scope.resource_count
    count = 0

    def cancel():
        nonlocal count
        count += 1
        if count == cancel_at:
            raise InterruptedError("cancelled")

    try:
        with pytest.raises(InterruptedError):
            support_bounds(runtime, cloud, cancel=cancel)
        assert runtime.storage_scope.resource_count == before
        assert support_bounds(runtime, cloud, cancel=lambda: None).max == (4, 5, 6)
    finally:
        assert not scope.close() and runtime.budget.used == 0
