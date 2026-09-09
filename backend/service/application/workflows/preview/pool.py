"""内存 Preview 进程监督；没有持久化 Run、上传目录或磁盘恢复依赖。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
import math
import json
import multiprocessing
from queue import Empty, Full
from threading import RLock
from time import monotonic

from backend.service.application.workflows.preview.session import PreviewSessionError
from backend.service.application.workflows.preview.worker import run_preview_worker


@dataclass
class _PreviewSlot:
    """独占一个串行 Worker，任务结束后复用模型而非新建进程。"""

    cancellation: object
    process: object = None
    requests: object = None
    responses: object = None
    replies: object = None
    busy: bool = False
    quarantined: bool = False
    deferred_cleanup: object = None


class PreviewSessionPool:
    """有界进程池，只向 SessionManager 交付实时控制事件。"""

    def __init__(self, *, settings, manager):
        """复用既有进程数量/业务期限，状态存放在注入的内存 manager。"""
        self.settings = settings
        self.manager = manager
        self._context = multiprocessing.get_context("spawn")
        self._lock = RLock()
        self._slots = [_PreviewSlot(self._context.Event()) for _ in range(settings.workflow_runtime.preview_worker_count)]
        self._executor = ThreadPoolExecutor(max_workers=len(self._slots), thread_name_prefix="preview-session-control")
        self._active = {}
        self._stopping = False

    def submit(self, session, request):
        """只登记容量和内存快照；拒绝时 manager 不发布 accepted。"""
        with self._lock:
            slot = next((s for s in self._slots if not s.busy), None)
            if self._stopping or slot is None:
                raise PreviewSessionError("preview_execution_capacity", 429)
            run_id = session.run["run_id"]
            message = {"session_id": session.session_id, "project_id": session.project_id,
                       "application_id": session.application_id, "run_id": run_id, "request": request}
            descriptors = {}
            try:
                for binding, raw_ids in request.get("input_ids", {}).items():
                    ids = raw_ids if isinstance(raw_ids, list) else [raw_ids]
                    if not 1 <= len(ids) <= 64:
                        raise ValueError("preview_input_file_count_invalid")
                    descriptors[binding] = []
                    for blob_id in ids:
                        descriptors[binding].append(self.manager.buffers.pin_descriptor(session.session_id, str(blob_id).replace("-", "")))
                self.manager.buffers.reserve(session.session_id, f"worker:{run_id}:request",
                                             len(json.dumps(request).encode()) + sum(item["byte_length"] * 3 for items in descriptors.values() for item in items))
            except ValueError as error:
                for items in descriptors.values():
                    for descriptor in items:
                        self.manager.buffers.unpin(session.session_id, descriptor["blob_id"])
                raise PreviewSessionError(str(error), 413) from error
            message["inputs"] = descriptors
            slot.busy = True
            slot.cancellation.clear()
            try:
                future = self._executor.submit(self._execute, slot, message)
            except Exception:
                slot.busy = False
                for items in descriptors.values():
                    for descriptor in items:
                        self.manager.buffers.unpin(session.session_id, descriptor["blob_id"])
                self.manager.buffers.release_reservations(session.session_id, f"worker:{run_id}:")
                raise
            self._active[run_id] = (slot, future)
            future.add_done_callback(lambda done: self._finished(run_id, slot))

    def _finished(self, run_id, slot):
        """真实执行结束后才归还容量。"""
        with self._lock:
            self._active.pop(run_id, None)
            slot.busy = slot.quarantined

    def cancel(self, run_id):
        """协作取消仅设 Event，不能提前宣布 cancelled。"""
        with self._lock:
            item = self._active.get(run_id)
            if item:
                item[0].cancellation.set()

    def _stop(self, slot):
        """仅终止本池拥有的进程，必须确认死亡后才能释放借用。"""
        if slot.process is not None and slot.process.is_alive():
            slot.cancellation.set()
            slot.process.terminate()
            slot.process.join(5)
            if slot.process.is_alive():
                slot.quarantined = True
                raise RuntimeError("preview_worker_did_not_exit")

    def _start(self, slot):
        """空闲活进程直接复用，死亡进程关闭旧通道后重建。"""
        if slot.process is not None and slot.process.is_alive():
            return
        self._close_slot(slot)
        slot.requests = self._context.Queue(maxsize=1)
        slot.responses = self._context.Queue(maxsize=1024)
        slot.replies = self._context.Queue(maxsize=1)
        slot.process = self._context.Process(target=run_preview_worker, kwargs={
            "settings_payload": self.settings.model_dump(mode="python"), "requests": slot.requests,
            "responses": slot.responses, "replies": slot.replies, "cancellation": slot.cancellation}, name="workflow-preview-session")
        slot.process.start()
        deadline = monotonic() + self.settings.workflow_runtime.model_startup_timeout_seconds
        while True:
            if slot.cancellation.is_set():
                self._stop(slot)
                raise PreviewSessionError("preview_cancelled_during_startup")
            if not slot.process.is_alive() or monotonic() >= deadline:
                raise RuntimeError("preview_worker_start_failed")
            try:
                kind, _ = slot.responses.get(timeout=.1)
                if kind != "ready":
                    raise RuntimeError("preview_worker_protocol_invalid")
                return
            except Empty:
                continue

    def _execute(self, slot, message):
        """控制线程独立等待 Worker，不借用 HTTP loop；节点 timeout 与连接无关。"""
        sid, rid = message["session_id"], message["run_id"]
        timed_out = False
        input_pins = [item["blob_id"] for items in message["inputs"].values() for item in items]
        input_sizes = {item["blob_id"]: item["byte_length"] for items in message["inputs"].values() for item in items}
        input_owned_bytes = 0
        writer_pins = set()
        published = set()
        borrowing_finished = False
        try:
            self._start(slot)
            timeout = message["request"].get("timeout_seconds") or self.settings.workflow_runtime.preview_default_timeout_seconds
            deadline = monotonic() + timeout
            slot.requests.put(message, timeout=2)
            cancel_started = None
            node_deadlines = {}
            while True:
                try:
                    kind, payload = slot.responses.get(timeout=.1)
                except Empty:
                    kind, payload = None, None
                if kind == "event":
                    self.manager.accept(sid, rid, payload["type"], payload["payload"])
                    if payload["type"].startswith(("display.", "value.")):
                        published.intersection_update(self.manager.buffers.live_ids(sid))
                elif kind == "memory":
                    reply = {"request_id": payload["request_id"]}
                    try:
                        if payload["action"] == "input-consumed":
                            blob = payload["blob_id"]
                            if blob not in input_pins:
                                raise ValueError("preview_input_lease_invalid")
                            size = payload["byte_length"]
                            if type(size) is not int or not 0 <= size <= input_sizes[blob] * 3:
                                raise ValueError("preview_input_length_invalid")
                            # Worker 已关闭附加映射，只保留其节点输入副本。
                            self.manager.buffers.release(sid, blob)
                            self.manager.buffers.unpin(sid, blob)
                            input_pins.remove(blob)
                            input_owned_bytes += size
                            self.manager.buffers.reserve(sid, f"worker:{rid}:request",
                                len(json.dumps(message["request"]).encode()) + input_owned_bytes + sum(input_sizes[key] * 3 for key in input_pins))
                            reply["result"] = {}
                        elif payload["action"] == "allocate":
                            # 释放中的会话不能继续分配结果。
                            self.manager.authorize(sid, None)
                            blob = self.manager.buffers.allocate(sid, payload["byte_length"], media_type=payload["media_type"])
                            reply["result"] = self.manager.buffers.writer_descriptor(sid, blob)
                            writer_pins.add(blob)
                        elif payload["action"] == "publish" and payload["blob_id"] in writer_pins:
                            reply["result"] = self.manager.buffers.publish_writer(sid, payload["blob_id"])
                            writer_pins.remove(payload["blob_id"])
                            published.add(payload["blob_id"])
                        elif payload["action"] == "reserve":
                            if payload["byte_length"]:
                                self.manager.authorize(sid, None)
                            key = f"worker:{rid}:{payload['key']}"
                            self.manager.buffers.reserve(sid, key, payload["byte_length"])
                            reply["result"] = {}
                        elif payload["action"] == "release":
                            blob = payload["blob_id"]
                            if blob not in published:
                                raise ValueError("preview_memory_protocol_invalid")
                            self.manager.buffers.release(sid, blob)
                            published.discard(blob)
                            reply["result"] = {}
                        else:
                            raise ValueError("preview_memory_protocol_invalid")
                    except ValueError as error:
                        reply["error"] = str(error)
                    slot.replies.put(reply, timeout=2)
                elif kind == "finished":
                    borrowing_finished = True
                    if timed_out:
                        payload["status"] = "timed_out"
                    self.manager.accept(sid, rid, "run.finished", payload)
                    return
                elif kind == "lifecycle":
                    invocation = payload.get("node_invocation_id")
                    if payload.get("message_type") == "node-ended":
                        node_deadlines.pop(invocation, None)
                    elif payload.get("message_type") == "node-started":
                        value = payload.get("deadline_monotonic")
                        grace = payload.get("kill_grace_seconds")
                        if isinstance(value, (float, int)) and math.isfinite(value) and isinstance(grace, (float, int)) and math.isfinite(grace) and grace >= 0:
                            node_deadlines[invocation] = (value, grace)
                elif kind is not None:
                    raise RuntimeError("preview_worker_protocol_invalid")
                if not slot.process.is_alive():
                    raise RuntimeError(f"preview_worker_exited:{slot.process.exitcode}")
                now = monotonic()
                due = [v for v in node_deadlines.values() if now >= v[0]]
                if now >= deadline or due:
                    timed_out = True
                    slot.cancellation.set()
                if slot.cancellation.is_set():
                    cancel_started = cancel_started or now
                    force_at = min(v[0] + v[1] for v in due) if due else cancel_started + 5
                    if now >= force_at:
                        self._stop(slot)
                        borrowing_finished = True
                        self.manager.accept(sid, rid, "run.finished", {"status": "timed_out" if timed_out else "cancelled"})
                        return
        except Exception as original_error:
            failure = original_error
            was_cancelled = slot.cancellation.is_set()
            try:
                self._stop(slot)
                borrowing_finished = True
            except Exception as stop_error:
                slot.quarantined = True
                failure = stop_error
                was_cancelled = timed_out = False
            self.manager.accept(sid, rid, "run.finished", {
                "status": "timed_out" if timed_out else "cancelled" if was_cancelled else "failed",
                "error": {"type": type(failure).__name__, "message": str(failure)[:1024]}})
        finally:
            # 正常 finished 保证 Worker 已退出本次借用；异常路径必须先确认进程死亡。
            def cleanup():
                """保留全部借用登记，隔离进程稍后退出时仍可完整回收。"""
                for blob in input_pins:
                    self.manager.buffers.release(sid, blob)
                    self.manager.buffers.unpin(sid, blob)
                for blob in writer_pins:
                    self.manager.buffers.release(sid, blob)
                    self.manager.buffers.unpin(sid, blob)
                for blob in published - self.manager.referenced_blobs(sid):
                    self.manager.buffers.release(sid, blob)
                self.manager.buffers.release_reservations(sid, f"worker:{rid}:")
            if borrowing_finished:
                cleanup()
            else:
                slot.deferred_cleanup = cleanup

    def reap(self):
        """隔离进程确认退出后回收借用；不在池锁内调用会话管理器。"""
        with self._lock:
            slots = [slot for slot in self._slots if slot.quarantined and slot.deferred_cleanup and not slot.process.is_alive()]
        for slot in slots:
            self._close_slot(slot)
            with self._lock:
                slot.quarantined = slot.busy = False

    def _close_slot(self, slot):
        """先退出进程再关闭队列，避免 feeder 因失去消费者无限 join。"""
        if slot.process is not None:
            if slot.process.is_alive():
                try:
                    slot.requests.put(None, timeout=.5)
                    slot.process.join(15)
                except Full:
                    pass
                self._stop(slot)
            slot.process.close()
        for queue in (slot.requests, slot.responses, slot.replies):
            if queue is not None:
                queue.cancel_join_thread()
                queue.close()
        slot.process = None
        if slot.deferred_cleanup is not None:
            slot.deferred_cleanup()
            slot.deferred_cleanup = None

    def close(self):
        """排空后释放池；未退出则失败，不能继续释放共享资源。"""
        with self._lock:
            self._stopping = True
            active = list(self._active.values())
            for slot, _ in active:
                slot.cancellation.set()
        _, pending = wait([future for _, future in active], timeout=30)
        if pending:
            raise RuntimeError("preview_workers_not_drained")
        self._executor.shutdown(wait=True)
        for slot in self._slots:
            self._close_slot(slot)
