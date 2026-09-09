"""编辑态 Preview 会话状态与事件归并；所有结果只存在于有界内存。"""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from threading import Event, RLock, Thread
from time import monotonic
from typing import Callable
from uuid import uuid4

from backend.contracts.workflows.preview_session import PREVIEW_SESSION_FORMAT, PREVIEW_TERMINAL_STATES
from backend.service.application.workflows.preview.buffers import PreviewBuffers, PreviewMemoryError


class PreviewSessionError(ValueError):
    """会话错误携带固定 code 和 HTTP status，不泄漏其他会话资源。"""

    def __init__(self, code: str, status: int = 409):
        """code 由协议定义，status 供 REST/WS 适配层统一处理。"""
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass
class PreviewSubscription:
    """一个浏览器订阅者的有界待发送控制队列。"""

    messages: deque = field(default_factory=deque)
    bytes: int = 0
    overflowed: bool = False
    closed: bool = False


@dataclass
class PreviewSession:
    """会话的最新状态，不保留无限运行或调用历史。"""

    session_id: str
    principal_id: str
    project_id: str
    application_id: str
    editor_session_id: str
    seq: int = 0
    run: dict | None = None
    requests: dict = field(default_factory=dict)
    nodes: dict = field(default_factory=dict)
    displays: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)
    subscriptions: list = field(default_factory=list)
    disconnected_at: float | None = field(default_factory=monotonic)
    released: bool = False
    state_bytes: int = 0


def _encoded_size(value: object) -> int:
    """按 UTF-8 JSON 计算控制数据字节，拒绝非有限数与非 JSON 对象。"""
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode())


class PreviewSessionManager:
    """单 API 进程拥有的会话表，Worker 只通过控制事件更新它。"""

    def __init__(self, *, buffers: PreviewBuffers | None = None, max_sessions: int = 8,
                 queue_items: int = 1024, queue_bytes: int = 4 * 1024**2):
        """依赖注入仅用于配置与测试；正式 Runtime 不引用本对象。"""
        self.epoch = uuid4().hex
        self.buffers = buffers or PreviewBuffers()
        self.buffers.require_registered_owner = True
        self.max_sessions = max_sessions
        self.queue_items = queue_items
        self.queue_bytes = queue_bytes
        self._sessions: dict[str, PreviewSession] = {}
        self._lock = RLock()
        self.pool = None
        self._closed = False
        self._maintenance_stop = Event()
        self._maintenance_thread = None
        self._deleting: set[tuple[str, str | None]] = set()

    def _check_document_available(self, project_id, application_id):
        """删除操作期间禁止受理新会话或运行，避免检查与删除之间出现竞态。"""
        if (project_id, None) in self._deleting or (project_id, application_id) in self._deleting or (application_id is None and any(project == project_id for project, _ in self._deleting)):
            raise PreviewSessionError("preview_document_deleting")

    @contextmanager
    def deleting_document(self, project_id, application_id=None):
        """只占用 Preview 受理门；文件删除期间不持有事件归并锁。"""
        from backend.service.application.errors import ResourceInUseError
        key = (project_id, application_id)
        with self._lock:
            self._check_document_available(project_id, application_id)
            matches = [s for s in self._sessions.values() if s.project_id == project_id and (application_id is None or s.application_id == application_id)]
            if any(s.run and s.run["state"] not in PREVIEW_TERMINAL_STATES for s in matches):
                raise ResourceInUseError("仍有预览正在执行，结束后才能删除", details={"project_id": project_id, "application_id": application_id})
            self._deleting.add(key)
            for session in matches:
                self.release(session.session_id, session.principal_id)
        try:
            yield
        finally:
            with self._lock:
                self._deleting.discard(key)

    def start(self) -> None:
        """装配后开始空会话/断线回收，不把进度静默当作任务超时。"""
        if self._maintenance_thread is not None:
            return

        def maintain():
            while not self._maintenance_stop.wait(1):
                self.expire()
                if self.pool is not None:
                    self.pool.reap()

        self._maintenance_thread = Thread(target=maintain, name="preview-session-expiry", daemon=True)
        self._maintenance_thread.start()

    def create(self, *, principal_id: str, project_id: str, application_id: str, editor_session_id: str) -> dict:
        """只接受路由已授权的项目；容量满不驱逐其他活跃页面。"""
        with self._lock:
            self._check_document_available(project_id, application_id)
            if self._closed or len(self._sessions) >= self.max_sessions:
                raise PreviewSessionError("preview_session_capacity", 429)
            session = PreviewSession(uuid4().hex, principal_id, project_id, application_id, editor_session_id)
            self._sessions[session.session_id] = session
            self.buffers.register_owner(session.session_id)
            return {"format_id": PREVIEW_SESSION_FORMAT, "session_id": session.session_id,
                    "epoch": self.epoch, "memory_limit_bytes": self.buffers.session_limit}

    def _get(self, session_id: str, principal_id: str | None = None) -> PreviewSession:
        """不存在、已释放或其他 owner 一律不可见。"""
        session = self._sessions.get(session_id)
        if session is None or session.released or principal_id is not None and session.principal_id != principal_id:
            raise PreviewSessionError("preview_session_expired", 404)
        return session

    def authorize(self, session_id: str, principal_id: str, project_ids: tuple | list = ()) -> PreviewSession:
        """REST/WS 均检查 owner 和最新项目权限。"""
        with self._lock:
            session = self._get(session_id, principal_id)
            if project_ids and session.project_id not in project_ids:
                raise PreviewSessionError("preview_session_expired", 404)
            return session

    def _envelope(self, session: PreviewSession, kind: str, payload: dict) -> dict:
        """消息独立于业务输出，序号只由父进程生成。"""
        return {"format_id": PREVIEW_SESSION_FORMAT, "session_id": session.session_id,
                "epoch": self.epoch, "run_id": session.run.get("run_id") if session.run else None,
                "document_revision": session.run.get("document_revision") if session.run else None,
                "seq": session.seq, "type": kind, "payload": payload}

    def _publish(self, session: PreviewSession, kind: str, payload: dict) -> dict:
        """先形成可恢复状态，再向有界订阅队列交付；慢客户端不会阻塞执行。"""
        session.seq += 1
        event = self._envelope(session, kind, deepcopy(payload))
        size = _encoded_size(event)
        for sub in session.subscriptions:
            if sub.closed or sub.overflowed:
                continue
            if kind == "node.progress":
                identity = payload.get("invocation_id")
                # 只合并同一次调用的进度，开始/结束和错误不可静默删除。
                for old in tuple(sub.messages):
                    if old[0]["type"] == kind and old[0]["payload"].get("invocation_id") == identity:
                        sub.messages.remove(old)
                        sub.bytes -= old[1]
            if len(sub.messages) >= self.queue_items or sub.bytes + size > self.queue_bytes:
                sub.messages.clear()
                sub.bytes = 0
                sub.overflowed = True
            else:
                sub.messages.append((event, size))
                sub.bytes += size
        try:
            self.buffers.reserve(session.session_id, "state:queues", sum(sub.bytes for sub in session.subscriptions))
        except PreviewMemoryError:
            # 快照已经归并成功；慢订阅者丢弃队列后重连，不中断业务执行。
            for sub in session.subscriptions:
                sub.messages.clear()
                sub.bytes = 0
                sub.overflowed = True
            self.buffers.reserve(session.session_id, "state:queues", 0)
        return event

    def subscribe(self, session_id: str, principal_id: str) -> tuple[PreviewSubscription, dict]:
        """同一把锁内登记订阅并创建快照，避免快照与 live 之间丢事件。"""
        with self._lock:
            session = self._get(session_id, principal_id)
            if len(session.subscriptions) >= 4:
                raise PreviewSessionError("preview_subscriber_capacity", 429)
            sub = PreviewSubscription()
            session.subscriptions.append(sub)
            session.disconnected_at = None
            snapshot = self._envelope(session, "session.snapshot", {
                "watermark": session.seq, "run": session.run,
                "nodes": list(session.nodes.values()), "displays": list(session.displays.values()), "values": list(session.values.values())})
            return sub, deepcopy(snapshot)

    def take(self, sub: PreviewSubscription) -> dict | None:
        """WS 适配层非阻塞读取，发送 await 不能持有状态锁。"""
        with self._lock:
            if not sub.messages:
                return None
            event, size = sub.messages.popleft()
            sub.bytes -= size
            session = self._sessions.get(event["session_id"])
            if session is not None:
                self.buffers.reserve(session.session_id, "state:queues", sum(item.bytes for item in session.subscriptions))
            return event

    def unsubscribe(self, session_id: str, sub: PreviewSubscription) -> None:
        """最后一个订阅者退出才启动宽限，重复关闭幂等。"""
        with self._lock:
            sub.closed = True
            sub.messages.clear()
            sub.bytes = 0
            session = self._sessions.get(session_id)
            if session and sub in session.subscriptions:
                session.subscriptions.remove(sub)
                if not session.subscriptions:
                    session.disconnected_at = monotonic()
                self.buffers.reserve(session.session_id, "state:queues", sum(item.bytes for item in session.subscriptions))

    def submit(self, session_id: str, principal_id: str, request: dict, start: Callable) -> dict:
        """受理和 request_id 去重；容量拒绝时不产生伪 accepted 事件。"""
        from backend.service.application.workflows.preview.values import _measure
        try:
            _measure(request, [100_000])
            serialized = json.dumps(request, sort_keys=True, allow_nan=False, separators=(",", ":"))
        except (ValueError, TypeError, RecursionError) as error:
            raise PreviewSessionError("preview_snapshot_invalid", 413) from error
        if len(serialized.encode()) > 8 * 1024**2:
            raise PreviewSessionError("preview_snapshot_capacity", 413)
        digest = hashlib.sha256(serialized.encode()).hexdigest()
        request_id = str(request["request_id"])
        with self._lock:
            session = self._get(session_id, principal_id)
            previous = session.requests.get(request_id)
            self._check_document_available(session.project_id, session.application_id)
            if previous:
                if previous[0] != digest:
                    raise PreviewSessionError("preview_request_conflict")
                return dict(previous[1])
            if len(session.requests) >= 256:
                raise PreviewSessionError("preview_request_capacity", 429)
            if session.run and session.run["state"] not in PREVIEW_TERMINAL_STATES:
                raise PreviewSessionError("preview_session_busy")
            if not session.subscriptions:
                raise PreviewSessionError("preview_subscription_required")
            run = {"run_id": uuid4().hex, "state": "accepted", "document_revision": request["document_revision"],
                   "outputs": {}, "error": None}
            old_run, old_nodes, old_displays, old_size = session.run, session.nodes, session.displays, session.state_bytes
            node_ids = {node["node_id"] for node in request.get("template", {}).get("nodes", [])}
            run["node_ids"] = sorted(node_ids)
            retained = {key: {**value, "stale": True} for key, value in old_displays.items() if value.get("node_id") in node_ids}
            retained_size = sum(_encoded_size(value) for value in retained.values())
            session.run, session.nodes, session.displays, session.state_bytes = run, {}, retained, retained_size
            try:
                self.buffers.reserve(session_id, "state:run", _encoded_size(run))
                self.buffers.reserve(session_id, "state:current", retained_size)
                # start 仅登记容量/提交 Future，不得同步执行图；Worker 归并需等本锁释放。
                start(session, deepcopy(request))
            except Exception:
                session.run, session.nodes, session.displays, session.state_bytes = old_run, old_nodes, old_displays, old_size
                self.buffers.reserve(session_id, "state:run", _encoded_size(old_run) if old_run else 0)
                self.buffers.reserve(session_id, "state:current", old_size)
                raise
            retained_blobs = _blob_ids(list(retained.values()))
            for blob_id in _blob_ids(old_run) - retained_blobs:
                self.buffers.release(session_id, blob_id)
            for value in session.values.values():
                for blob_id in _blob_ids(value) - retained_blobs:
                    self.buffers.release(session_id, blob_id)
            session.values.clear()
            for display in old_displays.values():
                for blob_id in _blob_ids(display) - retained_blobs:
                    self.buffers.release(session_id, blob_id)
            reply = {"session_id": session_id, "run_id": run["run_id"], "state": "accepted", "epoch": self.epoch}
            session.requests[request_id] = (digest, reply)
            self._publish(session, "run.accepted", run)
            return dict(reply)

    def accept(self, session_id: str, run_id: str, kind: str, payload: dict) -> bool:
        """按当前运行归并节点事件，过期运行和终态后的逆向消息不能覆盖页面。"""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.released or not session.run or session.run["run_id"] != run_id:
                return False
            terminal = session.run["state"] in PREVIEW_TERMINAL_STATES
            if terminal and kind not in {"display.updated", "display.unavailable"}:
                return False
            payload = deepcopy(payload)
            size = _encoded_size(payload)
            if size > self.queue_bytes:
                raise PreviewSessionError("preview_event_capacity", 413)
            if kind == "run.started":
                if session.run["state"] != "accepted":
                    return False
                session.run["state"] = "running"
            elif kind == "run.finished":
                state = payload.get("status")
                if state not in PREVIEW_TERMINAL_STATES:
                    raise PreviewSessionError("preview_state_invalid")
                if state != "succeeded":
                    for node in list(session.nodes.values()):
                        if node.get("status") == "running":
                            self.accept(session_id, run_id, "node.finished", {**node, "status": state, "error_details": payload.get("error") or {}})
                self.buffers.reserve(session_id, "state:run", size)
                session.run.update(state=state, outputs=payload.get("outputs", {}), error=payload.get("error"))
            elif kind.startswith("node."):
                key = str(payload.get("invocation_id", ""))
                if not key or not payload.get("node_id"):
                    raise PreviewSessionError("preview_node_identity_invalid")
                old = session.nodes.get(key)
                if old and old.get("status") in {*PREVIEW_TERMINAL_STATES, "skipped"}:
                    return False
                merged = {**(old or {}), **payload}
                # 每节点保留最新完成调用和仍在执行的调用，长循环不累计历史。
                if payload.get("status") in {*PREVIEW_TERMINAL_STATES, "skipped"}:
                    for previous_key, previous in list(session.nodes.items()):
                        if previous_key != key and previous.get("node_id") == payload["node_id"] and previous.get("status") in {*PREVIEW_TERMINAL_STATES, "skipped"}:
                            session.state_bytes -= _encoded_size(previous)
                            del session.nodes[previous_key]
                next_bytes = session.state_bytes - (_encoded_size(old) if old else 0) + _encoded_size(merged)
                if len(session.nodes) >= 100_000 and key not in session.nodes or next_bytes > 16 * 1024**2:
                    raise PreviewSessionError("preview_state_capacity", 413)
                self.buffers.reserve(session_id, "state:current", next_bytes)
                session.nodes[key] = merged
                session.state_bytes = next_bytes
            elif kind in {"display.updated", "display.unavailable", "value.updated"}:
                payload["revision"] = session.seq + 1
                size = _encoded_size(payload)
                key = f"{payload.get('node_id')}:{payload.get('output_port')}"
                destination = session.values if kind == "value.updated" else session.displays
                old = destination.get(key)
                if kind == "display.unavailable" and old:
                    payload = {**old, **payload, "stale": True}
                    size = _encoded_size(payload)
                next_bytes = session.state_bytes - (_encoded_size(old) if old else 0) + size
                if next_bytes > 16 * 1024**2:
                    raise PreviewSessionError("preview_state_capacity", 413)
                self.buffers.reserve(session_id, "state:current", next_bytes)
                destination[key] = payload
                session.state_bytes = next_bytes
                if old:
                    for blob_id in _blob_ids(old) - self.referenced_blobs(session_id):
                        self.buffers.release(session_id, blob_id)
            else:
                raise PreviewSessionError("preview_event_invalid")
            self._publish(session, kind, payload)
            return True

    def release(self, session_id: str, principal_id: str) -> None:
        """显式释放不等待断线宽限，取消活动任务但不提前销毁进程借用。"""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or session.principal_id != principal_id:
                return
            session.released = True
            if self.pool is not None and session.run:
                self.pool.cancel(session.run["run_id"])
            for sub in session.subscriptions:
                sub.closed = True
                sub.messages.clear()
                sub.bytes = 0
            self.buffers.release_owner(session_id)
            self.buffers.release_reservations(session_id, "state:")
            del self._sessions[session_id]

    def referenced_blobs(self, session_id: str) -> set[str]:
        """仅回收未被当前显示引用的发布块，避免编码途中失败留下孤立内存。"""
        with self._lock:
            session = self._sessions.get(session_id)
            return _blob_ids([*session.displays.values(), *session.values.values(), session.run]) if session else set()

    def expire(self, *, now: float | None = None) -> None:
        """连接宽限与业务 timeout 分开；没有 progress 不能导致误判。"""
        with self._lock:
            tick = monotonic() if now is None else now
            for session in list(self._sessions.values()):
                if session.disconnected_at is not None and tick - session.disconnected_at >= 60:
                    self.release(session.session_id, session.principal_id)
            self.buffers.expire_uploads(now=tick)

    def close(self) -> None:
        """先停止/排空 Worker，最后关闭内存映射。"""
        with self._lock:
            self._closed = True
        self._maintenance_stop.set()
        if self._maintenance_thread is not None:
            self._maintenance_thread.join(2)
        if self.pool is not None:
            self.pool.close()
        with self._lock:
            for session in list(self._sessions.values()):
                self.release(session.session_id, session.principal_id)
            self.buffers.close()


def _blob_ids(value):
    """从受控显示描述中提取 blob，替换旧显示时释放且不遍历任意执行对象。"""
    if isinstance(value, dict):
        found = {value["blob_id"]} if value.get("transport_kind") == "preview-memory" and value.get("blob_id") else set()
        for item in value.values():
            found.update(_blob_ids(item))
        return found
    if isinstance(value, list):
        return set().union(*(_blob_ids(item) for item in value))
    return set()
