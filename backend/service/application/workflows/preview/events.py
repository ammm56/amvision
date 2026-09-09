"""既有执行器事件到编辑器事件的适配，不参与正式 Runtime 广播。"""

from __future__ import annotations

from threading import RLock, get_ident
from uuid import uuid4
import math
from datetime import datetime, timezone


class PreviewNodeEvents:
    """将节点执行事件关联到单次调用，不用整图终态推断节点状态。"""

    def __init__(self, emit, node_ids=()):
        """emit 接收有界 JSON 控制消息，由父进程分配最终 seq。"""
        self.emit = emit
        self._lock = RLock()
        self.node_ids = set(node_ids)
        self._active: dict[int, list[dict]] = {}

    def current(self) -> dict:
        """显示和 progress 与当前执行线程中的节点使用同一个调用身份。"""
        with self._lock:
            stack = self._active.get(get_ident(), [])
            return dict(stack[-1]) if stack else {}

    def progress(self, *, completed=None, total=None, message=None) -> None:
        """只报告节点真实提供的进度，不用耗时推算百分比。"""
        current = self.current()
        if not current:
            return
        for value in (completed, total):
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise ValueError("preview_progress_invalid")
        if total is not None and completed is not None and completed > total:
            raise ValueError("preview_progress_invalid")
        self.emit("node.progress", {**current, "status": "running", "completed": completed,
                                    "total": total, "message": str(message or "")[:256]})

    def __call__(self, event: dict) -> None:
        """适配现有 started/completed/failed 事件；保留其有界端口摘要。"""
        kind = event.get("event_type")
        if kind not in {"node.started", "node.completed", "node.failed", "node.skipped"}:
            return
        payload = dict(event.get("payload") or {})
        event_node_id = str(payload.get("node_id", ""))
        node_id = event_node_id
        if node_id not in self.node_ids and payload.get("for_each_node_id"):
            matches = [known for known in self.node_ids if event_node_id.endswith(f".{known}")]
            if matches:
                node_id = max(matches, key=len)
        scope = {key: payload[key] for key in (
            "parallel_start_node_id", "parallel_branch_index", "for_each_start_node_id",
            "iteration_index", "loop_index", "selection_start_node_id", "selection_branch", "scope_path",
            "for_each_node_id", "for_each_iteration_index"
        ) if key in payload}
        with self._lock:
            stack = self._active.setdefault(get_ident(), [])
            if kind == "node.started":
                scope_path = [*stack[-1]["scope_path"], scope] if stack else [scope]
                identity = {"node_id": node_id, "event_node_id": event_node_id,
                            "invocation_id": uuid4().hex, "scope_path": scope_path,
                            "started_at": datetime.now(timezone.utc).isoformat()}
                stack.append(identity)
            else:
                identity = next((item for item in reversed(stack) if item["event_node_id"] == event_node_id),
                                {"node_id": node_id, "invocation_id": uuid4().hex, "scope_path": [scope]})
            payload.update(identity,
                           status={"node.started": "running", "node.completed": "succeeded",
                                   "node.failed": "failed", "node.skipped": "skipped"}[kind])
            if kind == "node.failed":
                payload["status"] = {"operation_timeout": "timed_out", "operation_cancelled": "cancelled"}.get(
                    (payload.get("error_details") or {}).get("code"), "failed")
            self.emit("node.started" if kind == "node.started" else "node.finished", payload)
            if kind != "node.started" and identity in stack:
                stack.remove(identity)
            if not stack:
                self._active.pop(get_ident(), None)
