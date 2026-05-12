"""LocalBufferBroker 进程监督器。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from multiprocessing.queues import Queue
from queue import Empty
from threading import Event, Lock, Thread
from typing import Any
from uuid import uuid4
import multiprocessing

from backend.contracts.buffers import BufferRef, FrameRef
from backend.service.application.errors import OperationTimeoutError, ServiceConfigurationError
from backend.service.application.local_buffers.broker_settings import LocalBufferBrokerSettings
from backend.service.application.local_buffers.local_buffer_broker_process import run_local_buffer_broker_process
from backend.service.application.local_buffers.local_buffer_client import (
    LocalBufferBrokerClient,
    LocalBufferBrokerEventChannel,
)
from backend.service.infrastructure.local_buffers import MmapBufferWriteResult


@dataclass
class _LocalBufferBrokerClientRoute:
    """描述一个已注册到 router 的 broker client channel。

    字段：
    - channel_id：客户端通道 id。
    - request_queue：客户端请求队列。
    - response_queue：客户端响应队列。
    - forward_thread：把客户端请求转发给 broker 进程的线程。
    """

    channel_id: str
    request_queue: Any
    response_queue: Any
    forward_thread: Thread


@dataclass(frozen=True)
class _LocalBufferBrokerResponseRoute:
    """描述一条等待 broker 响应的请求路由。

    字段：
    - channel_id：发起请求的客户端通道 id。
    - response_queue：该请求应返回到的客户端响应队列。
    """

    channel_id: str
    response_queue: Any


class _LocalBufferBrokerEventRouter:
    """在父进程内为每个 broker client 隔离响应队列。"""

    def __init__(
        self,
        *,
        context: Any,
        broker_request_queue: Any,
        broker_response_queue: Any,
        request_timeout_seconds: float,
    ) -> None:
        """初始化 broker 事件 router。

        参数：
        - context：用于创建跨进程队列的 multiprocessing context。
        - broker_request_queue：broker process 接收状态事件的队列。
        - broker_response_queue：broker process 返回状态事件结果的队列。
        - request_timeout_seconds：透传给 client 的请求超时时间。
        """

        self._context = context
        self._broker_request_queue = broker_request_queue
        self._broker_response_queue = broker_response_queue
        self._request_timeout_seconds = request_timeout_seconds
        self._stop_event = Event()
        self._lock = Lock()
        self._client_routes: dict[str, _LocalBufferBrokerClientRoute] = {}
        self._response_routes: dict[str, _LocalBufferBrokerResponseRoute] = {}
        self._response_thread: Thread | None = None

    def start(self) -> None:
        """启动 broker 响应分发线程。"""

        if self._response_thread is not None and self._response_thread.is_alive():
            return
        self._stop_event.clear()
        self._response_thread = Thread(
            target=self._route_broker_responses,
            name="local-buffer-broker-response-router",
            daemon=True,
        )
        self._response_thread.start()

    def stop(self) -> None:
        """停止 router 并关闭全部客户端通道。"""

        self._stop_event.set()
        with self._lock:
            routes = tuple(self._client_routes.values())
        for route in routes:
            _safe_put(
                route.request_queue,
                {
                    "request_id": f"router-stop-{uuid4().hex}",
                    "action": "__close-client-channel__",
                    "payload": {"channel_id": route.channel_id},
                },
            )
        for route in routes:
            route.forward_thread.join(timeout=1.0)
        response_thread = self._response_thread
        if response_thread is not None:
            response_thread.join(timeout=1.0)
        with self._lock:
            self._client_routes.clear()
            self._response_routes.clear()
        self._response_thread = None

    def create_event_channel(self) -> LocalBufferBrokerEventChannel:
        """创建一个响应隔离的客户端事件通道。"""

        channel_id = f"broker-channel-{uuid4().hex}"
        request_queue = self._context.Queue()
        response_queue = self._context.Queue()
        forward_thread = Thread(
            target=self._forward_client_requests,
            args=(channel_id, request_queue, response_queue),
            name=f"local-buffer-broker-client-router-{channel_id}",
            daemon=True,
        )
        with self._lock:
            self._client_routes[channel_id] = _LocalBufferBrokerClientRoute(
                channel_id=channel_id,
                request_queue=request_queue,
                response_queue=response_queue,
                forward_thread=forward_thread,
            )
        forward_thread.start()
        return LocalBufferBrokerEventChannel(
            request_queue=request_queue,
            response_queue=response_queue,
            request_timeout_seconds=self._request_timeout_seconds,
            channel_id=channel_id,
        )

    def _forward_client_requests(self, channel_id: str, request_queue: Any, response_queue: Any) -> None:
        """把单个客户端通道的请求转发给 broker 进程。"""

        try:
            while not self._stop_event.is_set():
                try:
                    message = request_queue.get(timeout=0.1)
                except Empty:
                    continue
                if not isinstance(message, dict):
                    continue
                action = str(message.get("action") or "")
                if action == "__close-client-channel__":
                    break
                request_id = str(message.get("request_id") or f"broker-{uuid4().hex}")
                message["request_id"] = request_id
                with self._lock:
                    self._response_routes[request_id] = _LocalBufferBrokerResponseRoute(
                        channel_id=channel_id,
                        response_queue=response_queue,
                    )
                try:
                    self._broker_request_queue.put(message)
                except Exception as exc:
                    with self._lock:
                        self._response_routes.pop(request_id, None)
                    response_queue.put(
                        {
                            "request_id": request_id,
                            "ok": False,
                            "error": {
                                "code": "service_configuration_error",
                                "message": "LocalBufferBroker router 转发请求失败",
                                "details": {
                                    "channel_id": channel_id,
                                    "error_type": type(exc).__name__,
                                    "error_message": str(exc) or type(exc).__name__,
                                },
                            },
                        }
                    )
        finally:
            self._remove_client_route(channel_id)
            _close_queue(request_queue)
            _close_queue(response_queue)

    def _route_broker_responses(self) -> None:
        """把 broker 进程响应分发回对应客户端响应队列。"""

        while not self._stop_event.is_set():
            try:
                message = self._broker_response_queue.get(timeout=0.1)
            except Empty:
                continue
            if not isinstance(message, dict):
                continue
            request_id = str(message.get("request_id") or "")
            with self._lock:
                response_route = self._response_routes.pop(request_id, None)
            if response_route is None:
                continue
            response_route.response_queue.put(message)

    def _remove_client_route(self, channel_id: str) -> None:
        """移除一个客户端通道及其未完成响应路由。"""

        with self._lock:
            self._client_routes.pop(channel_id, None)
            stale_request_ids = [
                request_id
                for request_id, response_route in self._response_routes.items()
                if response_route.channel_id == channel_id
            ]
            for request_id in stale_request_ids:
                self._response_routes.pop(request_id, None)


class LocalBufferBrokerProcessSupervisor:
    """管理本机 LocalBufferBroker companion process。"""

    def __init__(self, *, settings: LocalBufferBrokerSettings) -> None:
        """初始化 broker 进程监督器。

        参数：
        - settings：broker 进程启动配置。
        """

        self.settings = settings
        self._context = multiprocessing.get_context("spawn")
        self._process: Any | None = None
        self._startup_queue: Queue[Any] | None = None
        self._request_queue: Queue[Any] | None = None
        self._response_queue: Queue[Any] | None = None
        self._router: _LocalBufferBrokerEventRouter | None = None
        self._expire_stop_event = Event()
        self._expire_thread: Thread | None = None
        self._recent_error: dict[str, object] | None = None
        self._lock = Lock()

    @property
    def is_running(self) -> bool:
        """返回 broker 进程当前是否存活。"""

        process = self._process
        return process is not None and process.is_alive()

    def start(self) -> None:
        """启动 broker companion process。"""

        if not self.settings.enabled:
            return
        with self._lock:
            if self.is_running:
                return
            startup_queue = self._context.Queue()
            request_queue = self._context.Queue()
            response_queue = self._context.Queue()
            process = self._context.Process(
                target=run_local_buffer_broker_process,
                kwargs={
                    "settings_payload": self.settings.model_dump(mode="python"),
                    "startup_queue": startup_queue,
                    "request_queue": request_queue,
                    "response_queue": response_queue,
                },
                name="local-buffer-broker",
                daemon=False,
            )
            process.start()
            self._process = process
            self._startup_queue = startup_queue
            self._request_queue = request_queue
            self._response_queue = response_queue

        try:
            message = startup_queue.get(timeout=max(0.1, self.settings.startup_timeout_seconds))
        except Empty as exc:
            self.stop()
            raise OperationTimeoutError(
                "等待 LocalBufferBroker 启动超时",
                details={"timeout_seconds": self.settings.startup_timeout_seconds},
            ) from exc

        if not isinstance(message, dict) or message.get("ok") is not True:
            self.stop()
            error_payload = message.get("error") if isinstance(message, dict) and isinstance(message.get("error"), dict) else {}
            raise ServiceConfigurationError(
                str(error_payload.get("message") or "LocalBufferBroker 启动失败"),
                details=error_payload.get("details") if isinstance(error_payload.get("details"), dict) else {},
            )
        router = _LocalBufferBrokerEventRouter(
            context=self._context,
            broker_request_queue=request_queue,
            broker_response_queue=response_queue,
            request_timeout_seconds=self.settings.request_timeout_seconds,
        )
        router.start()
        with self._lock:
            self._router = router
        self._clear_recent_error()
        self._start_expire_loop()

    def stop(self) -> None:
        """停止 broker companion process。"""

        self._stop_expire_loop()
        with self._lock:
            process = self._process
            router = self._router
        if process is not None and process.is_alive() and router is not None:
            client = self.create_client()
            try:
                if client is not None:
                    client.shutdown()
            except Exception:
                pass
            finally:
                if client is not None:
                    client.close()
            process.join(timeout=max(0.1, self.settings.shutdown_timeout_seconds))
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=max(0.1, self.settings.shutdown_timeout_seconds))
        if router is not None:
            router.stop()
        with self._lock:
            self._cleanup_startup_queue_locked()
            self._cleanup_event_queues_locked()
            self._process = None
            self._router = None

    def get_event_channel(self) -> LocalBufferBrokerEventChannel | None:
        """返回当前 broker event channel。"""

        with self._lock:
            if self._process is None or not self._process.is_alive():
                return None
            router = self._router
        if router is None:
            return None
        return router.create_event_channel()

    def create_client(self) -> LocalBufferBrokerClient | None:
        """创建一个当前 broker 的 client。"""

        event_channel = self.get_event_channel()
        if event_channel is None:
            return None
        return LocalBufferBrokerClient(event_channel)

    def get_status(self) -> dict[str, object]:
        """读取 broker 状态摘要。"""

        client = self.create_client()
        if client is None:
            return {"state": "stopped"}
        try:
            status = client.get_status()
            return status
        except Exception as exc:
            self._record_recent_error(action="status", error=exc)
            raise
        finally:
            client.close()

    def get_health_summary(self) -> dict[str, object]:
        """返回适合 REST health 暴露的 broker 健康摘要。

        返回：
        - dict[str, object]：包含启用状态、进程状态、broker status 和最近错误的摘要。
        """

        if not self.settings.enabled:
            return {
                "enabled": False,
                "state": "disabled",
                "running": False,
                "recent_error": self.get_recent_error(),
            }
        try:
            status = self.get_status()
            return {
                "enabled": True,
                "state": str(status.get("state") or "unknown"),
                "running": self.is_running,
                "status": status,
                "recent_error": self.get_recent_error(),
                "expire_loop_running": self._is_expire_loop_running(),
                "expire_interval_seconds": self.settings.expire_interval_seconds,
            }
        except Exception as exc:
            self._record_recent_error(action="health", error=exc)
            return {
                "enabled": True,
                "state": "error" if self.is_running else "stopped",
                "running": self.is_running,
                "recent_error": self.get_recent_error(),
                "expire_loop_running": self._is_expire_loop_running(),
                "expire_interval_seconds": self.settings.expire_interval_seconds,
            }

    def get_recent_error(self) -> dict[str, object] | None:
        """返回最近一次 broker 控制错误。"""

        with self._lock:
            return dict(self._recent_error) if self._recent_error is not None else None

    def write_bytes(
        self,
        *,
        content: bytes,
        owner_kind: str,
        owner_id: str,
        media_type: str,
        pool_name: str | None = None,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        ttl_seconds: float | None = None,
        trace_id: str | None = None,
    ) -> MmapBufferWriteResult:
        """写入 bytes 并返回可跨进程传递的 BufferRef。"""

        client = self._require_client()
        try:
            result = client.write_bytes(
                content=content,
                owner_kind=owner_kind,
                owner_id=owner_id,
                media_type=media_type,
                pool_name=pool_name,
                shape=shape,
                dtype=dtype,
                layout=layout,
                pixel_format=pixel_format,
                ttl_seconds=ttl_seconds,
                trace_id=trace_id,
            )
            return result
        except Exception as exc:
            self._record_recent_error(action="write-bytes", error=exc)
            raise
        finally:
            client.close()

    def read_buffer_ref(self, buffer_ref: BufferRef) -> bytes:
        """读取普通 BufferRef 对应的字节。"""

        client = self._require_client()
        try:
            content = client.read_buffer_ref(buffer_ref)
            return content
        except Exception as exc:
            self._record_recent_error(action="read-buffer-ref", error=exc)
            raise
        finally:
            client.close()

    def create_frame_channel(
        self,
        *,
        stream_id: str,
        frame_capacity: int,
        pool_name: str | None = None,
    ) -> dict[str, object]:
        """创建一个 ring buffer frame channel。

        参数：
        - stream_id：连续帧来源 id。
        - frame_capacity：预留帧槽位数量。
        - pool_name：目标 pool 名称；未提供时使用默认 pool。

        返回：
        - dict[str, object]：channel 状态摘要。
        """

        client = self._require_client()
        try:
            return client.create_frame_channel(
                stream_id=stream_id,
                frame_capacity=frame_capacity,
                pool_name=pool_name,
            )
        except Exception as exc:
            self._record_recent_error(action="create-frame-channel", error=exc)
            raise
        finally:
            client.close()

    def write_frame(
        self,
        *,
        stream_id: str,
        content: bytes,
        media_type: str,
        pool_name: str | None = None,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> FrameRef:
        """写入一帧并返回 FrameRef。

        参数：
        - stream_id：连续帧来源 id。
        - content：当前帧字节内容。
        - media_type：当前帧媒体类型。
        - pool_name：目标 pool 名称；未提供时使用默认 pool。
        - shape：raw 图像或 tensor 形状。
        - dtype：raw 数据类型。
        - layout：raw 数据布局。
        - pixel_format：像素格式。
        - metadata：附加元数据。

        返回：
        - FrameRef：当前帧引用。
        """

        client = self._require_client()
        try:
            return client.write_frame(
                stream_id=stream_id,
                content=content,
                media_type=media_type,
                pool_name=pool_name,
                shape=shape,
                dtype=dtype,
                layout=layout,
                pixel_format=pixel_format,
                metadata=metadata,
            )
        except Exception as exc:
            self._record_recent_error(action="write-frame", error=exc)
            raise
        finally:
            client.close()

    def read_frame_ref(self, frame_ref: FrameRef) -> bytes:
        """读取 FrameRef 对应的帧字节。"""

        client = self._require_client()
        try:
            content = client.read_frame_ref(frame_ref)
            return content
        except Exception as exc:
            self._record_recent_error(action="read-frame-ref", error=exc)
            raise
        finally:
            client.close()

    def release(self, lease_id: str, *, pool_name: str | None = None) -> None:
        """释放一条 broker lease。"""

        client = self._require_client()
        try:
            client.release(lease_id, pool_name=pool_name)
        except Exception as exc:
            self._record_recent_error(action="release", error=exc)
            raise
        finally:
            client.close()

    def release_owner(
        self,
        *,
        owner_kind: str | None = None,
        owner_id: str | None = None,
        owner_id_prefix: str | None = None,
        pool_name: str | None = None,
    ) -> int:
        """释放指定 owner 匹配的全部 broker lease。

        参数：
        - owner_kind：可选 owner 类型过滤条件。
        - owner_id：可选 owner id 精确匹配条件。
        - owner_id_prefix：可选 owner id 前缀匹配条件。
        - pool_name：可选的目标 pool 名称。

        返回：
        - int：本次释放的 lease 数量。
        """

        client = self._require_client()
        try:
            released_count = client.release_owner(
                owner_kind=owner_kind,
                owner_id=owner_id,
                owner_id_prefix=owner_id_prefix,
                pool_name=pool_name,
            )
            return released_count
        except Exception as exc:
            self._record_recent_error(action="release-owner", error=exc)
            raise
        finally:
            client.close()

    def expire_leases(self, *, pool_name: str | None = None) -> int:
        """触发 broker 回收已经过期的 lease。

        参数：
        - pool_name：可选的目标 pool 名称。

        返回：
        - int：本次回收的 lease 数量。
        """

        client = self._require_client()
        try:
            expired_count = client.expire_leases(pool_name=pool_name)
            return expired_count
        except Exception as exc:
            self._record_recent_error(action="expire-leases", error=exc)
            raise
        finally:
            client.close()

    def _start_expire_loop(self) -> None:
        """启动周期性过期 lease 回收线程。"""

        interval_seconds = float(self.settings.expire_interval_seconds)
        if interval_seconds <= 0:
            return
        with self._lock:
            if self._expire_thread is not None and self._expire_thread.is_alive():
                return
            self._expire_stop_event.clear()
            self._expire_thread = Thread(
                target=self._run_expire_loop,
                name="local-buffer-broker-expire-loop",
                daemon=True,
            )
            self._expire_thread.start()

    def _stop_expire_loop(self) -> None:
        """停止周期性过期 lease 回收线程。"""

        self._expire_stop_event.set()
        with self._lock:
            expire_thread = self._expire_thread
        if expire_thread is not None:
            expire_thread.join(timeout=1.0)
        with self._lock:
            self._expire_thread = None

    def _run_expire_loop(self) -> None:
        """定期触发 broker expire-leases 控制动作。"""

        interval_seconds = max(0.1, float(self.settings.expire_interval_seconds))
        while not self._expire_stop_event.wait(interval_seconds):
            if not self.is_running:
                continue
            try:
                self.expire_leases()
            except Exception as exc:  # pragma: no cover - 后台线程错误由 health recent_error 暴露
                self._record_recent_error(action="expire-loop", error=exc)

    def _is_expire_loop_running(self) -> bool:
        """返回周期性 expire loop 是否存活。"""

        with self._lock:
            expire_thread = self._expire_thread
        return expire_thread is not None and expire_thread.is_alive()

    def _record_recent_error(self, *, action: str, error: Exception) -> None:
        """记录最近一次 broker 控制错误。"""

        details = getattr(error, "details", None)
        error_payload = {
            "action": action,
            "error_type": type(error).__name__,
            "message": getattr(error, "message", str(error) or type(error).__name__),
            "code": getattr(error, "code", "service_configuration_error"),
            "details": dict(details) if isinstance(details, dict) else {},
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._recent_error = error_payload

    def _clear_recent_error(self) -> None:
        """清除最近一次 broker 控制错误。"""

        with self._lock:
            self._recent_error = None

    def _require_client(self) -> LocalBufferBrokerClient:
        """返回已启动 broker 的 client。"""

        client = self.create_client()
        if client is None:
            raise ServiceConfigurationError("LocalBufferBroker 当前未启动")
        return client

    def _cleanup_startup_queue_locked(self) -> None:
        """关闭启动队列。"""

        startup_queue = self._startup_queue
        self._startup_queue = None
        if startup_queue is None:
            return
        startup_queue.close()
        startup_queue.join_thread()

    def _cleanup_event_queues_locked(self) -> None:
        """关闭 broker 事件队列。"""

        request_queue = self._request_queue
        response_queue = self._response_queue
        self._request_queue = None
        self._response_queue = None
        for queue in (request_queue, response_queue):
            if queue is None:
                continue
            queue.close()
            queue.join_thread()


def _safe_put(queue: Any, message: dict[str, object]) -> None:
    """向队列发送消息并忽略关闭期错误。"""

    try:
        queue.put(message)
    except Exception:
        pass


def _close_queue(queue: Any) -> None:
    """关闭 multiprocessing queue 并忽略重复关闭错误。"""

    try:
        queue.close()
        queue.join_thread()
    except Exception:
        pass