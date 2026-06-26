"""backend-worker 本地健康心跳。"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from typing import Any


BACKEND_WORKER_HEALTH_DIRNAME = "_worker_health"
BACKEND_WORKER_HEALTH_FILENAME = "backend-worker.json"
DEFAULT_BACKEND_WORKER_HEARTBEAT_INTERVAL_SECONDS = 2.0
DEFAULT_BACKEND_WORKER_STALE_AFTER_SECONDS = 15.0


@dataclass(frozen=True)
class BackendWorkerHeartbeatInfo:
    """描述 backend-worker 心跳写入所需的稳定信息。

    字段：
    - app_name：worker 进程名称。
    - app_version：worker 进程版本。
    - workspace_dir：worker 工作目录。
    - queue_root_dir：本地队列根目录。
    - enabled_consumer_kinds：当前 worker 启用的 consumer kind。
    - max_concurrent_tasks：当前 worker 最大并发任务数。
    - poll_interval_seconds：当前 worker 空闲轮询间隔秒数。
    """

    app_name: str
    app_version: str
    workspace_dir: Path
    queue_root_dir: Path
    enabled_consumer_kinds: tuple[str, ...]
    max_concurrent_tasks: int
    poll_interval_seconds: float


class BackendWorkerHeartbeat:
    """在后台线程中维护 backend-worker 本地心跳文件。"""

    def __init__(
        self,
        *,
        info: BackendWorkerHeartbeatInfo,
        interval_seconds: float = DEFAULT_BACKEND_WORKER_HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        """初始化 worker 心跳写入器。

        参数：
        - info：写入心跳文件所需的 worker 运行信息。
        - interval_seconds：两次心跳写入之间的间隔秒数。
        """

        self.info = info
        self.interval_seconds = max(0.5, float(interval_seconds))
        self._started_at = datetime.now(UTC).isoformat()
        self._stop_event = Event()
        self._thread: Thread | None = None

    @property
    def heartbeat_path(self) -> Path:
        """返回当前 worker 心跳文件路径。"""

        return build_backend_worker_health_path(self.info.queue_root_dir)

    def start(self) -> None:
        """启动心跳后台线程。"""

        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._write_snapshot(status="running")
        self._thread = Thread(
            target=self._run,
            name="backend-worker-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止心跳后台线程，并写入 stopped 状态。"""

        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.5, self.interval_seconds * 2))
            self._thread = None
        self._write_snapshot(status="stopped")

    def _run(self) -> None:
        """持续写入 worker 运行心跳。"""

        while not self._stop_event.wait(self.interval_seconds):
            self._write_snapshot(status="running")

    def _write_snapshot(self, *, status: str) -> None:
        """把当前 worker 状态写入本地心跳文件。"""

        heartbeat_at = datetime.now(UTC).isoformat()
        payload: dict[str, object] = {
            "status": status,
            "health": status,
            "app_name": self.info.app_name,
            "app_version": self.info.app_version,
            "worker_id": self.info.app_name,
            "process_id": os.getpid(),
            "python_executable": sys.executable,
            "entrypoint": "python -m backend.workers.main",
            "started_at": self._started_at,
            "heartbeat_at": heartbeat_at,
            "workspace_dir": str(self.info.workspace_dir),
            "queue_root_dir": str(self.info.queue_root_dir),
            "enabled_consumer_kinds": list(self.info.enabled_consumer_kinds),
            "enabled_consumer_count": len(self.info.enabled_consumer_kinds),
            "max_concurrent_tasks": self.info.max_concurrent_tasks,
            "poll_interval_seconds": self.info.poll_interval_seconds,
        }
        _write_json_atomic(self.heartbeat_path, payload)


def build_backend_worker_health_path(queue_root_dir: str | Path) -> Path:
    """根据本地队列根目录构造 backend-worker 心跳文件路径。"""

    return Path(queue_root_dir).resolve() / BACKEND_WORKER_HEALTH_DIRNAME / BACKEND_WORKER_HEALTH_FILENAME


def read_backend_worker_health_summary(
    *,
    queue_root_dir: str | Path,
    stale_after_seconds: float = DEFAULT_BACKEND_WORKER_STALE_AFTER_SECONDS,
) -> dict[str, object]:
    """读取 backend-worker 心跳并转换为设置页诊断摘要。

    参数：
    - queue_root_dir：backend-service 和 backend-worker 共享的本地队列根目录。
    - stale_after_seconds：心跳超过该秒数后判定为 stale。

    返回：
    - dict[str, object]：backend-worker 诊断摘要。
    """

    health_path = build_backend_worker_health_path(queue_root_dir)
    base_summary: dict[str, object] = {
        "status": "external",
        "entrypoint": "python -m backend.workers.main",
        "health_file": str(health_path),
    }
    if not health_path.exists():
        return {
            **base_summary,
            "health": "offline",
            "reason": "heartbeat_missing",
        }

    try:
        payload = _read_json_dict(health_path)
    except Exception as error:  # pragma: no cover - 文件损坏时用于诊断页面暴露
        return {
            **base_summary,
            "health": "unknown",
            "reason": "heartbeat_unreadable",
            "error": str(error),
        }

    heartbeat_at = _read_optional_str(payload, "heartbeat_at")
    age_seconds = _calculate_age_seconds(heartbeat_at)
    reported_health = _read_optional_str(payload, "health") or _read_optional_str(payload, "status") or "unknown"
    health = _resolve_worker_health(
        reported_health=reported_health,
        age_seconds=age_seconds,
        stale_after_seconds=stale_after_seconds,
    )
    return {
        **base_summary,
        **payload,
        "health": health,
        "reported_health": reported_health,
        "heartbeat_age_seconds": age_seconds,
        "stale_after_seconds": stale_after_seconds,
    }


def _resolve_worker_health(
    *,
    reported_health: str,
    age_seconds: float | None,
    stale_after_seconds: float,
) -> str:
    """结合心跳上报状态和时间差判断 worker 健康状态。"""

    normalized = reported_health.strip().lower()
    if normalized == "stopped":
        return "stopped"
    if age_seconds is None:
        return "unknown"
    if age_seconds > max(1.0, stale_after_seconds):
        return "stale"
    if normalized in {"running", "ok", "healthy"}:
        return "running"
    return normalized or "unknown"


def _calculate_age_seconds(value: str | None) -> float | None:
    """计算 ISO 时间距离当前时间的秒数。"""

    if not value:
        return None
    try:
        heartbeat_at = datetime.fromisoformat(value)
    except ValueError:
        return None
    if heartbeat_at.tzinfo is None:
        heartbeat_at = heartbeat_at.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - heartbeat_at).total_seconds())


def _read_json_dict(path: Path) -> dict[str, object]:
    """读取 JSON 文件并确认顶层是对象。"""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("backend-worker health 文件顶层必须是 JSON object")
    return {str(key): value for key, value in payload.items()}


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    """原子写入 JSON 文件，避免诊断接口读到半截内容。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _read_optional_str(payload: dict[str, Any], key: str) -> str | None:
    """从字典读取可选字符串字段。"""

    value = payload.get(key)
    return value if isinstance(value, str) and value.strip() else None
