"""Broker 超时隔离、进程内周期清理和读者保护回归。"""

from queue import Queue
from time import monotonic, monotonic_ns, sleep
from types import SimpleNamespace

import pytest

from backend.service.application.errors import (
    OperationTimeoutError,
    ServiceConfigurationError,
)
from backend.service.application.local_buffers.local_buffer_client import (
    LocalBufferBrokerClient,
    LocalBufferBrokerEventChannel,
)
from backend.service.application.local_buffers.local_buffer_broker_process import (
    _BrokerHousekeeping,
)
from tests.test_local_buffer_broker_phase1 import _supervisor


def test_late_response_does_not_poison_next_request():
    """第一次请求超时后仅丢弃已知迟到响应；新请求只发送一次。"""
    requests, responses = Queue(), Queue()
    client = LocalBufferBrokerClient(
        LocalBufferBrokerEventChannel(requests, responses, 0.02)
    )
    with pytest.raises(OperationTimeoutError) as error:
        client.get_status()
    first = requests.get_nowait()
    assert error.value.details["request_id"] == first["request_id"]
    responses.put(
        {"request_id": first["request_id"], "ok": True, "payload": {"old": True}}
    )

    class Reply:
        def put(self, message):
            requests.put(message)
            responses.put(
                {
                    "request_id": message["request_id"],
                    "ok": True,
                    "payload": {"current": True},
                }
            )

    client.channel = LocalBufferBrokerEventChannel(Reply(), responses, 0.1)
    assert client.get_status() == {"current": True}
    requests.get_nowait()
    assert requests.empty()
    assert not client._timed_out_requests
    client.close()


def test_unknown_response_is_not_silently_discarded():
    """未知 identity 继续报错，不能把其他客户端的回复作为本次结果。"""
    responses = Queue()
    responses.put({"request_id": "foreign", "ok": True, "payload": {}})
    with LocalBufferBrokerClient(
        LocalBufferBrokerEventChannel(Queue(), responses, 0.02)
    ) as client:
        with pytest.raises(ServiceConfigurationError, match="identity"):
            client.get_status()


def test_housekeeping_failure_is_visible_until_same_action_recovers(monkeypatch):
    """到期清理失败不杀死 Broker，也不能被撤销扫描成功掩盖。"""
    from backend.service.application.local_buffers import (
        local_buffer_broker_process as module,
    )

    now = [0.0]
    monkeypatch.setattr(module, "monotonic", lambda: now[0])
    calls = []
    fail = [True]

    def expire():
        calls.append("expire")
        if fail[0]:
            raise OSError("injected cleanup failure")

    registry = SimpleNamespace(
        settings=SimpleNamespace(expire_interval_seconds=1.0),
        _arena=SimpleNamespace(expire_leases=expire),
        sweep_reclaiming_leases=lambda: calls.append("sweep"),
    )
    house = _BrokerHousekeeping(registry)
    now[0] = 1.0
    house.run_due()
    assert house.error["action"] == "expire-leases"
    now[0] = 1.5
    house.run_due()
    assert house.error is not None
    fail[0] = False
    now[0] = 2.0
    house.run_due()
    assert house.error is None
    assert house.describe()["last_error"]["message"] == "injected cleanup failure"
    assert calls == ["expire", "sweep", "sweep", "expire", "sweep"]


def test_busy_broker_expires_without_parent_cleanup_rpc(tmp_path):
    """持续控制请求不再饿死回收；TTL 与 reader guard 在真实子进程中验证。"""
    supervisor = _supervisor(tmp_path)
    supervisor.settings.expire_interval_seconds = 0.1
    supervisor.start()
    try:
        with supervisor.create_client() as client:
            result = client.write_bytes(
                content=b"guarded",
                owner_kind="test",
                owner_id="ttl",
                media_type="image/raw",
                ttl_seconds=0.3,
            )
            with client.acquire_buffer_reader_guard(
                buffer_ref=result.buffer_ref, deadline_ns=monotonic_ns() + 5_000_000_000
            ):
                end = monotonic() + 0.9
                while monotonic() < end:
                    status = client.get_status()
                assert status["free_capacity_bytes"] < 16 * 1024**2
                assert (
                    status["revoking_capacity_bytes"]
                    + status["quarantined_capacity_bytes"]
                    > 0
                )
            end = monotonic() + 2.0
            while monotonic() < end:
                status = client.get_status()
                if status["free_capacity_bytes"] == 16 * 1024**2:
                    break
            assert status["free_capacity_bytes"] == 16 * 1024**2
            assert status["housekeeping"]["owner"] == "broker"
            assert status["housekeeping"]["last_success_at"]
            assert status["housekeeping"]["error"] is None
            assert supervisor.get_recent_error() is None
    finally:
        supervisor.stop()


def test_idle_broker_expires_without_control_requests(tmp_path):
    """没有 HTTP/RPC 访问时 Broker 也按时释放过期普通租约。"""
    supervisor = _supervisor(tmp_path)
    supervisor.settings.expire_interval_seconds = 0.1
    supervisor.start()
    try:
        with supervisor.create_client() as client:
            client.write_bytes(
                content=b"expired",
                owner_kind="test",
                owner_id="idle",
                media_type="image/raw",
                ttl_seconds=0.1,
            )
            sleep(0.7)
            assert client.get_status()["free_capacity_bytes"] == 16 * 1024**2
    finally:
        supervisor.stop()
