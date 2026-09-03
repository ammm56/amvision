"""保存结果保留清理的确定性策略和有界内存执行器。"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
import calendar
import fnmatch
import heapq
import os
from pathlib import PurePosixPath
from time import monotonic
from typing import Literal

from backend.service.application.ports.object_store import (
    RetentionDeleteState,
    RetentionObjectMetadata,
    RetentionObjectPage,
)


RetentionPolicy = Literal["age", "count", "age-and-count"]
RetentionUnit = Literal["day", "month", "year"]


@dataclass(frozen=True)
class StorageRetentionOptions:
    """保存一次保留清理调用的已校验参数。"""

    retention_policy: RetentionPolicy
    retention_value: int | None
    retention_unit: RetentionUnit | None
    max_file_count: int | None
    include_patterns: tuple[str, ...]
    delete_limit: int
    dry_run: bool
    delete_empty_directories: bool


@dataclass(frozen=True)
class StorageRetentionResult:
    """保存一次保留清理执行的稳定统计。"""

    state: Literal["dry_run", "completed", "partial"]
    cutoff_time: datetime | None
    scanned_file_count: int
    matched_file_count: int
    eligible_file_count: int
    deleted_file_count: int
    deleted_size_bytes: int
    skipped_changed_count: int
    skipped_locked_count: int
    skipped_missing_count: int
    failed_file_count: int
    has_more: bool
    duration_ms: int


@dataclass(frozen=True)
class _ReverseOldestEntry:
    """让 heap 根节点保存当前候选中最新的项目。"""

    order_key: tuple[int, str]
    item: RetentionObjectMetadata

    def __lt__(self, other: _ReverseOldestEntry) -> bool:
        return self.order_key > other.order_key


def calculate_retention_cutoff(
    current_time: datetime,
    *,
    retention_value: int,
    retention_unit: RetentionUnit,
) -> datetime:
    """按日历日、月或年计算保留截止时间。"""

    if retention_value <= 0:
        raise ValueError("retention_value 必须大于 0")
    if retention_unit == "day":
        return current_time - timedelta(days=retention_value)
    if retention_unit == "month":
        month_index = current_time.year * 12 + current_time.month - 1 - retention_value
        target_year, zero_based_month = divmod(month_index, 12)
        target_month = zero_based_month + 1
        target_day = min(
            current_time.day,
            calendar.monthrange(target_year, target_month)[1],
        )
        return current_time.replace(
            year=target_year,
            month=target_month,
            day=target_day,
        )
    if retention_unit == "year":
        target_year = current_time.year - retention_value
        target_day = min(
            current_time.day,
            calendar.monthrange(target_year, current_time.month)[1],
        )
        return current_time.replace(year=target_year, day=target_day)
    raise ValueError(f"不支持的 retention_unit: {retention_unit}")


def execute_storage_retention(
    *,
    options: StorageRetentionOptions,
    current_time: datetime,
    iter_pages: Callable[[], Iterator[RetentionObjectPage]],
    delete_item: Callable[[RetentionObjectMetadata], RetentionDeleteState],
    delete_empty_directories: Callable[[], int],
) -> StorageRetentionResult:
    """通过一次流式扫描和有界 heap 执行一次保留清理。"""

    started_at = monotonic()
    cutoff_time = _resolve_cutoff_time(options=options, current_time=current_time)
    cutoff_epoch_ns = (
        int(cutoff_time.timestamp() * 1_000_000_000)
        if cutoff_time is not None
        else None
    )
    oldest_heap: list[_ReverseOldestEntry] = []
    scanned_file_count = 0
    matched_file_count = 0
    age_candidate_count = 0
    for page in iter_pages():
        scanned_file_count += len(page.items)
        for item in page.items:
            if not _matches_patterns(item.object_key, options.include_patterns):
                continue
            matched_file_count += 1
            if not options.dry_run:
                _retain_oldest_item(
                    oldest_heap,
                    item=item,
                    selection_limit=options.delete_limit,
                )
            if (
                cutoff_epoch_ns is not None
                and item.last_modified_epoch_ns < cutoff_epoch_ns
            ):
                age_candidate_count += 1

    count_candidate_count = (
        max(0, matched_file_count - int(options.max_file_count or 0))
        if options.retention_policy in {"count", "age-and-count"}
        else 0
    )
    eligible_file_count = (
        age_candidate_count
        if options.retention_policy == "age"
        else count_candidate_count
        if options.retention_policy == "count"
        else max(age_candidate_count, count_candidate_count)
    )
    if options.dry_run:
        return StorageRetentionResult(
            state="dry_run",
            cutoff_time=cutoff_time,
            scanned_file_count=scanned_file_count,
            matched_file_count=matched_file_count,
            eligible_file_count=eligible_file_count,
            deleted_file_count=0,
            deleted_size_bytes=0,
            skipped_changed_count=0,
            skipped_locked_count=0,
            skipped_missing_count=0,
            failed_file_count=0,
            has_more=eligible_file_count > 0,
            duration_ms=_elapsed_milliseconds(started_at),
        )

    selection_count = min(eligible_file_count, options.delete_limit)
    selected_items = tuple(
        entry.item
        for entry in sorted(oldest_heap, key=lambda value: value.order_key)[
            :selection_count
        ]
    )
    deleted_file_count = 0
    deleted_size_bytes = 0
    skipped_changed_count = 0
    skipped_locked_count = 0
    skipped_missing_count = 0
    for item in selected_items:
        delete_state = delete_item(item)
        if delete_state == "deleted":
            deleted_file_count += 1
            deleted_size_bytes += item.content_length
        elif delete_state == "changed":
            skipped_changed_count += 1
        elif delete_state == "locked":
            skipped_locked_count += 1
        elif delete_state == "missing":
            skipped_missing_count += 1
        else:
            raise RuntimeError(f"未知保留清理删除状态: {delete_state}")
    if options.delete_empty_directories:
        delete_empty_directories()
    has_more = (
        eligible_file_count > selection_count
        or skipped_changed_count > 0
        or skipped_locked_count > 0
    )
    return StorageRetentionResult(
        state="partial" if has_more else "completed",
        cutoff_time=cutoff_time,
        scanned_file_count=scanned_file_count,
        matched_file_count=matched_file_count,
        eligible_file_count=eligible_file_count,
        deleted_file_count=deleted_file_count,
        deleted_size_bytes=deleted_size_bytes,
        skipped_changed_count=skipped_changed_count,
        skipped_locked_count=skipped_locked_count,
        skipped_missing_count=skipped_missing_count,
        failed_file_count=0,
        has_more=has_more,
        duration_ms=_elapsed_milliseconds(started_at),
    )


def _resolve_cutoff_time(
    *,
    options: StorageRetentionOptions,
    current_time: datetime,
) -> datetime | None:
    """按策略决定是否需要计算时间截止点。"""

    if options.retention_policy not in {"age", "age-and-count"}:
        return None
    if options.retention_value is None or options.retention_unit is None:
        raise ValueError("时间保留策略缺少 retention_value 或 retention_unit")
    return calculate_retention_cutoff(
        current_time,
        retention_value=options.retention_value,
        retention_unit=options.retention_unit,
    )


def _retain_oldest_item(
    heap: list[_ReverseOldestEntry],
    *,
    item: RetentionObjectMetadata,
    selection_limit: int,
) -> None:
    """在有界 max-heap 中保留当前扫描范围最旧的项目。"""

    entry = _ReverseOldestEntry(
        order_key=_build_order_key(item),
        item=item,
    )
    if len(heap) < selection_limit:
        heapq.heappush(heap, entry)
        return
    if entry.order_key < heap[0].order_key:
        heapq.heapreplace(heap, entry)


def _build_order_key(item: RetentionObjectMetadata) -> tuple[int, str]:
    """构造修改时间和规范 key 组成的稳定先后顺序。"""

    normalized_key = PurePosixPath(item.object_key).as_posix()
    if os.name == "nt":
        normalized_key = normalized_key.casefold()
    return item.last_modified_epoch_ns, normalized_key


def _matches_patterns(object_key: str, patterns: tuple[str, ...]) -> bool:
    """只使用文件名匹配一个或多个 include pattern。"""

    file_name = PurePosixPath(object_key).name
    if os.name == "nt":
        file_name = file_name.casefold()
        return any(
            fnmatch.fnmatchcase(file_name, pattern.casefold()) for pattern in patterns
        )
    return any(fnmatch.fnmatchcase(file_name, pattern) for pattern in patterns)


def _elapsed_milliseconds(started_at: float) -> int:
    """返回非负整数毫秒耗时。"""

    return max(0, int(round((monotonic() - started_at) * 1_000)))


__all__ = [
    "StorageRetentionOptions",
    "StorageRetentionResult",
    "calculate_retention_cutoff",
    "execute_storage_retention",
]
