"""Conversion Attempt 的不可变总 deadline 策略。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Mapping
import time

from backend.service.application.errors import ServiceConfigurationError


BASE_CONVERSION_TIMEOUT_SECONDS = 7200.0
TENSORRT_CONVERSION_TIMEOUT_SECONDS = 10800.0
CONVERSION_DEADLINE_POLICY_SOURCE = "conversion-task-spec.v1"


@dataclass(frozen=True)
class ConversionDeadlinePolicy:
    """描述由不可变 Task spec 解析出的总时限。"""

    timeout_seconds: float
    target_formats: tuple[str, ...]
    applied_override: str
    policy_source: str = CONVERSION_DEADLINE_POLICY_SOURCE

    def to_attempt_metadata(self, *, started_at: str) -> dict[str, object]:
        """生成首次 claim 原子写入 Attempt 的 metadata。"""

        started = _parse_utc_datetime(started_at, field_name="started_at")
        deadline_at = started + timedelta(seconds=self.timeout_seconds)
        return {
            "deadline_at": deadline_at.isoformat().replace("+00:00", "Z"),
            "timeout_seconds": self.timeout_seconds,
            "timeout_policy_source": self.policy_source,
            "timeout_target_formats": list(self.target_formats),
            "timeout_applied_override": self.applied_override,
        }


class ConversionCancellationProbe:
    """以固定间隔读取权威 Task 状态，避免 supervisor 热轮询数据库。"""

    def __init__(self, *, task_service: object, task_id: str, poll_seconds: float = 1.0) -> None:
        """初始化 Attempt 级取消探针。"""

        self.task_service = task_service
        self.task_id = task_id
        self.poll_seconds = max(0.05, float(poll_seconds))
        self._next_poll_monotonic = 0.0
        self._cancelled = False

    def __call__(self) -> bool:
        """到达轮询时间时刷新状态，其他调用只返回缓存值。"""

        if self._cancelled:
            return True
        now = time.monotonic()
        if now < self._next_poll_monotonic:
            return False
        self._next_poll_monotonic = now + self.poll_seconds
        detail = self.task_service.get_task(self.task_id)
        self._cancelled = detail.task.state == "cancelled"
        return self._cancelled


def resolve_conversion_deadline_policy(
    task_spec: Mapping[str, object],
) -> ConversionDeadlinePolicy:
    """只从 Task 中固化的 conversion spec 解析总时限。"""

    raw_formats = task_spec.get("target_formats")
    if not isinstance(raw_formats, list | tuple):
        raise ServiceConfigurationError("Conversion Task spec 缺少 target_formats")
    normalized: list[str] = []
    for raw_format in raw_formats:
        if not isinstance(raw_format, str) or not raw_format.strip():
            raise ServiceConfigurationError(
                "Conversion Task spec 的 target_formats 无效"
            )
        value = raw_format.strip().lower()
        if value not in normalized:
            normalized.append(value)
    if not normalized:
        raise ServiceConfigurationError("Conversion Task spec 的 target_formats 不能为空")
    has_tensorrt = "tensorrt-engine" in normalized
    return ConversionDeadlinePolicy(
        timeout_seconds=(
            TENSORRT_CONVERSION_TIMEOUT_SECONDS
            if has_tensorrt
            else BASE_CONVERSION_TIMEOUT_SECONDS
        ),
        target_formats=tuple(normalized),
        applied_override="tensorrt" if has_tensorrt else "base",
    )


def validate_conversion_attempt_deadline_metadata(
    metadata: Mapping[str, object],
) -> dict[str, object]:
    """严格读取已固化的 Attempt deadline，不生成新预算。"""

    deadline_at = metadata.get("deadline_at")
    timeout_seconds = metadata.get("timeout_seconds")
    policy_source = metadata.get("timeout_policy_source")
    raw_formats = metadata.get("timeout_target_formats")
    applied_override = metadata.get("timeout_applied_override")
    if not isinstance(deadline_at, str) or not deadline_at.strip():
        raise ServiceConfigurationError("Conversion Attempt 缺少 deadline_at")
    _parse_utc_datetime(deadline_at, field_name="deadline_at")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int | float)
        or float(timeout_seconds) <= 0
    ):
        raise ServiceConfigurationError("Conversion Attempt 的 timeout_seconds 无效")
    if policy_source != CONVERSION_DEADLINE_POLICY_SOURCE:
        raise ServiceConfigurationError("Conversion Attempt 的 timeout policy source 无效")
    if not isinstance(raw_formats, list) or not raw_formats or not all(
        isinstance(item, str) and item.strip() for item in raw_formats
    ):
        raise ServiceConfigurationError("Conversion Attempt 的 target formats 无效")
    if applied_override not in {"base", "tensorrt"}:
        raise ServiceConfigurationError("Conversion Attempt 的 timeout override 无效")
    return {
        "deadline_at": deadline_at,
        "timeout_seconds": float(timeout_seconds),
        "timeout_policy_source": policy_source,
        "timeout_target_formats": list(raw_formats),
        "timeout_applied_override": applied_override,
    }


def validate_queue_conversion_target_formats(
    *,
    policy: ConversionDeadlinePolicy,
    queue_metadata: Mapping[str, object] | None,
) -> None:
    """如 Queue 携带格式快照，仅作一致性交叉校验。"""

    if queue_metadata is None or "target_formats" not in queue_metadata:
        return
    raw_formats = queue_metadata.get("target_formats")
    if not isinstance(raw_formats, list | tuple) or not all(
        isinstance(item, str) and item.strip() for item in raw_formats
    ):
        raise ServiceConfigurationError("Conversion Queue metadata 的 target_formats 无效")
    normalized = tuple(dict.fromkeys(str(item).strip().lower() for item in raw_formats))
    if normalized != policy.target_formats:
        raise ServiceConfigurationError(
            "Conversion Queue metadata 与 Task spec 不一致",
            details={
                "task_target_formats": list(policy.target_formats),
                "queue_target_formats": list(normalized),
            },
        )


def _parse_utc_datetime(value: str, *, field_name: str) -> datetime:
    """解析并校验带时区时间。"""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ServiceConfigurationError(f"{field_name} 不是合法 ISO 时间") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ServiceConfigurationError(f"{field_name} 必须包含时区")
    return parsed.astimezone(UTC)


__all__ = [
    "BASE_CONVERSION_TIMEOUT_SECONDS",
    "CONVERSION_DEADLINE_POLICY_SOURCE",
    "ConversionCancellationProbe",
    "ConversionDeadlinePolicy",
    "TENSORRT_CONVERSION_TIMEOUT_SECONDS",
    "resolve_conversion_deadline_policy",
    "validate_conversion_attempt_deadline_metadata",
    "validate_queue_conversion_target_formats",
]
