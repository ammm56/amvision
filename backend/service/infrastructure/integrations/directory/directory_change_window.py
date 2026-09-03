"""directory-watch 固定窗口有界聚合器。"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import heapq
from typing import Iterable

from backend.contracts.workflows import DIRECTORY_CHANGE_EVENT_TYPES


@dataclass(frozen=True)
class MatchedDirectoryChange:
    """描述已经通过目录过滤的一条 watcher 观察事实。"""

    change_type: str
    path: str
    relative_path: str
    path_key: str


@dataclass(frozen=True)
class DirectoryChangeSampleSnapshot:
    """描述窗口快照中的一条路径样本。"""

    observed_change_types: tuple[str, ...]
    path: str
    relative_path: str
    observed_at: str
    observed_sequence: int


@dataclass(frozen=True)
class DirectoryChangeWindowSnapshot:
    """描述一次到期目录变化窗口的不可变快照。"""

    window_started_at: str
    window_finished_at: str
    window_deadline_monotonic: float
    created_count: int
    modified_count: int
    deleted_count: int
    samples: tuple[DirectoryChangeSampleSnapshot, ...]
    samples_truncated: bool

    @property
    def total_change_count(self) -> int:
        """返回本窗口观察到的变化总数。"""

        return self.created_count + self.modified_count + self.deleted_count


@dataclass
class _MutableSample:
    """保存当前窗口中一条样本的可变状态。"""

    observed_change_types: tuple[str, ...]
    path: str
    relative_path: str
    observed_at: str
    observed_sequence: int


class DirectoryChangeWindowAccumulator:
    """按首次变化锚定的固定窗口聚合目录事件。"""

    def __init__(self, *, interval_seconds: float, sample_limit: int) -> None:
        """初始化空窗口聚合器。"""

        self.interval_seconds = interval_seconds
        self.sample_limit = sample_limit
        self.window_started_monotonic: float | None = None
        self.window_deadline_monotonic: float | None = None
        self.window_started_at: str | None = None
        self.created_count = 0
        self.modified_count = 0
        self.deleted_count = 0
        self.observed_sequence = 0
        self.samples_truncated = False
        self._samples: OrderedDict[str, _MutableSample] = OrderedDict()

    @property
    def is_open(self) -> bool:
        """返回当前是否存在包含变化的活动窗口。"""

        return self.window_started_monotonic is not None

    @property
    def total_change_count(self) -> int:
        """返回当前窗口累计的变化总数。"""

        return self.created_count + self.modified_count + self.deleted_count

    @property
    def sample_count(self) -> int:
        """返回当前长期保留的样本数量。"""

        return len(self._samples)

    def is_due(self, now_monotonic: float) -> bool:
        """判断当前窗口是否已经到期。"""

        deadline = self.window_deadline_monotonic
        return deadline is not None and now_monotonic >= deadline

    def add_batch(
        self,
        changes: Iterable[MatchedDirectoryChange],
        *,
        observed_monotonic: float,
        observed_at: str,
    ) -> tuple[int, bool]:
        """单次遍历一个无序 watcher 批次并合并有界样本。"""

        selected_by_key: dict[str, tuple[MatchedDirectoryChange, set[str]]] = {}
        selected_key_heap: list[str] = []
        matched_count = 0
        opened_window = False
        for change in changes:
            matched_count += 1
            self._increment_change_count(change.change_type)
            if not self.is_open:
                self.window_started_monotonic = observed_monotonic
                self.window_deadline_monotonic = (
                    observed_monotonic + self.interval_seconds
                )
                self.window_started_at = observed_at
                opened_window = True
            if self.sample_limit == 0:
                self.samples_truncated = True
                continue
            selected = selected_by_key.get(change.path_key)
            if selected is not None:
                selected[1].add(change.change_type)
                continue
            if len(selected_by_key) < self.sample_limit:
                selected_by_key[change.path_key] = (change, {change.change_type})
                heapq.heappush(selected_key_heap, change.path_key)
                continue
            self.samples_truncated = True
            if change.path_key <= selected_key_heap[0]:
                continue
            removed_key = heapq.heapreplace(selected_key_heap, change.path_key)
            selected_by_key.pop(removed_key, None)
            selected_by_key[change.path_key] = (change, {change.change_type})

        for path_key in sorted(selected_by_key):
            change, change_types = selected_by_key[path_key]
            self.observed_sequence += 1
            self._samples.pop(path_key, None)
            self._samples[path_key] = _MutableSample(
                observed_change_types=tuple(
                    item for item in DIRECTORY_CHANGE_EVENT_TYPES if item in change_types
                ),
                path=change.path,
                relative_path=change.relative_path,
                observed_at=observed_at,
                observed_sequence=self.observed_sequence,
            )
            if len(self._samples) > self.sample_limit:
                self._samples.popitem(last=False)
                self.samples_truncated = True
        return matched_count, opened_window

    def snapshot_and_reset(
        self,
        *,
        window_finished_at: str,
    ) -> DirectoryChangeWindowSnapshot | None:
        """生成不可变快照并立即清空当前窗口。"""

        if not self.is_open or self.window_started_at is None:
            return None
        deadline = self.window_deadline_monotonic
        if deadline is None:
            return None
        snapshot = DirectoryChangeWindowSnapshot(
            window_started_at=self.window_started_at,
            window_finished_at=window_finished_at,
            window_deadline_monotonic=deadline,
            created_count=self.created_count,
            modified_count=self.modified_count,
            deleted_count=self.deleted_count,
            samples=tuple(
                DirectoryChangeSampleSnapshot(
                    observed_change_types=sample.observed_change_types,
                    path=sample.path,
                    relative_path=sample.relative_path,
                    observed_at=sample.observed_at,
                    observed_sequence=sample.observed_sequence,
                )
                for sample in reversed(self._samples.values())
            ),
            samples_truncated=self.samples_truncated,
        )
        self._reset()
        return snapshot

    def _increment_change_count(self, change_type: str) -> None:
        """增加指定变化类型的窗口计数。"""

        if change_type == "created":
            self.created_count += 1
        elif change_type == "modified":
            self.modified_count += 1
        elif change_type == "deleted":
            self.deleted_count += 1
        else:
            raise ValueError(f"不支持的目录变化类型: {change_type}")

    def _reset(self) -> None:
        """清空当前窗口的全部长期状态。"""

        self.window_started_monotonic = None
        self.window_deadline_monotonic = None
        self.window_started_at = None
        self.created_count = 0
        self.modified_count = 0
        self.deleted_count = 0
        self.observed_sequence = 0
        self.samples_truncated = False
        self._samples.clear()
