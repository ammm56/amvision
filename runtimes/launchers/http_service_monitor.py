"""独立、低频、有界的新连接 HTTP 探测与故障确认。"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import socket
from threading import Event, Lock, Thread
import time


@dataclass(frozen=True)
class ProbeResult:
    """一次探测的有界结果；时间戳使用 monotonic clock。"""

    kind: str
    checked_at: float
    instance_id: str = ""
    pid: int = 0
    detail: str = ""


def probe_service(host: str, port: int, *, timeout: float = 1.0) -> ProbeResult:
    """新建 loopback TCP 连接，限制整个请求时长和响应容量。"""
    started = time.monotonic()
    address = "127.0.0.1" if host in {"", "0.0.0.0", "localhost"} else "::1" if host == "::" else host
    try:
        ipaddress.ip_address(address)
        deadline = started + timeout
        with socket.create_connection((address, port), timeout=timeout) as connection:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("probe deadline")
            connection.settimeout(remaining)
            connection.sendall(
                f"GET /api/v1/system/liveness HTTP/1.1\r\nHost: localhost:{port}\r\nConnection: close\r\nAccept: application/json\r\n\r\n".encode("ascii")
            )
            payload = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("probe deadline")
                connection.settimeout(remaining)
                chunk = connection.recv(8193 - len(payload))
                if not chunk:
                    raise ValueError("incomplete response")
                payload.extend(chunk)
                if len(payload) > 8192:
                    raise ValueError("response too large")
                header, separator, body = bytes(payload).partition(b"\r\n\r\n")
                if len(header) > 4096:
                    raise ValueError("headers too large")
                if not separator:
                    if len(header) > 4096:
                        raise ValueError("headers too large")
                    continue
                lines = header.decode("iso-8859-1").split("\r\n")
                if lines[0].split()[:2] not in (["HTTP/1.1", "200"], ["HTTP/1.0", "200"]):
                    raise ValueError("unexpected HTTP status")
                headers = {}
                for line in lines[1:]:
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    if key in headers:
                        raise ValueError("duplicate response header")
                    headers[key] = value.strip()
                if headers.get("content-type", "").split(";", 1)[0] != "application/json":
                    raise ValueError("unexpected content type")
                length = int(headers.get("content-length", "-1"))
                if "transfer-encoding" in headers or not 0 < length <= 4096:
                    raise ValueError("invalid response length")
                if len(body) < length:
                    continue
                data = json.loads(body[:length])
                if not isinstance(data, dict) or data.get("format_id") != "amvision.service-liveness.v1":
                    raise ValueError("invalid liveness format")
                identity, pid = data.get("instance_id"), data.get("pid")
                if not isinstance(identity, str) or len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
                    raise ValueError("invalid service identity")
                if type(pid) is not int or pid <= 0 or data.get("phase") != "ready":
                    raise ValueError("service not ready")
                return ProbeResult("ready", time.monotonic(), identity, pid)
    except ConnectionRefusedError:
        return ProbeResult("not_listening", time.monotonic())
    except TimeoutError:
        return ProbeResult("timeout", time.monotonic())
    except (OSError, ValueError, KeyError, TypeError) as error:
        return ProbeResult("invalid", time.monotonic(), detail=str(error)[:256])


class ServiceMonitor:
    """单后台线程串行探测，只保存最后一次结果。"""

    def __init__(self, host: str, port: int, *, interval: float = 2.0, timeout: float = 1.0):
        """初始化目标地址、周期、停止信号与结果锁。"""
        self.host, self.port = host, port
        if interval <= 0 or timeout <= 0:
            raise ValueError("探测周期和超时必须为正数")
        self.interval, self.timeout = interval, timeout
        self._stop = Event()
        self._lock = Lock()
        self._result: ProbeResult | None = None
        self._thread = Thread(target=self._run, name="service-liveness", daemon=True)

    def start(self) -> None:
        """启动单一探测任务。"""
        self._thread.start()

    def latest(self) -> ProbeResult | None:
        """读取不可变快照，不进行网络等待。"""
        with self._lock:
            return self._result

    def assert_healthy(self) -> None:
        """探测线程异常退出不能被误认为服务仍正常。"""
        if not self._thread.is_alive() and not self._stop.is_set():
            raise RuntimeError("HTTP probe thread stopped unexpectedly")

    def close(self) -> None:
        """停止探测，等待最多一次有界请求完成。"""
        self._stop.set()
        self._thread.join(self.timeout + 2)
        if self._thread.is_alive():
            raise RuntimeError("HTTP probe thread did not stop")

    def _run(self) -> None:
        """每轮新建连接，不积累线程或未完成请求。"""
        while not self._stop.is_set():
            result = probe_service(self.host, self.port, timeout=self.timeout)
            with self._lock:
                self._result = result
            if self._stop.wait(self.interval):
                return


class HealthDecision:
    """同一服务实例的连续失败/成功窗口。"""

    def __init__(self, identity: ProbeResult):
        """固定已就绪实例，拒绝将端口上的其他进程当作恢复。"""
        self.identity = identity
        self.last_checked_at = 0.0
        self.failures = 0
        self.successes = 0
        self.failed_since: float | None = None
        self.state = "running"

    def observe(self, result: ProbeResult | None) -> str:
        """返回 running/degraded/recovering/failed，不重复消费同一快照。"""
        if result is None or result.checked_at <= self.last_checked_at:
            return self.state
        if self.state == "failed":
            return self.state
        self.last_checked_at = result.checked_at
        if result.kind == "ready":
            if (result.instance_id, result.pid) != (self.identity.instance_id, self.identity.pid):
                self.state = "failed"
                return self.state
            self.successes = min(2, self.successes + 1)
            self.failures = 0
            self.failed_since = None
            if self.successes >= 2:
                self.state = "running"
        else:
            self.successes = 0
            self.failures = min(3, self.failures + 1)
            if self.failed_since is None:
                self.failed_since = result.checked_at
            self.state = "degraded"
            if self.failures >= 3 and (
                result.kind == "not_listening" or result.checked_at - self.failed_since >= 30
            ):
                self.state = "recovering"
        return self.state
