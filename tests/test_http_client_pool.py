"""HTTP ClientPool 连接复用、响应上限和背压测试。"""

from __future__ import annotations

from threading import Event, Thread
from time import monotonic

import httpx
import pytest

from backend.service.application.errors import InvalidRequestError, OperationCancelledError
from backend.service.application.workflows.execution.execution_control import ExecutionControl
from custom_nodes.http_nodes.categories.request.backend.runtime.transport import (
    HttpClientPool,
    HttpClientPoolSettings,
)


def _control(*, cancellation_event: Event | None = None) -> ExecutionControl:
    """构造 HTTP pool 测试控制对象。"""

    return ExecutionControl(
        node_id="http-node",
        cancellation_event=cancellation_event,
        deadline_monotonic=monotonic() + 5.0,
    )


def test_http_client_pool_reuses_single_client_for_multiple_requests() -> None:
    """同一进程池应连续处理多个请求而不重建 Client。"""

    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, json={"count": request_count}, request=request)

    pool = HttpClientPool(transport=httpx.MockTransport(handler))
    try:
        first = pool.request(
            control=_control(), method="GET", url="https://example.test/first", timeout=2.0
        )
        second = pool.request(
            control=_control(), method="GET", url="https://example.test/second", timeout=2.0
        )
    finally:
        pool.close()

    assert first.json() == {"count": 1}
    assert second.json() == {"count": 2}
    assert request_count == 2


def test_http_client_pool_rejects_content_length_over_limit() -> None:
    """Content-Length 已超限时不应继续读取 body。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-length": "128"},
            content=b"x" * 128,
            request=request,
        )

    pool = HttpClientPool(
        settings=HttpClientPoolSettings(max_response_bytes=64),
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(InvalidRequestError) as exc_info:
            pool.request(
                control=_control(), method="GET", url="https://example.test/large", timeout=2.0
            )
    finally:
        pool.close()

    assert exc_info.value.details["max_response_bytes"] == 64


def test_http_client_pool_waiting_for_permit_is_cancellable() -> None:
    """等待并发许可时必须响应 cancellation event。"""

    request_entered = Event()
    release_request = Event()

    def handler(request: httpx.Request) -> httpx.Response:
        request_entered.set()
        release_request.wait(timeout=2.0)
        return httpx.Response(200, content=b"ok", request=request)

    pool = HttpClientPool(
        settings=HttpClientPoolSettings(
            max_connections=1,
            max_keepalive_connections=1,
            max_inflight_requests=1,
            permit_poll_seconds=0.01,
        ),
        transport=httpx.MockTransport(handler),
    )
    first_thread = Thread(
        target=lambda: pool.request(
            control=_control(),
            method="GET",
            url="https://example.test/hold",
            timeout=2.0,
        ),
        daemon=True,
    )
    first_thread.start()
    assert request_entered.wait(timeout=1.0)
    cancellation_event = Event()
    cancellation_event.set()
    try:
        with pytest.raises(OperationCancelledError):
            pool.request(
                control=_control(cancellation_event=cancellation_event),
                method="GET",
                url="https://example.test/cancelled",
                timeout=2.0,
            )
    finally:
        release_request.set()
        first_thread.join(timeout=2.0)
        pool.close()
