"""连续逻辑视图不复制字段，非连续/有序顶点仍保持实际选择顺序。"""

import numpy as np
import pytest

from backend.service.application.workflows.point_cloud.runtime import (
    CloudView,
    get_cloud_runtime,
)
from backend.service.application.runtime.resource_scope import ResourceScope
from tests.point_cloud_support import policy
from tests.test_point_cloud_runtime import root_cloud, own, method


@pytest.mark.parametrize(
    "indices,shared",
    [
        ([1, 2, 3, 4], True),
        ([2], True),
        ([], False),
        ([1, 3, 2, 4], False),
        ([1, 1, 3], False),
        ([1, 4], False),
    ],
)
def test_exact_contiguous_detection_including_ordered_rows(indices, shared):
    """不能仅凭首尾推断连续，覆盖重复、空集、逆序和原始行号。"""
    scope = ResourceScope(kind="test")
    runtime = get_cloud_runtime(scope, run_id="run", policy=policy(chunk_rows=32))
    root, owner = root_cloud(runtime)
    selected = np.asarray(indices, dtype=np.uint32).reshape(-1, 1)
    try:
        with owner.borrow() as arrays:
            view = CloudView(
                reference=root.model_copy(update={"point_count": len(indices)}),
                arrays=arrays,
                selectors=(selected,),
                origin_selectors=(selected,),
                lineage=None,
                policy=runtime.policy,
            )
            result = view.chunk(0, len(indices))["positions"]
            np.testing.assert_array_equal(result, arrays["positions"][indices])
            np.testing.assert_array_equal(view.source_indices(0, len(indices)), indices)
            assert np.shares_memory(result, arrays["positions"]) == shared
            assert not result.flags.writeable
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_nested_real_subset_keeps_owner_and_close_boundary():
    """通过真实注册构建两层连续子集，结束借用后禁止继续访问。"""
    scope = ResourceScope(kind="test")
    runtime = get_cloud_runtime(scope, run_id="run", policy=policy(chunk_rows=32))
    root, owner = root_cloud(runtime)
    first = runtime.register_subset(
        parent=root,
        method=method(),
        indices=own(runtime, {"indices": np.array([[1], [2], [3], [4]], dtype="<u4")}),
        cancel=lambda: None,
    )
    second = runtime.register_subset(
        parent=first,
        method=method(),
        indices=own(runtime, {"indices": np.array([[1], [2]], dtype="<u4")}),
        cancel=lambda: None,
    )
    try:
        with runtime.borrow(second) as view, owner.borrow() as arrays:
            values = view.chunk(0, 2)["positions"]
            assert np.shares_memory(values, arrays["positions"])
            np.testing.assert_array_equal(values, arrays["positions"][2:4])
            np.testing.assert_array_equal(view.source_indices(0, 2), [2, 3])
            gathered, identity = view.gather(np.array([1, 0]))
            np.testing.assert_array_equal(gathered["positions"], arrays["positions"][[3, 2]])
            np.testing.assert_array_equal(identity, [3, 2])
            assert not gathered["positions"].flags.writeable and not identity.flags.writeable
        with pytest.raises(RuntimeError, match="借用已结束"):
            view.chunk(0, 1)
        with pytest.raises(RuntimeError):
            view.gather(np.array([0]))
        del values
    finally:
        assert not scope.close() and runtime.budget.used == 0
