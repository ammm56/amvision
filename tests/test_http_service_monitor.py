"""持续 HTTP 新连接探测的协议、超时和状态窗口测试。"""

import json
import socket
from threading import Thread
import time

import pytest

from runtimes.launchers.http_service_monitor import HealthDecision, ProbeResult, probe_service


def _response(*, status="200 OK", body=None, content_type="application/json"):
    """构造最小有长度响应。"""
    payload = json.dumps(body or {
        "format_id": "amvision.service-liveness.v1", "instance_id": "a" * 32,
        "pid": 123, "phase": "ready",
    }).encode()
    return f"HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {len(payload)}\r\n\r\n".encode() + payload


@pytest.mark.parametrize("response,expected", [
    (_response(), "ready"),
    (_response(status="302 Found"), "invalid"),
    (_response(content_type="text/html"), "invalid"),
    (_response(body={"status": "ok"}), "invalid"),
    (_response(body={"padding": "x" * 4200}), "invalid"),
])
def test_probe_validates_response(response, expected):
    """只接受固定 liveness 契约，拒绝 SPA 和无关服务。"""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    requests = []

    def serve():
        """分别接受两条新 TCP 连接。"""
        for _ in range(2):
            connection, _address = listener.accept()
            with connection:
                requests.append(connection.recv(1024))
                connection.sendall(response)

    thread = Thread(target=serve, daemon=True)
    thread.start()
    try:
        for _ in range(2):
            assert probe_service("127.0.0.1", listener.getsockname()[1]).kind == expected
        thread.join(2)
        assert not thread.is_alive()
        assert len(requests) == 2
        assert all(b"Connection: close" in request for request in requests)
    finally:
        listener.close()


def test_probe_total_deadline_cannot_be_extended_by_trickle():
    """持续发送零碎 header 不能无限延长总超时。"""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()

    def serve():
        """模拟每次 recv 都有少量数据的慢响应。"""
        connection, _address = listener.accept()
        with connection:
            connection.recv(1024)
            for _ in range(20):
                try:
                    connection.sendall(b"x")
                except OSError:
                    break
                time.sleep(0.03)

    thread = Thread(target=serve, daemon=True)
    thread.start()
    started = time.monotonic()
    try:
        assert probe_service("127.0.0.1", listener.getsockname()[1], timeout=0.15).kind == "timeout"
        assert time.monotonic() - started < 0.5
    finally:
        listener.close()
        thread.join(2)


def test_decision_distinguishes_transient_stall_and_lost_listener():
    """去重快照、短暂恢复、持续无响应分别处理。"""
    initial = ProbeResult("ready", 1, "a" * 32, 123)
    decision = HealthDecision(initial)
    bad = ProbeResult("timeout", 2)
    assert decision.observe(bad) == "degraded"
    assert decision.observe(bad) == "degraded"
    assert decision.failures == 1
    assert decision.observe(ProbeResult("timeout", 4)) == "degraded"
    assert decision.observe(ProbeResult("timeout", 6)) == "degraded"
    assert decision.observe(ProbeResult("ready", 8, initial.instance_id, 123)) == "degraded"
    assert decision.observe(ProbeResult("ready", 10, initial.instance_id, 123)) == "running"
    for at in (12, 14):
        assert decision.observe(ProbeResult("not_listening", at)) == "degraded"
    assert decision.observe(ProbeResult("not_listening", 16)) == "recovering"


def test_decision_refuses_replacement_and_confirms_long_stall():
    """其他实例不能冒充恢复，超时达到完整窗口才进入恢复。"""
    decision = HealthDecision(ProbeResult("ready", 1, "a" * 32, 123))
    assert decision.observe(ProbeResult("ready", 2, "b" * 32, 124)) == "failed"
    decision = HealthDecision(ProbeResult("ready", 1, "a" * 32, 123))
    for at in (2, 4, 30):
        assert decision.observe(ProbeResult("timeout", at)) == "degraded"
    assert decision.observe(ProbeResult("timeout", 32)) == "recovering"


def test_success_breaks_continuous_failure_window_without_clearing_degraded_early():
    """单次成功打断连续失败计数，但两次成功才清除降级显示。"""
    decision = HealthDecision(ProbeResult("ready", 1, "a" * 32, 123))
    for at in (2, 4):
        assert decision.observe(ProbeResult("not_listening", at)) == "degraded"
    assert decision.observe(ProbeResult("ready", 6, "a" * 32, 123)) == "degraded"
    for at in (8, 10):
        assert decision.observe(ProbeResult("not_listening", at)) == "degraded"
    assert decision.observe(ProbeResult("not_listening", 12)) == "recovering"
