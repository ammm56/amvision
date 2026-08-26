"""LocalBuffer buddy allocator 的几何、碎片与容量守恒门禁。"""

from __future__ import annotations

import random

import pytest

from backend.service.infrastructure.local_buffers.buddy_allocator import (
    BuddyAllocationError,
    BuddyArenaAllocator,
    BuddyArenaGeometry,
)


_MIB = 1024 * 1024


def _geometry(*, huge_reserve_bytes: int = 0) -> BuddyArenaGeometry:
    """使用与正式配置同等比例、较小容量的测试几何。"""

    return BuddyArenaGeometry(
        arena_size_bytes=32 * _MIB,
        min_block_size_bytes=_MIB,
        max_allocation_bytes=16 * _MIB,
        huge_reserve_bytes=huge_reserve_bytes,
    )


@pytest.mark.parametrize(
    ("content_length", "capacity"),
    (
        (1, _MIB),
        (_MIB, _MIB),
        (_MIB + 1, 2 * _MIB),
        (3 * _MIB, 4 * _MIB),
        (9 * _MIB, 16 * _MIB),
    ),
)
def test_buddy_allocator_uses_smallest_contiguous_order(
    content_length: int,
    capacity: int,
) -> None:
    """分配只依据精确 content length，不依赖图片格式或分辨率。"""

    allocator = BuddyArenaAllocator(_geometry())
    extent = allocator.allocate(content_length)

    assert extent.offset == 0
    assert extent.capacity_bytes == capacity
    assert extent.content_length == content_length
    allocator.free(extent)
    assert allocator.snapshot()["free_capacity_bytes"] == 32 * _MIB


def test_buddy_allocator_clusters_low_addresses_and_preserves_high_root() -> None:
    """小块聚集在低地址，第二个 16 MiB 顶级 root 保持完整。"""

    allocator = BuddyArenaAllocator(_geometry())
    extents = [allocator.allocate(_MIB) for _ in range(8)]

    assert [item.offset for item in extents] == [index * _MIB for index in range(8)]
    status = allocator.snapshot()
    assert status["largest_general_free_block_bytes"] == 16 * _MIB


def test_buddy_allocator_reports_fragmentation_without_cross_root_merge() -> None:
    """总容量足够但没有连续块时返回 contiguous capacity。"""

    geometry = BuddyArenaGeometry(
        arena_size_bytes=16 * _MIB,
        min_block_size_bytes=_MIB,
        max_allocation_bytes=8 * _MIB,
    )
    allocator = BuddyArenaAllocator(geometry)
    extents = [allocator.allocate(4 * _MIB) for _ in range(4)]
    allocator.free(extents[0])
    allocator.free(extents[2])

    with pytest.raises(BuddyAllocationError) as caught:
        allocator.allocate(8 * _MIB)

    assert caught.value.kind == "contiguous_capacity"


def test_huge_reserve_is_not_borrowed_by_small_allocations() -> None:
    """hard reserve 只服务等于 reserve order 的请求。"""

    allocator = BuddyArenaAllocator(_geometry(huge_reserve_bytes=16 * _MIB))
    small = [allocator.allocate(_MIB) for _ in range(16)]
    with pytest.raises(BuddyAllocationError) as caught:
        allocator.allocate(_MIB)
    assert caught.value.kind == "total_capacity"

    huge = allocator.allocate(16 * _MIB)
    assert huge.domain == "huge_reserve"
    assert huge.offset == 16 * _MIB
    with pytest.raises(BuddyAllocationError) as caught:
        allocator.allocate(16 * _MIB)
    assert caught.value.kind == "huge_reserve"

    for extent in small:
        allocator.free(extent)
    allocator.free(huge)
    allocator.assert_invariants()


def test_frame_allocation_cannot_borrow_hard_huge_reserve() -> None:
    """frame channel 即使大小等于 max order 也只能使用 general 区。"""

    allocator = BuddyArenaAllocator(_geometry(huge_reserve_bytes=16 * _MIB))
    general = allocator.allocate(16 * _MIB, allow_huge_reserve=False)
    assert general.domain == "general"
    with pytest.raises(BuddyAllocationError) as caught:
        allocator.allocate(16 * _MIB, allow_huge_reserve=False)
    assert caught.value.kind == "total_capacity"
    status = allocator.snapshot()
    assert status["huge_free_capacity_bytes"] == 16 * _MIB
    allocator.free(general)


def test_production_geometry_supports_one_gib_contiguous_extent() -> None:
    """正式 2 GiB 几何能直接提供单个 1 GiB 连续 extent。"""

    allocator = BuddyArenaAllocator(
        BuddyArenaGeometry(
            arena_size_bytes=2 * 1024 * _MIB,
            min_block_size_bytes=_MIB,
            max_allocation_bytes=1024 * _MIB,
        )
    )
    extent = allocator.allocate(1024 * _MIB)
    assert extent.offset == 0
    assert extent.capacity_bytes == 1024 * _MIB
    allocator.free(extent)
    assert allocator.snapshot()["free_capacity_bytes"] == 2 * 1024 * _MIB


def test_frame_sized_batch_can_be_rolled_back_without_capacity_leak() -> None:
    """上层 frame channel 批量失败时可反向释放全部已分配 extent。"""

    allocator = BuddyArenaAllocator(_geometry())
    allocated = []
    with pytest.raises(BuddyAllocationError):
        for _ in range(3):
            allocated.append(allocator.allocate(9 * _MIB))
    for extent in reversed(allocated):
        allocator.free(extent)

    status = allocator.snapshot()
    assert status["allocated_capacity_bytes"] == 0
    assert status["free_capacity_bytes"] == status["arena_total_bytes"]


def test_random_100000_allocate_free_operations_preserve_invariants() -> None:
    """十万次确定性随机操作后无重叠、泄漏并完全合并。"""

    geometry = BuddyArenaGeometry(
        arena_size_bytes=128 * _MIB,
        min_block_size_bytes=_MIB,
        max_allocation_bytes=64 * _MIB,
    )
    allocator = BuddyArenaAllocator(geometry)
    randomizer = random.Random(20260826)
    active = []
    for operation_index in range(100_000):
        should_allocate = not active or (
            len(active) < 96 and randomizer.random() < 0.57
        )
        if should_allocate:
            content_length = randomizer.randint(1, 20 * _MIB)
            try:
                active.append(allocator.allocate(content_length))
            except BuddyAllocationError as error:
                assert error.kind in {"total_capacity", "contiguous_capacity"}
        else:
            index = randomizer.randrange(len(active))
            allocator.free(active.pop(index))
        if operation_index % 1_000 == 0:
            allocator.assert_invariants()

    for extent in reversed(active):
        allocator.free(extent)
    allocator.assert_invariants()
    status = allocator.snapshot()
    assert status["free_capacity_bytes"] == 128 * _MIB
    assert status["allocated_capacity_bytes"] == 0
    assert status["largest_general_free_block_bytes"] == 64 * _MIB


@pytest.mark.parametrize(
    "kwargs",
    (
        {"arena_size_bytes": 30 * _MIB},
        {"min_block_size_bytes": 3 * _MIB},
        {"max_allocation_bytes": 12 * _MIB},
        {"huge_reserve_bytes": 8 * _MIB},
    ),
)
def test_geometry_rejects_non_deterministic_layout(kwargs: dict[str, int]) -> None:
    """非法几何不能被静默修正。"""

    values = {
        "arena_size_bytes": 32 * _MIB,
        "min_block_size_bytes": _MIB,
        "max_allocation_bytes": 16 * _MIB,
        "huge_reserve_bytes": 0,
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        BuddyArenaGeometry(**values)
