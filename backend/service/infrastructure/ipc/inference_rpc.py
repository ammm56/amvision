"""Inference daemon 对通用 LocalMessage RpcMailbox 的业务适配。"""

from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from math import ceil
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic_ns
from typing import Callable
from uuid import uuid4

from backend.contracts.ipc.local_message_profiles import INFERENCE_RPC_PROFILE_V1
from backend.service.application.message_channels.errors import (
    ChannelCancelledError,
    ChannelCapacityExhaustedError,
    ChannelClosedError,
    ChannelCorruptMessageError,
    ChannelDeadlineExceededError,
    ChannelInvalidMessageError,
    ChannelRestartedError,
)
from backend.service.application.message_channels.models import RpcRequestContext
from backend.service.application.error_serialization import serialize_error
from backend.service.application.errors import (
    InvalidRequestError,
    OperationCancelledError,
    OperationTimeoutError,
    ServiceConfigurationError,
    ServiceError,
)
from backend.service.application.runtime.deployment.inference_message_channel import (
    decode_inference_request,
    decode_inference_response,
    encode_inference_request,
    encode_inference_response,
)
from backend.service.infrastructure.ipc.local_message.paths import (
    build_inference_rpc_channel_paths,
    reject_legacy_inference_layout,
)
from backend.service.infrastructure.ipc.local_message.rpc_mailbox import (
    MmapRpcMailboxClient,
    MmapRpcMailboxServer,
)


class _InferenceResponseCapacityExhaustedError(ServiceError):
    """表示 inference 结构化响应超过固定 Channel 容量。"""

    def __init__(self, message: str, *, details: dict[str, object]) -> None:
        super().__init__(
            message,
            code="mmap_response_capacity_exhausted",
            status_code=503,
            details=details,
        )


class InferenceLocalMmapClient:
    """保留 application 调用形状的通用 RpcMailbox client adapter。"""

    def __init__(
        self,
        *,
        buffers_root: str | Path,
        service_id: str,
        request_timeout_seconds: float,
    ) -> None:
        """绑定稳定 Channel identity；实际 endpoint 在首次请求时打开。"""

        self.paths = build_inference_rpc_channel_paths(
            buffers_root=buffers_root,
            service_id=service_id,
        )
        self.path = self.paths.mmap_path
        self.request_timeout_seconds = max(0.1, request_timeout_seconds)
        self._client: MmapRpcMailboxClient | None = None
        self._lock = Lock()
        self._closed = False

    def request(
        self,
        payload: dict[str, object],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        """执行一次请求；owner 变化只报错，不自动重跑模型。"""

        timeout = max(
            0.1,
            self.request_timeout_seconds if timeout_seconds is None else timeout_seconds,
        )
        deadline_ns = monotonic_ns() + int(timeout * 1e9)
        client: MmapRpcMailboxClient | None = None
        try:
            client = self._require_client()
            handle = client.call(
                request_id=uuid4(),
                wire_bytes=encode_inference_request(payload),
                deadline_ns=deadline_ns,
            )
            with handle:
                return decode_inference_response(handle.wire_bytes)
        except ChannelDeadlineExceededError as error:
            raise OperationTimeoutError("等待 inference RPC 响应超时") from error
        except (ChannelCancelledError, ChannelRestartedError) as error:
            self._drop_client()
            raise OperationCancelledError(
                "inference daemon 在请求处理中关闭或重启",
                details={"path": str(self.path), "retryable": True},
            ) from error
        except ChannelCapacityExhaustedError as error:
            raise _InferenceResponseCapacityExhaustedError(
                "inference RPC 固定容量暂时不足",
                details={"path": str(self.path)},
            ) from error
        except ChannelInvalidMessageError as error:
            raise InvalidRequestError(str(error)) from error
        except ChannelClosedError as error:
            self._drop_client()
            if client is not None:
                raise OperationCancelledError(
                    "inference daemon 在请求处理中关闭或重启",
                    details={"path": str(self.path), "retryable": True},
                ) from error
            raise ServiceConfigurationError(
                "inference daemon RPC Channel 不可用",
                details={"path": str(self.path)},
            ) from error
        except (ChannelCorruptMessageError, OSError) as error:
            self._drop_client()
            raise ServiceConfigurationError(
                "inference daemon RPC Channel 不可用",
                details={"path": str(self.path)},
            ) from error

    def close(self) -> None:
        """幂等关闭当前 client view。"""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            client, self._client = self._client, None
        if client is not None:
            client.close(deadline_ns=monotonic_ns())

    def _require_client(self) -> MmapRpcMailboxClient:
        """惰性打开当前 owner epoch。"""

        with self._lock:
            if self._closed:
                raise ChannelClosedError("Inference RPC client 已关闭")
            if self._client is None:
                self._client = MmapRpcMailboxClient(
                    paths=self.paths,
                    profile=INFERENCE_RPC_PROFILE_V1,
                )
            return self._client

    def _drop_client(self) -> None:
        """丢弃已失效 epoch，使下一次独立请求可打开新 owner。"""

        with self._lock:
            client, self._client = self._client, None
        if client is not None:
            client.close(deadline_ns=monotonic_ns())


class InferenceLocalMmapServer:
    """在通用 RpcMailbox 上提供有 admission 的 inference handler。"""

    def __init__(
        self,
        *,
        buffers_root: str | Path,
        service_id: str,
        request_handler: Callable[[dict[str, object]], dict[str, object]],
        max_concurrent_requests: int = 16,
    ) -> None:
        """绑定 Channel、handler 与领域执行并发，不接收 transport 几何配置。"""

        if max_concurrent_requests <= 0:
            raise ValueError("max_concurrent_requests 必须大于 0")
        self.buffers_root = Path(buffers_root).resolve()
        self.service_id = service_id
        self.paths = build_inference_rpc_channel_paths(
            buffers_root=self.buffers_root,
            service_id=service_id,
        )
        self.path = self.paths.mmap_path
        self.request_handler = request_handler
        self.max_concurrent_requests = max_concurrent_requests
        self._server: MmapRpcMailboxServer | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._active_count = 0
        self._active_lock = Lock()
        self._metrics_lock = Lock()
        self._response_raw_sizes: deque[int] = deque(maxlen=4096)
        self._response_raw_sizes_by_task: dict[str, deque[int]] = {}
        self._response_count = 0
        self._overflow_response_count = 0
        self._compressed_response_count = 0
        self._capacity_exhausted_count = 0
        self._page_high_watermark = 0

    @property
    def is_running(self) -> bool:
        """返回 dispatcher 线程是否存活。"""

        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """创建单 owner Channel 与常驻 dispatcher。"""

        if self.is_running:
            return
        reject_legacy_inference_layout(
            buffers_root=self.buffers_root,
            service_id=self.service_id,
        )
        self._server = MmapRpcMailboxServer(
            paths=self.paths,
            profile=INFERENCE_RPC_PROFILE_V1,
        )
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_concurrent_requests,
            thread_name_prefix="inference-rpc-handler",
        )
        self._stop_event.clear()
        self._thread = Thread(
            target=self._run_loop,
            name="inference-rpc-dispatcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止接收，先发布 closed fence，再等待已 claim handler。"""

        self._stop_event.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5.0)
        server, self._server = self._server, None
        if server is not None:
            server.close(deadline_ns=monotonic_ns() + 5_000_000_000)
        executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=False)

    def get_health_summary(self) -> dict[str, object]:
        """把通用 RPC health 映射到现有 inference health 契约。"""

        server = self._server
        if server is None:
            return {"ready": False, "protocol_version": 1}
        health = server.health()
        with self._active_lock:
            active = self._active_count
        used_pages = INFERENCE_RPC_PROFILE_V1.overflow_page_count - health.free_pages
        self._page_high_watermark = max(self._page_high_watermark, used_pages)
        with self._metrics_lock:
            metrics = {
                "response_count": self._response_count,
                "overflow_response_count": self._overflow_response_count,
                "compressed_response_count": self._compressed_response_count,
                "capacity_exhausted_count": self._capacity_exhausted_count,
                "raw_size_bytes": _build_size_summary(self._response_raw_sizes),
                "raw_size_bytes_by_task_type": {
                    name: _build_size_summary(values)
                    for name, values in sorted(self._response_raw_sizes_by_task.items())
                },
            }
        return {
            "ready": self.is_running,
            "protocol_version": 1,
            "server_epoch": health.owner_epoch,
            "descriptor_count": INFERENCE_RPC_PROFILE_V1.descriptor_count,
            "descriptor_states": {
                "free": health.free_descriptors,
                "request": health.request_descriptors,
                "processing": health.processing_descriptors,
                "response": health.response_descriptors,
                "acked": 0,
                "cancelled": 0,
            },
            "active_execution_count": active,
            "max_concurrent_requests": self.max_concurrent_requests,
            "inline_capacity_bytes": INFERENCE_RPC_PROFILE_V1.inline_response_capacity_bytes,
            "overflow_page_count": INFERENCE_RPC_PROFILE_V1.overflow_page_count,
            "overflow_page_capacity_bytes": INFERENCE_RPC_PROFILE_V1.overflow_page_capacity_bytes,
            "free_overflow_page_count": health.free_pages,
            "used_overflow_page_count": used_pages,
            "overflow_page_high_watermark": self._page_high_watermark,
            "max_overflow_pages_per_response": INFERENCE_RPC_PROFILE_V1.max_overflow_pages_per_response,
            "max_response_bytes": INFERENCE_RPC_PROFILE_V1.max_response_bytes,
            "response_metrics": metrics,
        }

    def _run_loop(self) -> None:
        """只在领域 admission 有容量时从 transport claim 请求。"""

        while not self._stop_event.is_set():
            with self._active_lock:
                has_capacity = self._active_count < self.max_concurrent_requests
            if not has_capacity:
                self._stop_event.wait(INFERENCE_RPC_PROFILE_V1.poll_interval_seconds)
                continue
            server = self._server
            if server is None:
                return
            request = server.receive(deadline_ns=monotonic_ns() + 10_000_000)
            if request is None:
                continue
            with self._active_lock:
                self._active_count += 1
            executor = self._executor
            if executor is None:
                with self._active_lock:
                    self._active_count -= 1
                return
            executor.submit(self._process_request, request)

    def _process_request(self, request: RpcRequestContext) -> None:
        """执行一次业务 handler，并由通用 engine 负责 publication/ACK。"""

        server = self._server
        if server is None:
            return
        raw_size = 0
        task_type = "unknown"
        published = False
        try:
            payload = decode_inference_request(request.wire_bytes)
            task_type = _read_request_task_type(payload)
            try:
                result = self.request_handler(payload)
                if payload.get("action") == "ping":
                    result = dict(result)
                    result["mailbox"] = self.get_health_summary()
                response = {"ok": True, "result": result}
            except Exception as error:  # noqa: BLE001 - IPC 边界统一序列化
                response = {"ok": False, "error": serialize_error(error)}
            wire_bytes = encode_inference_response(response)
            raw_size = len(wire_bytes)
            if raw_size > INFERENCE_RPC_PROFILE_V1.max_response_bytes:
                with self._metrics_lock:
                    self._capacity_exhausted_count += 1
                response = {
                    "ok": False,
                    "error": serialize_error(
                        _InferenceResponseCapacityExhaustedError(
                            "inference RPC 响应超过单请求上限",
                            details={
                                "response_size": raw_size,
                                "max_response_size": INFERENCE_RPC_PROFILE_V1.max_response_bytes,
                            },
                        )
                    ),
                }
                wire_bytes = encode_inference_response(response)
            publication = server.publish_response_with_receipt(
                request,
                wire_bytes=wire_bytes,
            )
            published = True
        except (
            ChannelCancelledError,
            ChannelDeadlineExceededError,
            ChannelRestartedError,
        ):
            return
        except ChannelCapacityExhaustedError:
            with self._metrics_lock:
                self._capacity_exhausted_count += 1
            return
        except Exception:
            try:
                server.publish_failure(request)
            except Exception:
                pass
        finally:
            if published:
                with self._metrics_lock:
                    self._response_count += 1
                    self._overflow_response_count += int(publication.page_count > 0)
                    self._compressed_response_count += int(publication.compressed)
                    self._response_raw_sizes.append(raw_size)
                    self._response_raw_sizes_by_task.setdefault(
                        task_type, deque(maxlen=4096)
                    ).append(raw_size)
            with self._active_lock:
                self._active_count -= 1


def _read_request_task_type(payload: dict[str, object]) -> str:
    """从请求快照读取五类 task type 或只读 action。"""

    process_config = payload.get("process_config")
    if isinstance(process_config, dict):
        for key in ("runtime_target_snapshot", "runtime_target"):
            runtime_target = process_config.get(key)
            if not isinstance(runtime_target, dict):
                continue
            task_type = runtime_target.get("task_type")
            if isinstance(task_type, str) and task_type.strip():
                return task_type.strip().lower()
    action = payload.get("action")
    return action if isinstance(action, str) else "unknown"


def _build_size_summary(values: deque[int]) -> dict[str, int | None]:
    """返回最近 4096 个 response envelope 长度的确定性分位数。"""

    ordered = sorted(values)
    if not ordered:
        return {"sample_count": 0, "p50": None, "p95": None, "p99": None, "max": None}

    def percentile(ratio: float) -> int:
        return ordered[min(len(ordered) - 1, max(0, ceil(len(ordered) * ratio) - 1))]

    return {
        "sample_count": len(ordered),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": ordered[-1],
    }


__all__ = ["InferenceLocalMmapClient", "InferenceLocalMmapServer"]
