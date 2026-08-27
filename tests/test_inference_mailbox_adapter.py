"""Inference 业务 adapter 接入通用 LocalMessage Mailbox 的专项测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Event, Lock
from time import sleep

import pytest

from backend.service.application.errors import (
    InvalidRequestError,
    OperationCancelledError,
    OperationTimeoutError,
)
from backend.service.application.message_channels.errors import (
    ChannelLegacyLayoutError,
)
from backend.service.application.runtime.deployment.inference_message_channel import (
    encode_inference_response,
)
from backend.service.infrastructure.ipc.inference_mailbox import (
    InferenceLocalMmapClient,
    InferenceLocalMmapServer,
)


def _client(tmp_path, *, timeout: float = 2.0) -> InferenceLocalMmapClient:
    return InferenceLocalMmapClient(
        buffers_root=tmp_path,
        service_id="inference-daemon-main",
        request_timeout_seconds=timeout,
    )


def _result_with_exact_wire_size(target_size: int) -> dict[str, object]:
    """构造指定 inference response envelope 长度的不可高度压缩结果。"""

    empty = {"value": ""}
    overhead = len(encode_inference_response({"ok": True, "result": empty}))
    value_size = target_size - overhead
    if value_size <= 0:
        raise ValueError("target_size 太小")
    value = os.urandom((value_size + 1) // 2).hex()[:value_size]
    result = {"value": value}
    assert (
        len(encode_inference_response({"ok": True, "result": result}))
        == target_size
    )
    return result


def test_inference_mailbox_owner_rejects_legacy_layout(tmp_path) -> None:
    """旧 service-id 命名的 mmap 存在时不能同时创建新 owner。"""

    legacy_path = tmp_path / "inference-control" / "inference_daemon_main.mmap"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(b"legacy")
    server = InferenceLocalMmapServer(
        buffers_root=tmp_path,
        service_id="inference_daemon_main",
        request_handler=lambda _request: {},
    )
    with pytest.raises(ChannelLegacyLayoutError, match="旧 LocalMessage layout"):
        server.start()
    assert not (
        tmp_path / "local-message" / "inference" / "mailbox.mmap"
    ).exists()


def test_inference_mailbox_round_trips_inline_and_page_chain(tmp_path) -> None:
    """验证小响应与 1 MiB response 都保持现有 ok/result envelope。"""

    server = InferenceLocalMmapServer(
        buffers_root=tmp_path,
        service_id="inference-daemon-main",
        request_handler=lambda request: {
            "value": (
                os.urandom(int(request["response_size"]) // 2).hex()
                if "response_size" in request
                else request["value"]
            )
        },
    )
    server.start()
    client = _client(tmp_path)
    try:
        assert client.request({"action": "run", "value": "small"}) == {
            "ok": True,
            "result": {"value": "small"},
        }
        large_result = client.request({"action": "run", "response_size": 1024 * 1024})[
            "result"
        ]
        assert len(large_result["value"]) == 1024 * 1024
        health = server.get_health_summary()
        assert health["descriptor_count"] == 128
        assert health["max_response_bytes"] == 32 * 1024 * 1024 + 64 * 1024
    finally:
        client.close()
        server.stop()


def test_inference_mailbox_serializes_handler_error_and_rejects_inline_image(tmp_path) -> None:
    """验证业务异常仍走 error envelope，图片正文在 client 边界即拒绝。"""

    def handler(_request):
        raise InvalidRequestError("bad inference request")

    server = InferenceLocalMmapServer(
        buffers_root=tmp_path,
        service_id="inference-daemon-main",
        request_handler=handler,
    )
    server.start()
    client = _client(tmp_path)
    try:
        response = client.request({"action": "run"})
        assert response["ok"] is False
        assert response["error"]["error_code"] == "invalid_request"
        with pytest.raises(InvalidRequestError, match="LocalBuffer"):
            client.request({"input_image_bytes_base64": "abc"})
    finally:
        client.close()
        server.stop()


def test_inference_mailbox_timeout_does_not_publish_late_result(tmp_path) -> None:
    """验证 deadline 取消 descriptor，handler 返回后不能发布过期结果。"""

    server = InferenceLocalMmapServer(
        buffers_root=tmp_path,
        service_id="inference-daemon-main",
        request_handler=lambda _request: (sleep(0.2) or {"late": True}),
        max_concurrent_requests=1,
    )
    server.start()
    client = _client(tmp_path, timeout=0.1)
    try:
        with pytest.raises(OperationTimeoutError):
            client.request({"action": "run"})
        sleep(0.25)
        health = server.get_health_summary()
        assert health["response_metrics"]["response_count"] == 0
        assert health["response_metrics"]["overflow_response_count"] == 0
        assert health["response_metrics"]["compressed_response_count"] == 0
    finally:
        client.close()
        server.stop()


def test_inference_mailbox_fences_old_client_epoch_without_retry(tmp_path) -> None:
    """验证 owner 切换不重跑当前请求，后续独立请求可打开新 epoch。"""

    first = InferenceLocalMmapServer(
        buffers_root=tmp_path,
        service_id="inference-daemon-main",
        request_handler=lambda _request: {"epoch": 1},
    )
    first.start()
    client = _client(tmp_path)
    assert client.request({"action": "run"})["result"] == {"epoch": 1}
    first.stop()
    second = InferenceLocalMmapServer(
        buffers_root=tmp_path,
        service_id="inference-daemon-main",
        request_handler=lambda _request: {"epoch": 2},
    )
    second.start()
    try:
        with pytest.raises(OperationCancelledError):
            client.request({"action": "run"})
        assert client.request({"action": "run"})["result"] == {"epoch": 2}
    finally:
        client.close()
        second.stop()


def test_inference_mailbox_admission_limits_handler_not_descriptor_capacity(tmp_path) -> None:
    """验证 max concurrency 只控制 handler，第二请求保留在 transport REQUEST。"""

    entered = Event()
    release = Event()

    def handler(request):
        if request["value"] == 1:
            entered.set()
            release.wait(timeout=2)
        return {"value": request["value"]}

    server = InferenceLocalMmapServer(
        buffers_root=tmp_path,
        service_id="inference-daemon-main",
        request_handler=handler,
        max_concurrent_requests=1,
    )
    server.start()
    first_client = _client(tmp_path)
    second_client = _client(tmp_path)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(first_client.request, {"action": "run", "value": 1})
            assert entered.wait(timeout=1)
            second = executor.submit(second_client.request, {"action": "run", "value": 2})
            sleep(0.05)
            health = server.get_health_summary()
            assert health["active_execution_count"] == 1
            assert health["descriptor_states"]["request"] == 1
            release.set()
            assert first.result(timeout=2)["result"] == {"value": 1}
            assert second.result(timeout=2)["result"] == {"value": 2}
    finally:
        release.set()
        first_client.close()
        second_client.close()
        server.stop()


def test_inference_mailbox_preserves_frozen_response_boundaries(tmp_path) -> None:
    """验证新 inline、旧 512 KiB 边界和 1/8/16/32 MiB 响应逐字节一致。"""

    targets = (
        256 * 1024,
        512 * 1024,
        1024 * 1024,
        8 * 1024 * 1024,
        16 * 1024 * 1024,
        32 * 1024 * 1024,
    )
    results = {target: _result_with_exact_wire_size(target) for target in targets}
    server = InferenceLocalMmapServer(
        buffers_root=tmp_path,
        service_id="inference-daemon-main",
        request_handler=lambda request: results[int(request["response_size"])],
    )
    server.start()
    client = _client(tmp_path, timeout=30.0)
    try:
        for target in targets:
            response = client.request({"action": "run", "response_size": target})
            assert response == {"ok": True, "result": results[target]}
        health = server.get_health_summary()
        metrics = health["response_metrics"]
        assert metrics["response_count"] == len(targets)
        assert metrics["overflow_response_count"] >= 1
        assert metrics["compressed_response_count"] >= 1
    finally:
        client.close()
        server.stop()


def test_inference_mailbox_handles_sixteen_mixed_calls_once_each(tmp_path) -> None:
    """验证 16 并发混合 inline/page-chain 请求不重跑 handler。"""

    executions: dict[int, int] = {}
    execution_lock = Lock()

    def handler(request):
        request_id = int(request["request_id"])
        with execution_lock:
            executions[request_id] = executions.get(request_id, 0) + 1
        if request["large"]:
            return _result_with_exact_wire_size(1024 * 1024)
        return {"request_id": request_id}

    server = InferenceLocalMmapServer(
        buffers_root=tmp_path,
        service_id="inference-daemon-main",
        request_handler=handler,
        max_concurrent_requests=16,
    )
    server.start()
    client = _client(tmp_path, timeout=15.0)
    try:
        with ThreadPoolExecutor(max_workers=16) as executor:
            responses = tuple(
                executor.map(
                    lambda request_id: client.request(
                        {
                            "action": "run",
                            "request_id": request_id,
                            "large": request_id % 2 == 1,
                        }
                    ),
                    range(16),
                )
            )
        assert len(responses) == 16
        assert executions == {request_id: 1 for request_id in range(16)}
        health = server.get_health_summary()
        assert health["response_metrics"]["response_count"] == 16
        assert health["response_metrics"]["overflow_response_count"] == 8
    finally:
        client.close()
        server.stop()
