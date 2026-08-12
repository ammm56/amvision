"""HTTP Request 节点的连接池、背压和有界响应读取。"""

from __future__ import annotations

import atexit
from dataclasses import dataclass
from threading import BoundedSemaphore

import httpx

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import (
    ResourceScope,
    create_process_resource_scope,
)
from backend.service.application.workflows.execution.contracts import (
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.execution.execution_control import (
    ExecutionControl,
    build_node_execution_control,
)
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)


_HTTP_CLIENT_POOL_RESOURCE_KEY = "custom.http.client-pool"
_DEFAULT_PROCESS_SCOPE = create_process_resource_scope()
_STREAM_CHUNK_SIZE = 64 * 1024
atexit.register(_DEFAULT_PROCESS_SCOPE.close)


@dataclass(frozen=True)
class HttpClientPoolSettings:
    """描述 HTTP 连接池和响应保护上限。"""

    max_connections: int = 32
    max_keepalive_connections: int = 16
    max_inflight_requests: int = 32
    keepalive_expiry_seconds: float = 30.0
    max_response_bytes: int = 32 * 1024 * 1024
    permit_poll_seconds: float = 0.1


class HttpClientPool:
    """复用 httpx.Client，并限制并发请求和响应内存。"""

    def __init__(
        self,
        *,
        settings: HttpClientPoolSettings | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """创建进程内 HTTP ClientPool。"""

        self.settings = settings or HttpClientPoolSettings()
        _validate_settings(self.settings)
        self._client = httpx.Client(
            limits=httpx.Limits(
                max_connections=self.settings.max_connections,
                max_keepalive_connections=self.settings.max_keepalive_connections,
                keepalive_expiry=self.settings.keepalive_expiry_seconds,
            ),
            transport=transport,
        )
        self._inflight = BoundedSemaphore(self.settings.max_inflight_requests)
        self._closed = False

    def request(
        self,
        *,
        control: ExecutionControl,
        method: str,
        url: str,
        timeout: float,
        params: object = None,
        headers: object = None,
        json: object = None,
    ) -> httpx.Response:
        """执行一次受并发和响应大小保护的 HTTP 请求。"""

        if self._closed:
            raise RuntimeError("HttpClientPool 已关闭")
        self._acquire_permit(control)
        try:
            control.raise_if_cancelled_or_expired()
            remaining = control.remaining_seconds()
            effective_timeout = float(timeout)
            if remaining is not None:
                effective_timeout = min(effective_timeout, max(0.001, remaining))
            with self._client.stream(
                method=method,
                url=url,
                timeout=httpx.Timeout(effective_timeout),
                params=params,
                headers=headers,
                json=json,
            ) as response:
                control.raise_if_cancelled_or_expired()
                _reject_large_content_length(
                    response,
                    max_response_bytes=self.settings.max_response_bytes,
                )
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=_STREAM_CHUNK_SIZE):
                    control.raise_if_cancelled_or_expired()
                    if len(body) + len(chunk) > self.settings.max_response_bytes:
                        raise _build_response_too_large_error(
                            max_response_bytes=self.settings.max_response_bytes,
                            observed_bytes=len(body) + len(chunk),
                        )
                    body.extend(chunk)
                return httpx.Response(
                    status_code=response.status_code,
                    headers=response.headers,
                    content=bytes(body),
                    request=response.request,
                    extensions=dict(response.extensions),
                )
        finally:
            self._inflight.release()

    def close(self) -> None:
        """幂等关闭底层连接池。"""

        if self._closed:
            return
        self._closed = True
        self._client.close()

    def _acquire_permit(self, control: ExecutionControl) -> None:
        """可取消地等待进程内 HTTP 并发许可。"""

        while True:
            control.raise_if_cancelled_or_expired()
            remaining = control.remaining_seconds()
            wait_seconds = self.settings.permit_poll_seconds
            if remaining is not None:
                wait_seconds = min(wait_seconds, max(0.001, remaining))
            if self._inflight.acquire(timeout=wait_seconds):
                return


def execute_bounded_http_request(
    *,
    request: WorkflowNodeExecutionRequest,
    method: str,
    url: str,
    timeout: float,
    params: object = None,
    headers: object = None,
    json: object = None,
) -> httpx.Response:
    """通过当前 worker 的共享 ClientPool 执行 HTTP 请求。"""

    control = build_node_execution_control(
        request,
        operation_timeout_seconds=timeout,
    )
    pool = _require_http_client_pool(_resolve_process_scope(request))
    return pool.request(
        control=control,
        method=method,
        url=url,
        timeout=timeout,
        params=params,
        headers=headers,
        json=json,
    )


def _resolve_process_scope(request: WorkflowNodeExecutionRequest) -> ResourceScope:
    """解析节点所属 worker 的进程资源作用域。"""

    if isinstance(request.runtime_context, WorkflowServiceNodeRuntimeContext):
        return request.runtime_context.process_resource_scope
    return _DEFAULT_PROCESS_SCOPE


def _require_http_client_pool(scope: ResourceScope) -> HttpClientPool:
    """返回当前进程唯一的 HTTP ClientPool。"""

    resource = scope.get_or_create(
        _HTTP_CLIENT_POOL_RESOURCE_KEY,
        HttpClientPool,
        lambda value: value.close(),
    )
    if not isinstance(resource, HttpClientPool):
        raise RuntimeError("HTTP ClientPool 资源类型无效")
    return resource


def _reject_large_content_length(
    response: httpx.Response,
    *,
    max_response_bytes: int,
) -> None:
    """服务端声明的响应长度超限时提前拒绝。"""

    raw_content_length = response.headers.get("content-length")
    if raw_content_length is None:
        return
    try:
        content_length = int(raw_content_length)
    except ValueError:
        return
    if content_length > max_response_bytes:
        raise _build_response_too_large_error(
            max_response_bytes=max_response_bytes,
            observed_bytes=content_length,
        )


def _build_response_too_large_error(
    *,
    max_response_bytes: int,
    observed_bytes: int,
) -> InvalidRequestError:
    """构造稳定的响应大小超限错误。"""

    return InvalidRequestError(
        "HTTP 响应超过平台允许的最大字节数",
        details={
            "max_response_bytes": max_response_bytes,
            "observed_bytes": observed_bytes,
        },
    )


def _validate_settings(settings: HttpClientPoolSettings) -> None:
    """校验 HTTP ClientPool 内部配置。"""

    positive_values = {
        "max_connections": settings.max_connections,
        "max_keepalive_connections": settings.max_keepalive_connections,
        "max_inflight_requests": settings.max_inflight_requests,
        "keepalive_expiry_seconds": settings.keepalive_expiry_seconds,
        "max_response_bytes": settings.max_response_bytes,
        "permit_poll_seconds": settings.permit_poll_seconds,
    }
    for field_name, value in positive_values.items():
        if value <= 0:
            raise ValueError(f"{field_name} 必须大于 0")
    if settings.max_keepalive_connections > settings.max_connections:
        raise ValueError("max_keepalive_connections 不能大于 max_connections")


__all__ = [
    "HttpClientPool",
    "HttpClientPoolSettings",
    "execute_bounded_http_request",
]
