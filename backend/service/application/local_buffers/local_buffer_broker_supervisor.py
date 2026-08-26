"""LocalBufferBroker 进程监督器。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from multiprocessing.connection import Connection
from multiprocessing.queues import Queue
from pathlib import Path
from queue import Empty, Queue as ThreadQueue
from threading import Event, Lock, RLock, Thread
from time import monotonic, sleep
from typing import Any
from uuid import uuid4
import logging
import multiprocessing

from backend.contracts.buffers import BufferLease, BufferRef, FrameRef
from backend.service.application.errors import (
    OperationTimeoutError,
    ServiceConfigurationError,
)
from backend.service.application.local_buffers.backend_service_process_takeover import (
    take_over_backend_service_owner,
)
from backend.service.application.local_buffers.broker_settings import (
    LocalBufferBrokerSettings,
)
from backend.service.application.local_buffers.local_buffer_broker_process import (
    run_local_buffer_broker_process,
)
from backend.service.application.local_buffers.local_buffer_client import (
    LocalBufferBrokerClient,
    LocalBufferBrokerEventChannel,
)
from backend.service.application.runtime.support.safe_counter import (
    SafeCounterState,
    increment_safe_counter,
    snapshot_safe_counter,
)
from backend.service.infrastructure.local_buffers import LocalBufferWriteResult


logger = logging.getLogger(__name__)


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
    forward_thread: Thread | None


@dataclass(frozen=True)
class _LocalBufferBrokerResponseRoute:
    """描述一条等待 broker 响应的请求路由。

    字段：
    - channel_id：发起请求的客户端通道 id。
    - response_queue：该请求应返回到的客户端响应队列。
    """

    channel_id: str
    response_queue: Any


class _LocalBufferBrokerDirectRequestQueue:
    """为同进程 client 提供与 Queue.put 一致的直达 Broker 入口。"""

    def __init__(
        self,
        *,
        router: "_LocalBufferBrokerEventRouter",
        channel_id: str,
        response_queue: Any,
    ) -> None:
        self._router = router
        self._channel_id = channel_id
        self._response_queue = response_queue

    def put(self, message: object) -> None:
        """登记响应路由后直接写入 Broker request connection。"""

        self._router.submit_local_request(
            channel_id=self._channel_id,
            response_queue=self._response_queue,
            message=message,
        )


class _LocalBufferBrokerEventRouter:
    """在父进程内为每个 broker client 隔离响应队列。"""

    def __init__(
        self,
        *,
        context: Any,
        broker_request_connection: Connection,
        broker_response_connection: Connection,
        request_timeout_seconds: float,
    ) -> None:
        """初始化 broker 事件 router。

        参数：
        - context：用于创建跨进程队列的 multiprocessing context。
        - broker_request_connection：向 broker process 发送状态事件的单向连接。
        - broker_response_connection：接收 broker process 状态事件结果的单向连接。
        - request_timeout_seconds：透传给 client 的请求超时时间。
        """

        self._context = context
        self._broker_request_connection = broker_request_connection
        self._broker_response_connection = broker_response_connection
        self._broker_send_lock = Lock()
        self._request_timeout_seconds = request_timeout_seconds
        self._stop_event = Event()
        self._lock = Lock()
        self._client_routes: dict[str, _LocalBufferBrokerClientRoute] = {}
        self._response_routes: dict[str, _LocalBufferBrokerResponseRoute] = {}
        self._response_thread: Thread | None = None
        self._forward_error_count = SafeCounterState()
        self._dropped_response_count = SafeCounterState()
        self._closed_channel_count = SafeCounterState()
        self._last_router_error: dict[str, object] | None = None

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
            if route.forward_thread is not None:
                route.forward_thread.join(timeout=1.0)
        response_thread = self._response_thread
        if response_thread is not None:
            response_thread.join(timeout=1.0)
        with self._lock:
            self._client_routes.clear()
            self._response_routes.clear()
        self._response_thread = None

    def describe_state(self) -> dict[str, object]:
        """返回当前 router 的运行时观测摘要。"""

        with self._lock:
            client_channel_ids = sorted(self._client_routes.keys())
            response_thread = self._response_thread
            active_forward_thread_count = sum(
                1
                for route in self._client_routes.values()
                if route.forward_thread is not None
                and route.forward_thread.is_alive()
            )
            closed_channel_snapshot = snapshot_safe_counter(self._closed_channel_count)
            forward_error_snapshot = snapshot_safe_counter(self._forward_error_count)
            dropped_response_snapshot = snapshot_safe_counter(
                self._dropped_response_count
            )
            return {
                "configured": True,
                "response_router_running": response_thread is not None
                and response_thread.is_alive(),
                "active_client_channel_count": len(self._client_routes),
                "pending_response_route_count": len(self._response_routes),
                "active_forward_thread_count": active_forward_thread_count,
                "closed_channel_count": closed_channel_snapshot["value"],
                "closed_channel_count_rollover_count": closed_channel_snapshot[
                    "rollover_count"
                ],
                "forward_error_count": forward_error_snapshot["value"],
                "forward_error_count_rollover_count": forward_error_snapshot[
                    "rollover_count"
                ],
                "dropped_response_count": dropped_response_snapshot["value"],
                "dropped_response_count_rollover_count": dropped_response_snapshot[
                    "rollover_count"
                ],
                "active_client_channel_ids": client_channel_ids[:8],
                "active_client_channel_overflow_count": max(
                    0, len(client_channel_ids) - 8
                ),
                "last_router_error": (
                    dict(self._last_router_error)
                    if self._last_router_error is not None
                    else None
                ),
            }

    def create_event_channel(self) -> LocalBufferBrokerEventChannel:
        """创建可传入 worker 子进程的响应隔离事件通道。"""

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

    def create_local_event_channel(self) -> LocalBufferBrokerEventChannel:
        """创建 backend 同进程 client 直达 Broker request queue 的通道。"""

        channel_id = f"broker-channel-{uuid4().hex}"
        response_queue: ThreadQueue[object] = ThreadQueue()
        request_queue = _LocalBufferBrokerDirectRequestQueue(
            router=self,
            channel_id=channel_id,
            response_queue=response_queue,
        )
        with self._lock:
            self._client_routes[channel_id] = _LocalBufferBrokerClientRoute(
                channel_id=channel_id,
                request_queue=request_queue,
                response_queue=response_queue,
                forward_thread=None,
            )
        return LocalBufferBrokerEventChannel(
            request_queue=request_queue,
            response_queue=response_queue,
            request_timeout_seconds=self._request_timeout_seconds,
            channel_id=channel_id,
        )

    def submit_local_request(
        self,
        *,
        channel_id: str,
        response_queue: Any,
        message: object,
    ) -> None:
        """同步登记响应路由并把同进程 client 请求直接提交给 Broker。"""

        if not isinstance(message, dict):
            return
        action = str(message.get("action") or "")
        if action == "__close-client-channel__":
            self._remove_client_route(channel_id)
            return
        self._submit_client_request(
            channel_id=channel_id,
            response_queue=response_queue,
            message=message,
        )

    def _forward_client_requests(
        self, channel_id: str, request_queue: Any, response_queue: Any
    ) -> None:
        """把单个客户端通道的请求转发给 broker 进程。"""

        try:
            while not self._stop_event.is_set():
                try:
                    message = request_queue.get(timeout=0.1)
                except Empty:
                    continue
                except Exception as exc:
                    self._record_router_error(
                        action="read-client-request", channel_id=channel_id, error=exc
                    )
                    if self._stop_event.is_set():
                        break
                    continue
                if isinstance(message, dict) and str(message.get("action") or "") == "__close-client-channel__":
                    break
                self._submit_client_request(
                    channel_id=channel_id,
                    response_queue=response_queue,
                    message=message,
                )
        finally:
            self._remove_client_route(channel_id)
            _close_queue(request_queue)
            _close_queue(response_queue)

    def _submit_client_request(
        self,
        *,
        channel_id: str,
        response_queue: Any,
        message: object,
    ) -> None:
        """统一登记 request id 的响应路由并投递 Broker 进程。"""

        if not isinstance(message, dict):
            return
        request_id = str(message.get("request_id") or f"broker-{uuid4().hex}")
        message["request_id"] = request_id
        with self._lock:
            if channel_id not in self._client_routes:
                raise ServiceConfigurationError(
                    "LocalBufferBroker client channel 已关闭",
                    details={"channel_id": channel_id},
                )
            self._response_routes[request_id] = _LocalBufferBrokerResponseRoute(
                channel_id=channel_id,
                response_queue=response_queue,
            )
        try:
            # multiprocessing.Connection 不允许多个线程并发写入同一字节流。
            # router 是唯一发送入口，锁只覆盖小型控制消息序列化与发送。
            with self._broker_send_lock:
                self._broker_request_connection.send(message)
        except Exception as exc:
            with self._lock:
                self._response_routes.pop(request_id, None)
                increment_safe_counter(self._forward_error_count)
            self._record_router_error(
                action="forward-request", channel_id=channel_id, error=exc
            )
            _safe_put(
                response_queue,
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
                },
            )

    def _route_broker_responses(self) -> None:
        """把 broker 进程响应分发回对应客户端响应队列。"""

        while not self._stop_event.is_set():
            try:
                if not self._broker_response_connection.poll(0.1):
                    continue
                message = self._broker_response_connection.recv()
            except (EOFError, OSError) as exc:
                self._record_router_error(action="read-broker-response", error=exc)
                break
            if not isinstance(message, dict):
                continue
            request_id = str(message.get("request_id") or "")
            with self._lock:
                response_route = self._response_routes.pop(request_id, None)
            if response_route is None:
                continue
            try:
                response_route.response_queue.put(message)
            except Exception as exc:
                with self._lock:
                    increment_safe_counter(self._dropped_response_count)
                self._record_router_error(
                    action="route-response",
                    channel_id=response_route.channel_id,
                    request_id=request_id,
                    error=exc,
                )

    def _remove_client_route(self, channel_id: str) -> None:
        """移除一个客户端通道及其未完成响应路由。"""

        with self._lock:
            removed_route = self._client_routes.pop(channel_id, None)
            if removed_route is not None:
                increment_safe_counter(self._closed_channel_count)
            stale_request_ids = [
                request_id
                for request_id, response_route in self._response_routes.items()
                if response_route.channel_id == channel_id
            ]
            for request_id in stale_request_ids:
                self._response_routes.pop(request_id, None)

    def _record_router_error(
        self,
        *,
        action: str,
        error: Exception,
        channel_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """记录最近一次 router 运行错误。"""

        payload = {
            "action": action,
            "channel_id": channel_id,
            "request_id": request_id,
            "error_type": type(error).__name__,
            "error_message": str(error) or type(error).__name__,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._last_router_error = payload


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
        self._request_connection: Connection | None = None
        self._response_connection: Connection | None = None
        self._router: _LocalBufferBrokerEventRouter | None = None
        self._expire_stop_event = Event()
        self._expire_thread: Thread | None = None
        self._recent_error: dict[str, object] | None = None
        self._lock = Lock()
        self._direct_io_lock = RLock()
        self._direct_io_client: LocalBufferBrokerClient | None = None

    @property
    def is_running(self) -> bool:
        """返回 broker 进程当前是否存活。"""

        process = self._process
        return process is not None and process.is_alive()

    def start(self) -> None:
        """启动 broker companion process。"""

        if not self.settings.enabled:
            return
        if not self.is_running:
            self._close_direct_io_client()
        timeout_seconds = max(0.1, float(self.settings.startup_timeout_seconds))
        deadline = monotonic() + timeout_seconds
        while True:
            with self._lock:
                if self.is_running:
                    return
                startup_queue = self._context.Queue()
                request_receive_connection, request_send_connection = (
                    self._context.Pipe(duplex=False)
                )
                response_receive_connection, response_send_connection = (
                    self._context.Pipe(duplex=False)
                )
                process = self._context.Process(
                    target=run_local_buffer_broker_process,
                    kwargs={
                        "settings_payload": self.settings.model_dump(mode="python"),
                        "startup_queue": startup_queue,
                        "request_connection": request_receive_connection,
                        "response_connection": response_send_connection,
                    },
                    name="local-buffer-broker",
                    daemon=True,
                )
                process.start()
                # 父进程仅保留 request send 与 response receive 两端，避免连接
                # 因无关句柄仍然打开而无法可靠观察 EOF。
                request_receive_connection.close()
                response_send_connection.close()
                self._process = process
                self._startup_queue = startup_queue
                self._request_connection = request_send_connection
                self._response_connection = response_receive_connection

            message: object | None = None
            while message is None:
                remaining_seconds = deadline - monotonic()
                if remaining_seconds <= 0:
                    process_id = process.pid
                    process_exitcode = process.exitcode
                    self.stop()
                    raise OperationTimeoutError(
                        "等待 LocalBufferBroker 启动超时",
                        details={
                            "timeout_seconds": self.settings.startup_timeout_seconds,
                            "process_id": process_id,
                            "process_exitcode": process_exitcode,
                            "root_dir": self.settings.root_dir,
                            "arena_file": str(
                                Path(self.settings.root_dir)
                                / "local-buffer"
                                / "arena-main.mmap"
                            ),
                        },
                    )
                try:
                    message = startup_queue.get(
                        timeout=min(0.1, max(0.01, remaining_seconds))
                    )
                except Empty:
                    if process.exitcode is None:
                        continue
                    process_id = process.pid
                    process_exitcode = process.exitcode
                    self.stop()
                    raise ServiceConfigurationError(
                        "LocalBufferBroker 子进程在启动完成前退出",
                        details={
                            "process_id": process_id,
                            "process_exitcode": process_exitcode,
                            "root_dir": self.settings.root_dir,
                        },
                    )

            if isinstance(message, dict) and message.get("ok") is True:
                router = _LocalBufferBrokerEventRouter(
                    context=self._context,
                    broker_request_connection=request_send_connection,
                    broker_response_connection=response_receive_connection,
                    request_timeout_seconds=self.settings.request_timeout_seconds,
                )
                router.start()
                with self._lock:
                    self._router = router
                self._clear_recent_error()
                self._start_expire_loop()
                return

            self.stop()
            error_payload = (
                message.get("error")
                if isinstance(message, dict) and isinstance(message.get("error"), dict)
                else {}
            )
            if self._should_take_over_existing_process(error_payload):
                error_details = error_payload.get("details")
                owner_metadata = (
                    error_details.get("owner")
                    if isinstance(error_details, dict)
                    and isinstance(error_details.get("owner"), dict)
                    else {}
                )
                remaining_seconds = deadline - monotonic()
                if remaining_seconds <= 0:
                    raise OperationTimeoutError(
                        "等待接管 LocalBufferBroker 占用进程超时",
                        details={
                            "timeout_seconds": self.settings.startup_timeout_seconds,
                            "root_dir": self.settings.root_dir,
                        },
                    )
                try:
                    takeover_summary = take_over_backend_service_owner(
                        owner_metadata=owner_metadata,
                        root_dir=Path(self.settings.root_dir),
                        timeout_seconds=min(
                            self.settings.takeover_timeout_seconds,
                            remaining_seconds,
                        ),
                    )
                except ServiceConfigurationError as exc:
                    if (
                        exc.details.get("reason") == "owner-exited-during-takeover"
                        and monotonic() < deadline
                    ):
                        sleep(min(0.2, max(0.05, deadline - monotonic())))
                        continue
                    raise
                logger.warning(
                    "已接管旧 backend-service LocalBufferBroker 占用进程：%s",
                    takeover_summary,
                )
                if monotonic() < deadline:
                    sleep(min(0.2, max(0.05, deadline - monotonic())))
                    continue
                raise OperationTimeoutError(
                    "接管旧 backend-service 后等待 LocalBufferBroker 启动超时",
                    details={
                        "timeout_seconds": self.settings.startup_timeout_seconds,
                        "root_dir": self.settings.root_dir,
                    },
                )
            if (
                self._is_retryable_startup_error(error_payload)
                and monotonic() < deadline
            ):
                sleep(min(0.2, max(0.05, deadline - monotonic())))
                continue
            raise ServiceConfigurationError(
                str(error_payload.get("message") or "LocalBufferBroker 启动失败"),
                details=error_payload.get("details")
                if isinstance(error_payload.get("details"), dict)
                else {},
            )

    def stop(self) -> None:
        """停止 broker companion process。"""

        self._stop_expire_loop()
        self._close_direct_io_client()
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
            self._cleanup_event_connections_locked()
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
        channel = router.create_event_channel()
        return LocalBufferBrokerEventChannel(
            request_queue=channel.request_queue,
            response_queue=channel.response_queue,
            request_timeout_seconds=channel.request_timeout_seconds,
            channel_id=channel.channel_id,
            direct_access_settings=self.settings.model_dump(mode="python"),
        )

    def create_client(self) -> LocalBufferBrokerClient | None:
        """创建一个当前 broker 的同进程 client。"""

        with self._lock:
            if self._process is None or not self._process.is_alive():
                return None
            router = self._router
        if router is None:
            return None
        channel = router.create_local_event_channel()
        return LocalBufferBrokerClient(
            LocalBufferBrokerEventChannel(
                request_queue=channel.request_queue,
                response_queue=channel.response_queue,
                request_timeout_seconds=channel.request_timeout_seconds,
                channel_id=channel.channel_id,
                direct_access_settings=self.settings.model_dump(mode="python"),
            )
        )

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
                "router": self._build_router_observation(),
                "ipc": self._build_ipc_observation(),
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
                "router": self._build_router_observation(),
                "ipc": self._build_ipc_observation(),
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
                "router": self._build_router_observation(),
                "ipc": self._build_ipc_observation(),
            }

    def get_recent_error(self) -> dict[str, object] | None:
        """返回最近一次 broker 控制错误。"""

        with self._lock:
            return dict(self._recent_error) if self._recent_error is not None else None

    def write_bytes(
        self,
        *,
        content: bytes | bytearray | memoryview,
        owner_kind: str,
        owner_id: str,
        media_type: str,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        ttl_seconds: float | None = None,
        trace_id: str | None = None,
    ) -> LocalBufferWriteResult:
        """写入 bytes 并返回可跨进程传递的 BufferRef。"""

        client = self._require_client()
        try:
            result = client.write_bytes(
                content=content,
                owner_kind=owner_kind,
                owner_id=owner_id,
                media_type=media_type,
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

    def allocate_buffer(
        self,
        *,
        content_length: int,
        owner_kind: str,
        owner_id: str,
        ttl_seconds: float | None = None,
        trace_id: str | None = None,
    ) -> BufferLease:
        """分配 writing lease，供独立 daemon 直接写入结果图片。"""

        client = self._require_direct_io_client()
        try:
            return client.allocate_buffer(
                content_length=content_length,
                owner_kind=owner_kind,
                owner_id=owner_id,
                ttl_seconds=ttl_seconds,
                trace_id=trace_id,
            )
        except Exception as exc:
            self._record_recent_error(action="allocate-buffer", error=exc)
            raise

    def commit_buffer(
        self,
        *,
        lease: BufferLease,
        media_type: str,
        shape: tuple[int, ...] = (),
        dtype: str | None = None,
        layout: str | None = None,
        pixel_format: str | None = None,
        content_length: int | None = None,
    ) -> LocalBufferWriteResult:
        """提交由独立 daemon 写完的结果图片 lease。"""

        client = self._require_direct_io_client()
        try:
            return client.commit_buffer(
                lease=lease,
                media_type=media_type,
                shape=shape,
                dtype=dtype,
                layout=layout,
                pixel_format=pixel_format,
                content_length=content_length,
            )
        except Exception as exc:
            self._record_recent_error(action="commit-buffer", error=exc)
            raise

    def write_lease_bytes(
        self,
        *,
        lease: BufferLease,
        content: bytes | bytearray | memoryview,
    ) -> None:
        """直接覆盖已分配 lease 的 mmap 内容，不发送 broker 控制事件。"""

        try:
            with self._direct_io_lock:
                client = self._require_direct_io_client()
                client.write_lease_bytes(lease=lease, content=content)
        except Exception as exc:
            self._record_recent_error(action="write-lease-bytes", error=exc)
            raise

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
        frame_count: int,
        max_frame_content_length: int,
    ) -> dict[str, object]:
        """创建一个 ring buffer frame channel。

        参数：
        - stream_id：连续帧来源 id。
        - frame_count：长期预留的 frame extent 数量。
        - max_frame_content_length：每个 frame extent 的最大有效字节数。

        返回：
        - dict[str, object]：channel 状态摘要。
        """

        client = self._require_client()
        try:
            return client.create_frame_channel(
                stream_id=stream_id,
                frame_count=frame_count,
                max_frame_content_length=max_frame_content_length,
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
        content: bytes | bytearray | memoryview,
        media_type: str,
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

    def abort_frame(self, *, reservation: dict[str, object]) -> None:
        """放弃尚未 commit 的 frame reservation。"""

        client = self._require_client()
        try:
            client.abort_frame(reservation=reservation)
        except Exception as exc:
            self._record_recent_error(action="abort-frame", error=exc)
            raise
        finally:
            client.close()

    def destroy_frame_channel(
        self,
        *,
        stream_id: str,
    ) -> int:
        """销毁 frame channel 并释放其预留槽位。"""

        client = self._require_client()
        try:
            return client.destroy_frame_channel(stream_id=stream_id)
        except Exception as exc:
            self._record_recent_error(action="destroy-frame-channel", error=exc)
            raise
        finally:
            client.close()

    def release(self, lease_id: str) -> None:
        """释放一条 broker lease。"""

        client = self._require_client()
        try:
            client.release(lease_id)
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
    ) -> int:
        """释放指定 owner 匹配的全部 broker lease。

        参数：
        - owner_kind：可选 owner 类型过滤条件。
        - owner_id：可选 owner id 精确匹配条件。
        - owner_id_prefix：可选 owner id 前缀匹配条件。
        返回：
        - int：本次释放的 lease 数量。
        """

        client = self._require_client()
        try:
            released_count = client.release_owner(
                owner_kind=owner_kind,
                owner_id=owner_id,
                owner_id_prefix=owner_id_prefix,
            )
            return released_count
        except Exception as exc:
            self._record_recent_error(action="release-owner", error=exc)
            raise
        finally:
            client.close()

    def expire_leases(self) -> int:
        """触发 broker 回收已经过期的 lease。

        返回：
        - int：本次回收的 lease 数量。
        """

        client = self._require_client()
        try:
            expired_count = client.expire_leases()
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
            except (
                Exception
            ) as exc:  # pragma: no cover - 后台线程错误由 health recent_error 暴露
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

    def _require_direct_io_client(self) -> LocalBufferBrokerClient:
        """返回监督器生命周期内复用的 direct mmap client。"""

        with self._direct_io_lock:
            client = self._direct_io_client
            if client is None:
                client = self.create_client()
                if client is None:
                    raise ServiceConfigurationError("LocalBufferBroker 当前未启动")
                self._direct_io_client = client
            return client

    def _close_direct_io_client(self) -> None:
        """关闭监督器持有的 direct mmap client。"""

        with self._direct_io_lock:
            client = self._direct_io_client
            self._direct_io_client = None
        if client is not None:
            client.close()

    def _build_router_observation(self) -> dict[str, object]:
        """构造 broker router 的观测摘要。"""

        with self._lock:
            router = self._router
        if router is None:
            return {
                "configured": False,
                "response_router_running": False,
                "active_client_channel_count": 0,
                "pending_response_route_count": 0,
                "active_forward_thread_count": 0,
                "closed_channel_count": 0,
                "closed_channel_count_rollover_count": 0,
                "forward_error_count": 0,
                "forward_error_count_rollover_count": 0,
                "dropped_response_count": 0,
                "dropped_response_count_rollover_count": 0,
                "active_client_channel_ids": [],
                "active_client_channel_overflow_count": 0,
                "last_router_error": None,
            }
        return router.describe_state()

    def _build_ipc_observation(self) -> dict[str, object]:
        """构造 broker IPC 通道的观测摘要。"""

        with self._lock:
            startup_queue = self._startup_queue
            request_connection = self._request_connection
            response_connection = self._response_connection
        return {
            "startup_queue_configured": startup_queue is not None,
            "startup_queue_size": _safe_queue_size(startup_queue),
            "request_connection_configured": request_connection is not None,
            "request_connection_closed": (
                request_connection.closed if request_connection is not None else None
            ),
            "response_connection_configured": response_connection is not None,
            "response_connection_closed": (
                response_connection.closed if response_connection is not None else None
            ),
        }

    def _is_retryable_startup_error(self, error_payload: dict[str, object]) -> bool:
        """判断 broker 启动失败是否属于可短暂重试的映射占用场景。"""

        error_details = (
            error_payload.get("details")
            if isinstance(error_payload.get("details"), dict)
            else {}
        )
        error_type = str(error_details.get("error_type") or "")
        file_path = str(error_details.get("file_path") or "")
        detail_message = str(error_details.get("error_message") or "")
        return (
            error_type == "OSError"
            and file_path.endswith(".dat")
            and "Invalid argument" in detail_message
        )

    def _should_take_over_existing_process(
        self,
        error_payload: dict[str, object],
    ) -> bool:
        """判断启动失败是否应触发已验证 backend-service 进程接管。"""

        if not self.settings.takeover_existing_process:
            return False
        error_details = (
            error_payload.get("details")
            if isinstance(error_payload.get("details"), dict)
            else {}
        )
        return error_details.get("reason") == "root-lock-busy"

    def _cleanup_startup_queue_locked(self) -> None:
        """关闭启动队列。"""

        startup_queue = self._startup_queue
        self._startup_queue = None
        if startup_queue is None:
            return
        startup_queue.close()
        startup_queue.join_thread()

    def _cleanup_event_connections_locked(self) -> None:
        """关闭 broker 事件连接。"""

        request_connection = self._request_connection
        response_connection = self._response_connection
        self._request_connection = None
        self._response_connection = None
        for connection in (request_connection, response_connection):
            if connection is None:
                continue
            connection.close()


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


def _safe_queue_size(queue: Any) -> int | None:
    """最佳努力读取 multiprocessing queue 当前长度。"""

    if queue is None:
        return None
    qsize = getattr(queue, "qsize", None)
    if not callable(qsize):
        return None
    try:
        size = qsize()
    except Exception:
        return None
    return int(size) if isinstance(size, int) else None
