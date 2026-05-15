"""服务内事件总线定义。"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ServiceEvent:
    """描述一条服务内统一事件。

    字段：
    - stream：事件流名称，例如 tasks.events。
    - resource_kind：资源类型，例如 task。
    - resource_id：资源 id。
    - event_type：事件类型。
    - event_version：事件版本。
    - occurred_at：事件发生时间。
    - cursor：恢复游标。
    - payload：结构化事件正文。
    """

    stream: str
    resource_kind: str
    resource_id: str
    event_type: str
    event_version: str = "v1"
    occurred_at: str = ""
    cursor: str | None = None
    payload: dict[str, object] = field(default_factory=dict)


class ServiceEventSubscription:
    """描述一条服务内事件订阅。"""

    def __init__(
        self,
        *,
        event_bus: InMemoryServiceEventBus,
        stream: str,
        resource_id: str,
        queue_size: int,
    ) -> None:
        """初始化服务内事件订阅。

        参数：
        - event_bus：所属事件总线。
        - stream：订阅的事件流名称。
        - resource_id：订阅的资源 id。
        - queue_size：单订阅缓冲大小。
        """

        self.event_bus = event_bus
        self.stream = stream
        self.resource_id = resource_id
        self.queue_size = queue_size
        self._loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue[ServiceEvent] = asyncio.Queue(maxsize=queue_size)
        self._overflowed = False
        self._closed = False

    async def receive(self, timeout_seconds: float | None = None) -> ServiceEvent | None:
        """等待接收一条事件。

        参数：
        - timeout_seconds：最长等待秒数；为空时一直等待。

        返回：
        - 收到的事件；超时时返回 None。
        """

        if timeout_seconds is None:
            return await self._queue.get()
        try:
            return await asyncio.wait_for(self._queue.get(), timeout_seconds)
        except asyncio.TimeoutError:
            return None

    def consume_overflowed(self) -> bool:
        """读取并清空缓冲溢出标记。

        返回：
        - 若订阅缓冲已满过则返回 True。
        """

        overflowed = self._overflowed
        self._overflowed = False
        return overflowed

    def close(self) -> None:
        """关闭当前订阅并从事件总线注销。"""

        if self._closed:
            return
        self._closed = True
        self.event_bus.unsubscribe(self)

    def matches(self, event: ServiceEvent) -> bool:
        """判断事件是否命中当前订阅。

        参数：
        - event：待匹配的服务内事件。

        返回：
        - 命中订阅范围时返回 True。
        """

        return event.stream == self.stream and event.resource_id == self.resource_id

    def deliver(self, event: ServiceEvent) -> None:
        """向当前订阅投递一条事件。

        参数：
        - event：待投递的服务内事件。
        """

        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._overflowed = True

    def dispatch(self, event: ServiceEvent) -> None:
        """把事件调度到订阅所属事件循环。

        参数：
        - event：待投递的服务内事件。
        """

        if self._closed:
            return
        self._loop.call_soon_threadsafe(self.deliver, event)


class InMemoryServiceEventBus:
    """提供进程内统一实时事件分发。"""

    def __init__(self) -> None:
        """初始化服务内事件总线。"""

        self._lock = threading.Lock()
        self._subscriptions: set[ServiceEventSubscription] = set()

    def subscribe(
        self,
        *,
        stream: str,
        resource_id: str,
        queue_size: int = 256,
    ) -> ServiceEventSubscription:
        """注册一条事件订阅。

        参数：
        - stream：要订阅的事件流名称。
        - resource_id：要订阅的资源 id。
        - queue_size：单订阅缓冲大小。

        返回：
        - 创建好的订阅对象。
        """

        subscription = ServiceEventSubscription(
            event_bus=self,
            stream=stream,
            resource_id=resource_id,
            queue_size=queue_size,
        )
        with self._lock:
            self._subscriptions.add(subscription)
        return subscription

    def unsubscribe(self, subscription: ServiceEventSubscription) -> None:
        """移除一条订阅。

        参数：
        - subscription：要移除的订阅对象。
        """

        with self._lock:
            self._subscriptions.discard(subscription)

    def publish(self, event: ServiceEvent) -> None:
        """发布一条服务内事件。

        参数：
        - event：要发布的事件对象。
        """

        with self._lock:
            subscriptions = tuple(
                subscription
                for subscription in self._subscriptions
                if subscription.matches(event)
            )

        for subscription in subscriptions:
            subscription.dispatch(event)
