"""点云数组复用真实 arena 的只读 guard、失效身份及释放边界。"""

from contextlib import contextmanager
from hashlib import sha256
import struct
import weakref

import numpy as np
import pytest

from backend.contracts.workflows.point_cloud import CloudBufferDescriptor
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.point_cloud.budget import CloudArrayBudget
from backend.service.application.workflows.point_cloud.local_array import (
    borrow_cloud_buffer,
    cloud_descriptor_sha256,
)
from backend.service.infrastructure.local_buffers.mmap_buffer_arena import (
    LocalBufferArenaError,
    MmapBufferArena,
    MmapBufferArenaExternalAccess,
)
from tests.point_cloud_support import policy, spatial
from tests.test_local_buffer_mmap_arena import _config, _deadline


def descriptor():
    """含六字节对齐填充与不可转成 JSON number 的 uint64 属性。"""
    return CloudBufferDescriptor.model_validate(
        {
            "format_id": "amvision.point-cloud-buffer.v1",
            "point_count": 2,
            "content_length": 48,
            "spatial": spatial(),
            "fields": [
                {
                    "name": "positions",
                    "semantic": "position",
                    "dtype": "float32",
                    "components": 3,
                    "unit": None,
                    "count": 2,
                    "offset_bytes": 0,
                    "byte_length": 24,
                },
                {
                    "name": "validity",
                    "semantic": "validity",
                    "dtype": "uint8",
                    "components": 1,
                    "unit": "1",
                    "count": 2,
                    "offset_bytes": 24,
                    "byte_length": 2,
                },
                {
                    "name": "label",
                    "semantic": "scalar",
                    "dtype": "uint64",
                    "components": 1,
                    "unit": "1",
                    "count": 2,
                    "offset_bytes": 32,
                    "byte_length": 16,
                },
            ],
        }
    )


def payload():
    """独立二进制夹具，含一个非有限坐标但未改写 validity。"""
    return struct.pack("<6f2B6x2Q", 1, 2, 3, float("nan"), 5, 6, 1, 1, 2**64 - 1, 7)


def borrow(acquire, budget, **changes):
    """测试仅显式传入固定预算，不修改生产配置。"""
    params = dict(
        descriptor=descriptor(),
        expected_descriptor_sha256=cloud_descriptor_sha256(descriptor()),
        acquire_view=acquire,
        policy=policy(),
        budget=budget,
        cancel=lambda: None,
    )
    return borrow_cloud_buffer(**(params | changes))


@pytest.fixture
def arena_input(tmp_path):
    config = _config(tmp_path)
    with MmapBufferArena(config) as arena:
        receipt = arena.allocate(content_length=48, deadline_ns=_deadline())
        with arena.acquire_writer_view(receipt) as view:
            view[:] = payload()
        arena.publish_active(receipt)
        external = MmapBufferArenaExternalAccess(config)
        try:
            yield arena, receipt, lambda: external.acquire_reader_view(receipt)
        finally:
            external.close()


def test_real_arena_readonly_borrow_blocks_reclaim(arena_input):
    arena, receipt, acquire = arena_input
    budget = CloudArrayBudget(policy().max_live_array_bytes)
    with borrow(acquire, budget) as cloud:
        assert cloud.content_sha256 == sha256(payload()).hexdigest()
        assert cloud.non_finite_positions == 1
        assert cloud.arrays["positions"].dtype == np.dtype("<f4")
        assert int(cloud.arrays["label"][0, 0]) == 2**64 - 1
        assert cloud.arrays["validity"][1, 0] == 1
        with pytest.raises(ValueError):
            cloud.arrays["positions"].setflags(write=True)
        assert budget.used == 48
        assert arena.request_reclaim(receipt) == "revoking"
    assert not cloud.arrays and budget.used == 0
    assert arena.request_reclaim(receipt) == "released"
    with pytest.raises(LocalBufferArenaError):
        with borrow(acquire, budget):
            pytest.fail("stale descriptor must not be borrowed")
    assert budget.used == 0


def test_cancel_and_consumer_error_clear_aliases_before_guard_exit(arena_input):
    arena, receipt, acquire = arena_input
    budget = CloudArrayBudget(policy().max_live_array_bytes)
    with pytest.raises(RuntimeError, match="consumer"):
        with borrow(acquire, budget) as cloud:
            references = [weakref.ref(array) for array in cloud.arrays.values()]
            raise RuntimeError("consumer failure")
    assert all(reference() is None for reference in references)
    assert budget.used == 0
    for at in range(1, 12):
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == at:
                raise InterruptedError("cancel")

        try:
            with borrow(acquire, budget, cancel=cancel):
                pass
        except InterruptedError:
            pass
        assert budget.used == 0
    assert arena.request_reclaim(receipt) == "released"


@contextmanager
def byte_guard(data):
    """只用于格式错误注入；生产入口使用上述真实 arena guard。"""
    with memoryview(data) as view:
        yield view


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda data: data[:26] + b"\x01" + data[27:], "填充"),
        (lambda data: data[:24] + b"\x02" + data[25:], "validity"),
        (lambda data: data[:-1], "长度"),
        (lambda data: data + b"\x00", "长度"),
        (bytearray, "只读"),
    ],
)
def test_invalid_payload_never_yields_arrays(change, match):
    budget = CloudArrayBudget(policy().max_live_array_bytes)
    with pytest.raises(InvalidRequestError, match=match):
        with borrow(lambda: byte_guard(change(payload())), budget):
            pytest.fail("invalid payload must not publish")
    assert budget.used == 0


def test_descriptor_change_and_capacity_reject_before_mapping():
    budget = CloudArrayBudget(policy().max_live_array_bytes)

    def unexpected():
        raise AssertionError("must reject before acquiring mapping")

    with pytest.raises(InvalidRequestError, match="摘要"):
        with borrow(unexpected, budget, expected_descriptor_sha256="0" * 64):
            pass
    with pytest.raises(InvalidRequestError, match="预算"):
        with borrow(unexpected, budget, policy=policy(max_decoded_bytes=32)):
            pass
    assert budget.used == 0


def test_failed_guard_close_does_not_return_budget():
    budget = CloudArrayBudget(policy().max_live_array_bytes)

    @contextmanager
    def broken_close():
        with memoryview(payload()) as view:
            yield view
        raise RuntimeError("guard close failed")

    with pytest.raises(RuntimeError, match="guard close failed"):
        with borrow(broken_close, budget):
            pass
    assert budget.used == 48
