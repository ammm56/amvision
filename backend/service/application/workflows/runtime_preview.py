"""Runtime 预览的单次显示交接；独立于业务响应，无历史和待发送队列。"""

from __future__ import annotations

import asyncio
import json
import math
import socket
import struct
from threading import Event, Lock, Thread
from typing import Any

from backend.contracts.workflows.workflow_graph import NodeDefinition

PREVIEW_CAPTURE_KEY = "_runtime_preview_capture"
PREVIEW_FORMAT = "amvision.workflow-runtime-preview.v1"
MAX_PREVIEW_BYTES = 64 * 1024 * 1024
MAX_PREVIEW_VALUES = 100_000
PREVIEW_TYPES = frozenset({"image-preview", "value-preview", "table-preview", "gallery-preview"})


class _DisplayLimit(ValueError):
    """显示副本超过限制，不影响业务执行。"""


def _copy_json(value: object, budget: list[int], depth: int = 0) -> object:
    """有界复制 JSON 容器，复用不可变字符串；拒绝矩阵、lease 等运行时对象。"""
    budget[1] -= 1
    if depth > 32 or budget[1] < 0:
        raise _DisplayLimit("preview_structure_limit")
    if isinstance(value, str):
        size = len(value) if value.isascii() else len(value.encode("utf-8"))
        budget[0] -= size + 8
        result: object = value
    elif value is None or isinstance(value, bool | int):
        budget[0] -= 32
        result = value
    elif isinstance(value, float) and math.isfinite(value):
        budget[0] -= 32
        result = value
    elif isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise _DisplayLimit("preview_not_json")
            result[_copy_json(key, budget, depth + 1)] = _copy_json(item, budget, depth + 1)
    elif isinstance(value, list | tuple):
        result = [_copy_json(item, budget, depth + 1) for item in value]
    else:
        raise _DisplayLimit("preview_not_json")
    if budget[0] < 0:
        raise _DisplayLimit("preview_size_limit")
    return result


class RuntimePreviewCapture:
    """一次 Run 的预览副本；同节点循环仅保留最后一个明确调用身份。"""

    def __init__(self) -> None:
        """初始化当前 Run 的记录、容量预算和并行节点互斥锁。"""
        self.records: dict[tuple[str, str], dict[str, object]] = {}
        self.budget = [MAX_PREVIEW_BYTES - 16_384, MAX_PREVIEW_VALUES]
        self.error: str | None = None
        self.lock = Lock()

    def capture(self, *, node_id: str, definition: NodeDefinition,
                outputs: dict[str, object], invocation_id: str,
                duration_ms: float) -> None:
        """仅复制声明 ui.preview 的显示端口，不读取图片源或修改节点输出。"""
        if "ui.preview" not in definition.capability_tags:
            return
        with self.lock:
            if self.error:
                return
            try:
                for port in definition.output_ports:
                    payload = outputs.get(port.name)
                    if not isinstance(payload, dict) or payload.get("type") not in PREVIEW_TYPES:
                        continue
                    copied = _copy_json(payload, self.budget)
                    # 图像交互编辑仅属于编辑画布；运行画布不能改参数。
                    copied.pop("interaction", None)
                    if copied.get("type") == "gallery-preview" and isinstance(copied.get("items"), list):
                        for item in copied["items"]:
                            if isinstance(item, dict):
                                item.pop("interaction", None)
                    self.records[(node_id, port.name)] = {
                        "node_id": node_id, "node_type_id": definition.node_type_id,
                        "output_port": port.name, "invocation_id": invocation_id,
                        "duration_ms": duration_ms, "payload": copied,
                    }
            except Exception as exc:
                self.records.clear()
                self.error = str(exc) if isinstance(exc, _DisplayLimit) else "preview_copy_failed"


class RuntimePreviewSender:
    """Worker 独立发送线程，最多一份正在收集/发送的 Run，不等待空位。"""

    def __init__(self, channel: socket.socket, observed: Any) -> None:
        """channel 是专用 socket；observed 是父进程维护的订阅信号。"""
        self.channel = channel
        self.channel.settimeout(2.0)
        self.observed = observed
        self.lock = Lock()
        self.wake = Event()
        self.stopped = Event()
        self.busy = False
        self.payload: dict[str, object] | None = None
        self.thread: Thread | None = None

    def begin(self) -> RuntimePreviewCapture | None:
        """仅观察者存在且当前没有在途数据时捕获本次显示。"""
        if not self.observed.is_set() or self.stopped.is_set():
            return None
        with self.lock:
            if self.busy:
                return None
            self.busy = True
            if self.thread is None:
                self.thread = Thread(target=self._run, name="runtime-preview-send", daemon=True)
                try:
                    self.thread.start()
                except RuntimeError:
                    self.thread = None
                    self.stopped.set()
                    self.busy = False
                    return None
        return RuntimePreviewCapture()

    def finish(self, capture: RuntimePreviewCapture, identity: dict[str, object]) -> None:
        """业务响应已交接后移交本次副本，不进行 JSON 编码或网络等待。"""
        with self.lock:
            if not self.observed.is_set() or self.stopped.is_set():
                self.busy = False
                return
            self.payload = {
                "format_id": PREVIEW_FORMAT, **identity,
                "displays": list(capture.records.values()), "display_error": capture.error,
            }
            self.wake.set()

    def _run(self) -> None:
        """在独立通道串行发送当前帧；失败只终止显示通道。"""
        try:
            while not self.stopped.is_set():
                self.wake.wait()
                self.wake.clear()
                with self.lock:
                    payload, self.payload = self.payload, None
                if payload is None:
                    continue
                try:
                    if self.observed.is_set():
                        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
                        if len(data) > MAX_PREVIEW_BYTES:
                            payload["displays"] = []
                            payload["display_error"] = "preview_size_limit"
                            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                        self.channel.sendall(struct.pack("!I", len(data)))
                        self.channel.sendall(data)
                        del data
                finally:
                    payload = None
                    with self.lock:
                        self.busy = False
        except (OSError, ValueError, TypeError):
            self.stopped.set()
        finally:
            self.stopped.set()
            self.channel.close()

    def close(self) -> None:
        """终止显示通道和线程，释放当前副本。"""
        self.stopped.set()
        self.wake.set()
        try:
            self.channel.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.channel.close()
        if self.thread is not None:
            self.thread.join(timeout=3.0)
        self.payload = None


class RuntimePreviewSubscription:
    """单个 WebSocket 的在途交接；发送期间的新帧直接略过。"""

    def __init__(self) -> None:
        """记录所属事件循环及当前接收方，不保留历史消息。"""
        self.loop = asyncio.get_running_loop()
        self.lock = Lock()
        self.waiter: asyncio.Future[str | None] | None = None
        self.busy = False
        self.closed = False

    async def receive(self) -> str | None:
        """等待下一帧；上次发送完成后才重新允许交接。"""
        with self.lock:
            if self.closed:
                return None
            self.busy = False
            self.waiter = self.loop.create_future()
            waiter = self.waiter
        return await waiter

    def offer(self, text: str) -> None:
        """接收线程直接尝试交给一个就绪的 WebSocket，不排队。"""
        with self.lock:
            if self.closed or self.busy or self.waiter is None:
                return
            self.busy = True
            waiter, self.waiter = self.waiter, None
        try:
            self.loop.call_soon_threadsafe(self._deliver, waiter, text)
        except RuntimeError:
            self.close()

    def _deliver(self, waiter: asyncio.Future[str | None], text: str | None) -> None:
        """只在原事件循环中完成 waiter，关闭后不再交付旧内容。"""
        if not waiter.done():
            waiter.set_result(None if self.closed else text)

    def close(self) -> None:
        """断开时释放等待者；幂等且可由接收线程调用。"""
        with self.lock:
            self.closed = True
            waiter, self.waiter = self.waiter, None
        if waiter is not None:
            try:
                self.loop.call_soon_threadsafe(self._deliver, waiter, None)
            except RuntimeError:
                pass


class RuntimePreviewChannel:
    """父进程专用接收通道；订阅随 worker generation 关闭，不跨版本复用。"""

    def __init__(self, channel: socket.socket, observed: Any) -> None:
        """保存 socket、共享订阅信号和有界客户端集合。"""
        self.channel = channel
        self.observed = observed
        self.lock = Lock()
        self.subscriptions: set[RuntimePreviewSubscription] = set()
        self.closed = False
        self.thread = Thread(target=self._run, name="runtime-preview-receive", daemon=True)
        try:
            self.thread.start()
        except RuntimeError:
            # 观察线程启动失败只关闭观察能力，不使已启动的业务 worker 失效。
            self._disconnect()
            self.channel.close()

    def subscribe(self) -> RuntimePreviewSubscription:
        """只订阅当前 worker，最多 16 个连接，不启动或重启 Runtime。"""
        with self.lock:
            if self.closed or len(self.subscriptions) >= 16:
                raise ValueError("runtime_preview_unavailable")
            subscription = RuntimePreviewSubscription()
            self.subscriptions.add(subscription)
            self.observed.set()
            return subscription

    def unsubscribe(self, subscription: RuntimePreviewSubscription) -> None:
        """移除订阅；最后一个页面关闭后取消 Worker 捕获信号。"""
        subscription.close()
        with self.lock:
            self.subscriptions.discard(subscription)
            if not self.subscriptions:
                self.observed.clear()

    def _read(self, count: int) -> bytearray:
        """读取一帧的指定长度；EOF 立即退出，不截断后接着读下一帧。"""
        data = bytearray(count)
        view = memoryview(data)
        offset = 0
        while offset < count:
            received = self.channel.recv_into(view[offset:])
            if received == 0:
                raise EOFError
            offset += received
        return data

    def _run(self) -> None:
        """独立线程收帧和扇出，不使用业务响应/超时控制通道。"""
        try:
            while True:
                size = struct.unpack("!I", self._read(4))[0]
                if size > MAX_PREVIEW_BYTES:
                    raise ValueError("preview_size_limit")
                text = self._read(size).decode("utf-8")
                with self.lock:
                    subscriptions = tuple(self.subscriptions)
                for subscription in subscriptions:
                    subscription.offer(text)
                del text
                subscriptions = ()
        except (OSError, EOFError, ValueError):
            pass
        finally:
            self._disconnect()
            self.channel.close()

    def _disconnect(self) -> None:
        """只关闭显示订阅，不触及 Runtime 的执行状态。"""
        with self.lock:
            self.closed = True
            self.observed.clear()
            subscriptions = tuple(self.subscriptions)
            self.subscriptions.clear()
        for subscription in subscriptions:
            subscription.close()

    def close(self) -> None:
        """停止专用接收线程，主动关闭 socket 解除阻塞读取。"""
        self._disconnect()
        try:
            self.channel.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.channel.close()
        if self.thread.ident is not None:
            self.thread.join(timeout=3.0)
