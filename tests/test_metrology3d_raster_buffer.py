"""真实 mmap 借用、原像素顺序、取消与释放，不用 bytes 夹具代替所有权验证。"""

from contextlib import contextmanager
from hashlib import sha256
import weakref

import numpy as np
import pytest

from backend.contracts.workflows.raster3d import RasterBufferDescriptor
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.budget import CloudArrayBudget
from backend.service.application.workflows.point_cloud.raster_buffer import (
    borrow_raster_buffer,
    raster_descriptor_sha256,
)
from backend.service.infrastructure.local_buffers.mmap_buffer_arena import (
    LocalBufferArenaError,
    MmapBufferArena,
    MmapBufferArenaExternalAccess,
)
from custom_nodes.metrology3d_nodes.shared.raster_conversion import convert_raster
from tests.point_cloud_support import policy
from tests.test_local_buffer_mmap_arena import _config, _deadline
from tests.test_metrology3d_raster_conversion import specification


def descriptor():
    """十二像素和原始掩码，不携带运行 lease。"""
    return RasterBufferDescriptor(
        format_id="amvision.raster-buffer.v1",
        raster=specification(),
        has_mask=True,
        content_length=60,
    )


def payload():
    """独立载荷，两个输入无效，其他点保持行优先身份。"""
    return np.arange(12, dtype="<f4").tobytes() + bytes([1, 0] + [1] * 10)


@pytest.fixture
def arena_input(tmp_path):
    """使用平台现有 arena，不新增数据面。"""
    config = _config(tmp_path)
    with MmapBufferArena(config) as arena:
        receipt = arena.allocate(content_length=60, deadline_ns=_deadline())
        with arena.acquire_writer_view(receipt) as view:
            view[:] = payload()
        arena.publish_active(receipt)
        external = MmapBufferArenaExternalAccess(config)
        try:
            yield arena, receipt, lambda: external.acquire_reader_view(receipt)
        finally:
            external.close()


def borrow(acquire, budget, **changes):
    """显式测试策略，未修改工程工作站配置。"""
    return borrow_raster_buffer(
        **(
            dict(
                descriptor=descriptor(),
                expected_descriptor_sha256=raster_descriptor_sha256(descriptor()),
                acquire_view=acquire,
                policy=policy(),
                budget=budget,
                cancel=lambda: None,
            )
            | changes
        )
    )


def test_real_arena_to_coordinates_and_reclaim(arena_input):
    arena, receipt, acquire = arena_input
    budget = CloudArrayBudget(policy().max_live_array_bytes)
    scope = ResourceScope(kind="raster-test")
    with borrow(acquire, budget) as raster:
        assert raster.content_sha256 == sha256(payload()).hexdigest()
        with pytest.raises(ValueError):
            raster.arrays["samples"].setflags(write=True)
        result = convert_raster(
            raster.arrays["samples"],
            raster.arrays["mask"],
            descriptor().raster,
            policy=policy(),
            budget=budget,
            scope=scope,
            cancel=lambda: None,
        )
        assert result.counts["valid"] == 10
        assert arena.request_reclaim(receipt) == "revoking"
    assert not raster.arrays
    assert arena.request_reclaim(receipt) == "released"
    # 输出已拥有独立数组，输入租约关闭不影响结果；最终 Scope 回收输出。
    with result.arrays.borrow() as arrays:
        np.testing.assert_array_equal(arrays["raw_samples"][:, 0], np.arange(12))
    assert not scope.close()
    assert budget.used == 0
    with pytest.raises(LocalBufferArenaError):
        with borrow(acquire, budget):
            pytest.fail("stale input accepted")
    assert budget.used == 0


def test_cancel_and_consumer_error_release_aliases(arena_input):
    arena, receipt, acquire = arena_input
    budget = CloudArrayBudget(policy().max_live_array_bytes)
    with pytest.raises(RuntimeError, match="consumer"):
        with borrow(acquire, budget) as raster:
            refs = [weakref.ref(a) for a in raster.arrays.values()]
            raise RuntimeError("consumer")
    assert all(ref() is None for ref in refs)
    for at in range(1, 14):
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
def guard(data):
    """只用于非法载荷注入。"""
    with memoryview(data) as view:
        yield view


@pytest.mark.parametrize(
    "change",
    [
        lambda b: b[:-1],
        lambda b: b + b"0",
        bytearray,
        lambda b: b[:48] + b"\x02" + b[49:],
    ],
)
def test_invalid_bytes_rejected(change):
    budget = CloudArrayBudget(policy().max_live_array_bytes)
    with pytest.raises(InvalidRequestError):
        with borrow(lambda: guard(change(payload())), budget):
            pytest.fail("bad input")
    assert budget.used == 0


def test_admission_before_mapping_and_close_failure():
    budget = CloudArrayBudget(policy().max_live_array_bytes)

    def unexpected():
        raise AssertionError("mapping before admission")

    for changes in (
        dict(expected_descriptor_sha256="0" * 64),
        dict(policy=policy(max_decoded_bytes=50)),
    ):
        with pytest.raises(InvalidRequestError):
            with borrow(unexpected, budget, **changes):
                pass
    assert budget.used == 0

    @contextmanager
    def failing():
        with guard(payload()) as view:
            yield view
        raise RuntimeError("guard close failed")

    with pytest.raises(RuntimeError, match="guard close failed"):
        with borrow(failing, budget):
            pass
    assert budget.used == 60
