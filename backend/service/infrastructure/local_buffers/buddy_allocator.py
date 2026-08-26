"""LocalBuffer 固定 arena 的纯 buddy allocator。"""

from __future__ import annotations

from bisect import insort
from dataclasses import dataclass
from threading import RLock
from typing import Literal


AllocationDomain = Literal["general", "huge_reserve"]
AllocationFailureKind = Literal[
    "total_capacity",
    "contiguous_capacity",
    "maximum_allocation",
    "huge_reserve",
    "integrity",
]


class BuddyAllocationError(RuntimeError):
    """描述可分类、可观测且不触发隐藏 fallback 的分配失败。"""

    def __init__(self, message: str, *, kind: AllocationFailureKind) -> None:
        """保存稳定的失败分类。"""

        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True, slots=True)
class BuddyArenaGeometry:
    """描述单个固定 arena 的 buddy 几何。"""

    arena_size_bytes: int
    min_block_size_bytes: int
    max_allocation_bytes: int
    huge_reserve_bytes: int = 0

    def __post_init__(self) -> None:
        """拒绝无法形成确定性顶级 root 的配置。"""

        for field_name in (
            "arena_size_bytes",
            "min_block_size_bytes",
            "max_allocation_bytes",
        ):
            value = int(getattr(self, field_name))
            if value <= 0 or not _is_power_of_two(value):
                raise ValueError(f"{field_name} 必须是大于 0 的 2 次幂")
        if self.max_allocation_bytes > self.arena_size_bytes:
            raise ValueError("max_allocation_bytes 不能超过 arena_size_bytes")
        if self.max_allocation_bytes < self.min_block_size_bytes:
            raise ValueError("max_allocation_bytes 不能小于 min_block_size_bytes")
        if self.huge_reserve_bytes not in (0, self.max_allocation_bytes):
            raise ValueError("huge_reserve_bytes 只允许 0 或 max_allocation_bytes")
        general_size = self.general_size_bytes
        if general_size <= 0:
            raise ValueError("general arena 容量必须大于 0")
        if general_size % self.max_allocation_bytes != 0:
            raise ValueError("general arena 必须由完整 max_allocation 顶级 root 组成")

    @property
    def general_size_bytes(self) -> int:
        """返回普通分配域容量。"""

        return self.arena_size_bytes - self.huge_reserve_bytes

    @property
    def min_order(self) -> int:
        """返回最小块的绝对二进制 order。"""

        return self.min_block_size_bytes.bit_length() - 1

    @property
    def max_order(self) -> int:
        """返回单次最大分配的绝对二进制 order。"""

        return self.max_allocation_bytes.bit_length() - 1

    @property
    def descriptor_count(self) -> int:
        """返回持久 descriptor 表的固定条目数量。"""

        return self.arena_size_bytes // self.min_block_size_bytes


@dataclass(frozen=True, slots=True)
class BuddyExtent:
    """描述一次连续 extent 分配结果。"""

    offset: int
    order: int
    capacity_bytes: int
    content_length: int
    domain: AllocationDomain


class BuddyArenaAllocator:
    """为一个固定容量 arena 提供确定性的低地址 buddy 分配。"""

    def __init__(self, geometry: BuddyArenaGeometry) -> None:
        """按几何创建 general 与可选 hard reserve free root。"""

        self.geometry = geometry
        self._lock = RLock()
        self._general_free: dict[int, list[int]] = {
            order: [] for order in range(geometry.min_order, geometry.max_order + 1)
        }
        self._huge_free: list[int] = []
        self._allocated: dict[int, BuddyExtent] = {}
        self._allocation_failure_counts: dict[AllocationFailureKind, int] = {
            "total_capacity": 0,
            "contiguous_capacity": 0,
            "maximum_allocation": 0,
            "huge_reserve": 0,
            "integrity": 0,
        }
        for offset in range(
            0,
            geometry.general_size_bytes,
            geometry.max_allocation_bytes,
        ):
            self._general_free[geometry.max_order].append(offset)
        if geometry.huge_reserve_bytes:
            self._huge_free.append(geometry.general_size_bytes)

    def allocate(
        self,
        content_length: int,
        *,
        allow_huge_reserve: bool = True,
    ) -> BuddyExtent:
        """分配容纳精确有效长度的最小连续 2 次幂 extent。"""

        normalized_length = int(content_length)
        if normalized_length <= 0:
            raise ValueError("content_length 必须大于 0")
        if normalized_length > self.geometry.max_allocation_bytes:
            with self._lock:
                self._allocation_failure_counts["maximum_allocation"] += 1
            raise BuddyAllocationError(
                "LocalBuffer 请求超过单次最大分配容量",
                kind="maximum_allocation",
            )
        capacity = max(
            self.geometry.min_block_size_bytes,
            _next_power_of_two(normalized_length),
        )
        order = capacity.bit_length() - 1
        with self._lock:
            if (
                allow_huge_reserve
                and self.geometry.huge_reserve_bytes
                and capacity == self.geometry.huge_reserve_bytes
            ):
                if not self._huge_free:
                    self._allocation_failure_counts["huge_reserve"] += 1
                    raise BuddyAllocationError(
                        "LocalBuffer hard huge reserve 已占用",
                        kind="huge_reserve",
                    )
                offset = self._huge_free.pop(0)
                domain: AllocationDomain = "huge_reserve"
            else:
                offset = self._allocate_general_locked(order)
                domain = "general"
            extent = BuddyExtent(
                offset=offset,
                order=order,
                capacity_bytes=capacity,
                content_length=normalized_length,
                domain=domain,
            )
            if offset in self._allocated:
                raise BuddyAllocationError(
                    "buddy allocator 返回了重复 extent",
                    kind="integrity",
                )
            self._allocated[offset] = extent
            return extent

    def free(self, extent: BuddyExtent) -> None:
        """释放 identity 完全匹配的 extent 并在顶级 root 内合并。"""

        with self._lock:
            current = self._allocated.get(extent.offset)
            if current != extent:
                raise BuddyAllocationError(
                    "LocalBuffer extent 已释放或 identity 不匹配",
                    kind="integrity",
                )
            del self._allocated[extent.offset]
            if extent.domain == "huge_reserve":
                insort(self._huge_free, extent.offset)
            else:
                self._free_general_locked(extent.offset, extent.order)

    def resize_content_length(
        self,
        extent: BuddyExtent,
        *,
        content_length: int,
    ) -> BuddyExtent:
        """只更新已分配 extent 的有效长度，不改变 capacity 与地址。"""

        normalized_length = int(content_length)
        if normalized_length <= 0 or normalized_length > extent.capacity_bytes:
            raise ValueError("content_length 超出 extent capacity")
        with self._lock:
            current = self._allocated.get(extent.offset)
            if current != extent:
                raise BuddyAllocationError(
                    "LocalBuffer extent identity 不匹配",
                    kind="integrity",
                )
            resized = BuddyExtent(
                offset=current.offset,
                order=current.order,
                capacity_bytes=current.capacity_bytes,
                content_length=normalized_length,
                domain=current.domain,
            )
            self._allocated[current.offset] = resized
            return resized

    def restore_extent(self, extent: BuddyExtent) -> None:
        """从持久 descriptor 恢复一个仍占用的精确 extent。"""

        if extent.content_length <= 0 or extent.content_length > extent.capacity_bytes:
            raise BuddyAllocationError(
                "恢复 extent 的 content length 不合法",
                kind="integrity",
            )
        if extent.capacity_bytes != 1 << extent.order:
            raise BuddyAllocationError(
                "恢复 extent 的 order 与 capacity 不一致",
                kind="integrity",
            )
        with self._lock:
            if extent.offset in self._allocated:
                raise BuddyAllocationError(
                    "恢复 extent identity 重复",
                    kind="integrity",
                )
            if extent.domain == "huge_reserve":
                try:
                    self._huge_free.remove(extent.offset)
                except ValueError as error:
                    raise BuddyAllocationError(
                        "恢复的 huge extent 不在 free reserve 中",
                        kind="integrity",
                    ) from error
            else:
                self._reserve_general_extent_locked(extent.offset, extent.order)
            self._allocated[extent.offset] = extent
            self._assert_invariants_locked()

    def snapshot(self) -> dict[str, object]:
        """返回容量守恒、碎片和每个 order 的确定性状态。"""

        with self._lock:
            self._assert_invariants_locked()
            general_free = sum(
                len(offsets) * (1 << order)
                for order, offsets in self._general_free.items()
            )
            huge_free = len(self._huge_free) * self.geometry.huge_reserve_bytes
            general_allocated = sum(
                item.capacity_bytes
                for item in self._allocated.values()
                if item.domain == "general"
            )
            huge_allocated = sum(
                item.capacity_bytes
                for item in self._allocated.values()
                if item.domain == "huge_reserve"
            )
            largest_general = max(
                (
                    1 << order
                    for order, offsets in self._general_free.items()
                    if offsets
                ),
                default=0,
            )
            fragmentation = (
                1.0 - largest_general / general_free if general_free else 0.0
            )
            return {
                "arena_total_bytes": self.geometry.arena_size_bytes,
                "general_total_bytes": self.geometry.general_size_bytes,
                "huge_reserved_total_bytes": self.geometry.huge_reserve_bytes,
                "general_free_capacity_bytes": general_free,
                "huge_free_capacity_bytes": huge_free,
                "free_capacity_bytes": general_free + huge_free,
                "general_allocated_capacity_bytes": general_allocated,
                "huge_allocated_capacity_bytes": huge_allocated,
                "allocated_capacity_bytes": general_allocated + huge_allocated,
                "published_content_bytes": sum(
                    item.content_length for item in self._allocated.values()
                ),
                "rounding_waste_bytes": sum(
                    item.capacity_bytes - item.content_length
                    for item in self._allocated.values()
                ),
                "largest_general_free_block_bytes": largest_general,
                "general_external_fragmentation": fragmentation,
                "active_extent_count": len(self._allocated),
                "free_blocks_by_order": {
                    str(order): len(offsets)
                    for order, offsets in self._general_free.items()
                },
                "allocation_failure_counts": dict(
                    self._allocation_failure_counts
                ),
            }

    def allocated_extents(self) -> tuple[BuddyExtent, ...]:
        """返回按地址排序的不可变已分配 extent 快照。"""

        with self._lock:
            return tuple(self._allocated[key] for key in sorted(self._allocated))

    def assert_invariants(self) -> None:
        """公开执行无重叠、对齐和容量守恒检查。"""

        with self._lock:
            self._assert_invariants_locked()

    def _allocate_general_locked(self, requested_order: int) -> int:
        """从最低可用地址 block 分裂得到请求 order。"""

        selected_order = next(
            (
                order
                for order in range(requested_order, self.geometry.max_order + 1)
                if self._general_free[order]
            ),
            None,
        )
        if selected_order is None:
            total_free = sum(
                len(offsets) * (1 << order)
                for order, offsets in self._general_free.items()
            )
            requested_capacity = 1 << requested_order
            kind: AllocationFailureKind = (
                "total_capacity"
                if total_free < requested_capacity
                else "contiguous_capacity"
            )
            self._allocation_failure_counts[kind] += 1
            raise BuddyAllocationError(
                "LocalBuffer 普通分配域没有可用连续 extent",
                kind=kind,
            )
        offset = self._general_free[selected_order].pop(0)
        while selected_order > requested_order:
            selected_order -= 1
            high_child = offset + (1 << selected_order)
            insort(self._general_free[selected_order], high_child)
        return offset

    def _free_general_locked(self, offset: int, order: int) -> None:
        """只在所属 max-allocation 顶级 root 内执行 buddy merge。"""

        root_size = self.geometry.max_allocation_bytes
        root_start = (offset // root_size) * root_size
        current_offset = offset
        current_order = order
        while current_order < self.geometry.max_order:
            block_size = 1 << current_order
            relative = current_offset - root_start
            buddy_offset = root_start + (relative ^ block_size)
            offsets = self._general_free[current_order]
            position = _find_sorted(offsets, buddy_offset)
            if position is None:
                break
            offsets.pop(position)
            current_offset = min(current_offset, buddy_offset)
            current_order += 1
        insort(self._general_free[current_order], current_offset)

    def _reserve_general_extent_locked(self, offset: int, order: int) -> None:
        """从 free tree 中精确切出恢复 descriptor 指向的 extent。"""

        if not 0 <= offset < self.geometry.general_size_bytes:
            raise BuddyAllocationError(
                "恢复 extent 超出 general arena",
                kind="integrity",
            )
        capacity = 1 << order
        if offset % capacity != 0:
            raise BuddyAllocationError(
                "恢复 extent 未按 order 对齐",
                kind="integrity",
            )
        root_size = self.geometry.max_allocation_bytes
        root_start = (offset // root_size) * root_size
        selected_order: int | None = None
        selected_offset = 0
        for candidate_order in range(order, self.geometry.max_order + 1):
            candidate_capacity = 1 << candidate_order
            candidate_offset = (
                root_start
                + ((offset - root_start) // candidate_capacity) * candidate_capacity
            )
            if candidate_offset in self._general_free[candidate_order]:
                selected_order = candidate_order
                selected_offset = candidate_offset
                break
        if selected_order is None:
            raise BuddyAllocationError(
                "恢复 extent 与现有 allocation/free tree 冲突",
                kind="integrity",
            )
        self._general_free[selected_order].remove(selected_offset)
        while selected_order > order:
            selected_order -= 1
            half_size = 1 << selected_order
            low_child = selected_offset
            high_child = selected_offset + half_size
            if offset < high_child:
                insort(self._general_free[selected_order], high_child)
                selected_offset = low_child
            else:
                insort(self._general_free[selected_order], low_child)
                selected_offset = high_child
        if selected_offset != offset:
            raise BuddyAllocationError(
                "恢复 extent split 未落到目标地址",
                kind="integrity",
            )

    def _assert_invariants_locked(self) -> None:
        """校验所有 free/allocated extent 唯一、不重叠且容量守恒。"""

        ranges: list[tuple[int, int, str]] = []
        for order, offsets in self._general_free.items():
            capacity = 1 << order
            if offsets != sorted(offsets) or len(offsets) != len(set(offsets)):
                raise BuddyAllocationError(
                    "buddy free list 顺序或唯一性损坏",
                    kind="integrity",
                )
            for offset in offsets:
                if offset % capacity != 0:
                    raise BuddyAllocationError(
                        "buddy free block 未按 order 对齐",
                        kind="integrity",
                    )
                ranges.append((offset, offset + capacity, "general_free"))
        reserve_start = self.geometry.general_size_bytes
        for offset in self._huge_free:
            ranges.append(
                (offset, offset + self.geometry.huge_reserve_bytes, "huge_free")
            )
        for extent in self._allocated.values():
            if extent.offset % extent.capacity_bytes != 0:
                raise BuddyAllocationError(
                    "已分配 extent 未按容量对齐",
                    kind="integrity",
                )
            expected_domain: AllocationDomain = (
                "huge_reserve"
                if extent.offset >= reserve_start and self.geometry.huge_reserve_bytes
                else "general"
            )
            if extent.domain != expected_domain:
                raise BuddyAllocationError(
                    "extent 分配域与地址不一致",
                    kind="integrity",
                )
            ranges.append(
                (extent.offset, extent.offset + extent.capacity_bytes, "allocated")
            )
        ranges.sort()
        for previous, current in zip(ranges, ranges[1:], strict=False):
            if previous[1] > current[0]:
                raise BuddyAllocationError(
                    "buddy extent 发生重叠",
                    kind="integrity",
                )
        total = sum(end - start for start, end, _kind in ranges)
        if total != self.geometry.arena_size_bytes:
            raise BuddyAllocationError(
                "buddy allocator 容量守恒失败",
                kind="integrity",
            )


def _is_power_of_two(value: int) -> bool:
    """返回整数是否为正 2 次幂。"""

    return value > 0 and value & (value - 1) == 0


def _next_power_of_two(value: int) -> int:
    """返回大于等于 value 的最小 2 次幂。"""

    return 1 << (value - 1).bit_length()


def _find_sorted(values: list[int], target: int) -> int | None:
    """在线性长度很小的 order bucket 中定位 target。"""

    try:
        return values.index(target)
    except ValueError:
        return None
