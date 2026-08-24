"""可跨持久化 UTC deadline 与当前进程 monotonic 时钟的转换。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import time


@dataclass(frozen=True)
class AttemptDeadline:
    """表示一次 Attempt 在当前进程中的不可延长 deadline。"""

    deadline_at: datetime
    monotonic_deadline: float

    @classmethod
    def from_timeout(
        cls,
        timeout_seconds: float,
        *,
        now_utc: datetime | None = None,
        now_monotonic: float | None = None,
    ) -> AttemptDeadline:
        """从相对时限建立可持久化与进程内 deadline。"""

        timeout = float(timeout_seconds)
        if timeout <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        current_utc = _require_aware_utc(now_utc or datetime.now(UTC))
        current_monotonic = (
            time.monotonic() if now_monotonic is None else float(now_monotonic)
        )
        return cls(
            deadline_at=datetime.fromtimestamp(
                current_utc.timestamp() + timeout,
                tz=UTC,
            ),
            monotonic_deadline=current_monotonic + timeout,
        )

    @classmethod
    def from_deadline_at(
        cls,
        deadline_at: datetime | str,
        *,
        now_utc: datetime | None = None,
        now_monotonic: float | None = None,
    ) -> AttemptDeadline:
        """从持久化 UTC deadline 恢复当前进程的 monotonic deadline。"""

        parsed = (
            datetime.fromisoformat(deadline_at.replace("Z", "+00:00"))
            if isinstance(deadline_at, str)
            else deadline_at
        )
        normalized = _require_aware_utc(parsed)
        current_utc = _require_aware_utc(now_utc or datetime.now(UTC))
        current_monotonic = (
            time.monotonic() if now_monotonic is None else float(now_monotonic)
        )
        remaining = max(0.0, normalized.timestamp() - current_utc.timestamp())
        return cls(
            deadline_at=normalized,
            monotonic_deadline=current_monotonic + remaining,
        )

    @property
    def deadline_at_iso(self) -> str:
        """返回统一 UTC ISO 表示。"""

        return self.deadline_at.isoformat().replace("+00:00", "Z")

    def remaining_seconds(self, *, now_monotonic: float | None = None) -> float:
        """返回不可为负的剩余秒数。"""

        current = time.monotonic() if now_monotonic is None else float(now_monotonic)
        return max(0.0, self.monotonic_deadline - current)

    def expired(self, *, now_monotonic: float | None = None) -> bool:
        """返回当前进程是否已到达 deadline。"""

        return self.remaining_seconds(now_monotonic=now_monotonic) <= 0


def _require_aware_utc(value: datetime) -> datetime:
    """校验并统一带时区时间为 UTC。"""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("deadline_at 必须包含时区")
    return value.astimezone(UTC)


__all__ = ["AttemptDeadline"]
