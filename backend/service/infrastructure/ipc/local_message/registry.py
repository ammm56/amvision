"""独立 LocalMessage endpoints 的进程内 health registry。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Literal

from backend.service.infrastructure.ipc.local_message.health import (
    EventChannelHealth,
    LocalMessageChannelHealthEnvelope,
    RpcChannelHealth,
)


ChannelKind = Literal["rpc", "event"]
HealthValue = RpcChannelHealth | EventChannelHealth


@dataclass(frozen=True, slots=True)
class _Registration:
    """保存一个 endpoint 的类型、profile 和只读 health provider。"""

    channel_name: str
    channel_kind: ChannelKind
    profile_id: str
    health_provider: Callable[[], HealthValue]


class LocalMessageChannelRegistry:
    """不拥有 endpoint 生命周期的分类型 health registry。"""

    def __init__(self) -> None:
        """初始化空 registry。"""

        self._registrations: dict[str, _Registration] = {}
        self._lock = Lock()

    def register(
        self,
        *,
        channel_name: str,
        channel_kind: ChannelKind,
        profile_id: str,
        health_provider: Callable[[], HealthValue],
    ) -> None:
        """登记唯一 Channel；不启动或关闭 endpoint。"""

        normalized_name = channel_name.strip()
        if not normalized_name or not profile_id.strip():
            raise ValueError("Channel name/profile id 不能为空")
        registration = _Registration(
            channel_name=normalized_name,
            channel_kind=channel_kind,
            profile_id=profile_id,
            health_provider=health_provider,
        )
        with self._lock:
            if normalized_name in self._registrations:
                raise ValueError(f"LocalMessage Channel 已登记: {normalized_name}")
            self._registrations[normalized_name] = registration

    def unregister(self, channel_name: str) -> None:
        """幂等移除 registry 引用，不关闭 endpoint。"""

        with self._lock:
            self._registrations.pop(channel_name, None)

    def snapshot(self) -> tuple[LocalMessageChannelHealthEnvelope, ...]:
        """返回按名称排序、RPC/Event 指标互斥的 health 快照。"""

        with self._lock:
            registrations = tuple(self._registrations.values())
        envelopes: list[LocalMessageChannelHealthEnvelope] = []
        for registration in sorted(
            registrations, key=lambda item: item.channel_name
        ):
            health = registration.health_provider()
            if registration.channel_kind == "rpc":
                if not isinstance(health, RpcChannelHealth):
                    raise TypeError("RPC registry provider 返回了非 RPC health")
                envelopes.append(
                    LocalMessageChannelHealthEnvelope(
                        channel_name=registration.channel_name,
                        channel_kind="rpc",
                        transport="mmap",
                        profile_id=registration.profile_id,
                        rpc=health,
                    )
                )
            else:
                if not isinstance(health, EventChannelHealth):
                    raise TypeError("Event registry provider 返回了非 Event health")
                envelopes.append(
                    LocalMessageChannelHealthEnvelope(
                        channel_name=registration.channel_name,
                        channel_kind="event",
                        transport="mmap",
                        profile_id=registration.profile_id,
                        event=health,
                    )
                )
        return tuple(envelopes)
