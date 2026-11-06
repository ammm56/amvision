"""B07 真实 mmap 行表借用、输入撤销、转换输出独立所有权及异常回收。"""

from contextlib import contextmanager
from hashlib import sha256
import weakref

import numpy as np
import pytest

from backend.contracts.workflows.profile3d import ProfileBufferDescriptor
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.budget import CloudArrayBudget
from backend.service.application.workflows.point_cloud.profile_buffer import (
    borrow_profile_buffer,
    profile_descriptor_sha256,
)
from backend.service.infrastructure.local_buffers.mmap_buffer_arena import (
    MmapBufferArena,
    MmapBufferArenaExternalAccess,
    LocalBufferArenaError,
)
from custom_nodes.metrology3d_nodes.shared.profile_conversion import convert_profiles
from tests.point_cloud_support import policy
from tests.test_local_buffer_mmap_arena import _config, _deadline
from tests.test_metrology3d_profile_conversion import inputs, specification


def descriptor():
    spec = specification()
    return ProfileBufferDescriptor(
        format_id="amvision.profile-buffer.v1",
        profiles=spec,
        has_validity=False,
        content_length=spec.input_bytes(has_validity=False),
    )


def payload():
    arrays = inputs()
    return b"".join(
        arrays[name].astype(np.dtype(dtype).newbyteorder("<"), copy=False).tobytes()
        for name, dtype, _ in descriptor().profiles.input_layout(has_validity=False)
    )


@pytest.fixture
def arena_input(tmp_path):
    config = _config(tmp_path)
    with MmapBufferArena(config) as arena:
        receipt = arena.allocate(content_length=len(payload()), deadline_ns=_deadline())
        with arena.acquire_writer_view(receipt) as view:
            view[:] = payload()
        arena.publish_active(receipt)
        external = MmapBufferArenaExternalAccess(config)
        try:
            yield arena, receipt, lambda: external.acquire_reader_view(receipt)
        finally:
            external.close()


def borrow(acquire, budget, **changes):
    return borrow_profile_buffer(
        **(
            dict(
                descriptor=descriptor(),
                expected_descriptor_sha256=profile_descriptor_sha256(descriptor()),
                acquire_view=acquire,
                policy=policy(),
                budget=budget,
                cancel=lambda: None,
            )
            | changes
        )
    )


def test_real_mmap_conversion_and_reclaim(arena_input):
    arena, receipt, acquire = arena_input
    budget = CloudArrayBudget(policy().max_live_array_bytes)
    scope = ResourceScope(kind="profiles-test")
    try:
        with borrow(acquire, budget) as source:
            assert source.content_sha256 == sha256(payload()).hexdigest()
            with pytest.raises(ValueError):
                source.arrays["profiles"].setflags(write=True)
            result = convert_profiles(
                source.arrays,
                descriptor().profiles,
                has_validity=False,
                policy=policy(),
                budget=budget,
                scope=scope,
                cancel=lambda: None,
            )
            assert arena.request_reclaim(receipt) == "revoking"
        assert not source.arrays
        assert arena.request_reclaim(receipt) == "released"
        with result.arrays.borrow() as output:
            np.testing.assert_array_equal(
                output["acquisition_line_id"][:, 0], [3, 3, 8, 8, 8, 9]
            )
        with pytest.raises(LocalBufferArenaError):
            with borrow(acquire, budget):
                pytest.fail("stale lease")
    finally:
        scope.close()
        assert budget.used == 0


def test_consumer_error_and_cancel_release_array_aliases(arena_input):
    arena, receipt, acquire = arena_input
    budget = CloudArrayBudget(policy().max_live_array_bytes)
    with pytest.raises(RuntimeError):
        with borrow(acquire, budget) as source:
            refs = [weakref.ref(a) for a in source.arrays.values()]
            raise RuntimeError("consumer")
    assert all(r() is None for r in refs)
    for stop in range(1, 8):
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == stop:
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
    with memoryview(data) as view:
        yield view


@pytest.mark.parametrize(
    "transform", [lambda data: data[:-1], lambda data: data + b"x", bytearray]
)
def test_wrong_length_or_mutable_payload_rejected(transform):
    budget = CloudArrayBudget(policy().max_live_array_bytes)
    with pytest.raises(InvalidRequestError):
        with borrow(lambda: guard(transform(payload())), budget):
            pytest.fail("bad bytes")
    assert budget.used == 0


def test_descriptor_admission_precedes_mapping():
    budget = CloudArrayBudget(policy().max_live_array_bytes)
    with pytest.raises(InvalidRequestError):
        with borrow(
            lambda: pytest.fail("mapped before admission"),
            budget,
            expected_descriptor_sha256="0" * 64,
        ):
            pass
    assert budget.used == 0


def test_failed_reader_release_does_not_report_capacity_reclaimed():
    budget = CloudArrayBudget(policy().max_live_array_bytes)

    @contextmanager
    def failed_close():
        with guard(payload()) as view:
            yield view
        raise RuntimeError("reader close failed")

    with pytest.raises(RuntimeError, match="reader close failed"):
        with borrow(failed_close, budget):
            pass
    assert budget.used == descriptor().content_length
