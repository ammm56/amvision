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
from uuid import uuid4


BACKEND_WORKER_HEALTH_DIRNAME = "_worker_health"
BACKEND_WORKER_HEALTH_FILE_PREFIX = "backend-worker"
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

        return build_backend_worker_profile_health_path(
            self.info.queue_root_dir,
            worker_name=self.info.app_name,
        )

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
    """根据本地队列根目录构造默认 backend-worker 心跳文件路径。"""

    return _build_backend_worker_health_dir(queue_root_dir) / f"{BACKEND_WORKER_HEALTH_FILE_PREFIX}.json"


def build_backend_worker_profile_health_path(
    queue_root_dir: str | Path,
    *,
    worker_name: str,
) -> Path:
    """根据 worker 名称构造独立心跳文件路径。

    参数：
    - queue_root_dir：backend-service 和 backend-worker 共享的本地队列根目录。
    - worker_name：worker profile 展示名称，发布目录里每个 profile 保持唯一。

    返回：
    - Path：当前 worker 独占的心跳文件路径。
    """

    worker_key = _normalize_worker_health_key(worker_name)
    return _build_backend_worker_health_dir(queue_root_dir) / f"{BACKEND_WORKER_HEALTH_FILE_PREFIX}-{worker_key}.json"


def _build_backend_worker_health_dir(queue_root_dir: str | Path) -> Path:
    """返回 backend-worker 心跳目录。"""

    return Path(queue_root_dir).resolve() / BACKEND_WORKER_HEALTH_DIRNAME


def _normalize_worker_health_key(worker_name: str) -> str:
    """把 worker 名称转换成适合文件名的稳定 key。"""

    normalized_chars: list[str] = []
    for char in worker_name.strip().lower():
        if char.isalnum():
            normalized_chars.append(char)
            continue
        if normalized_chars and normalized_chars[-1] != "-":
            normalized_chars.append("-")
    normalized = "".join(normalized_chars).strip("-")
    return normalized or "worker"


def _list_backend_worker_health_paths(health_dir: Path) -> list[Path]:
    """列出当前队列根目录下所有 backend-worker 心跳文件。"""

    if not health_dir.exists():
        return []
    profile_paths = sorted(
        path
        for path in health_dir.glob(f"{BACKEND_WORKER_HEALTH_FILE_PREFIX}-*.json")
        if path.is_file()
    )
    if profile_paths:
        return profile_paths
    default_path = health_dir / f"{BACKEND_WORKER_HEALTH_FILE_PREFIX}.json"
    return [default_path] if default_path.is_file() else []


def _read_backend_worker_health_file(
    health_path: Path,
    *,
    stale_after_seconds: float,
) -> dict[str, object]:
    """读取单个 backend-worker 心跳文件。"""

    base_summary: dict[str, object] = {
        "health_file": str(health_path),
        "worker_key": health_path.stem.removeprefix(f"{BACKEND_WORKER_HEALTH_FILE_PREFIX}-"),
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
    reported_health = (
        _read_optional_str(payload, "health")
        or _read_optional_str(payload, "status")
        or "unknown"
    )
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


def _resolve_backend_worker_group_health(workers: list[dict[str, object]]) -> str:
    """根据多个 worker 心跳聚合 backend-worker 总健康状态。"""

    if not workers:
        return "offline"
    worker_healths = {
        str(worker.get("health") or "unknown").strip().lower()
        for worker in workers
    }
    if worker_healths == {"running"}:
        return "running"
    if "running" in worker_healths:
        return "degraded"
    if worker_healths == {"stopped"}:
        return "stopped"
    if "stale" in worker_healths:
        return "stale"
    if "unknown" in worker_healths:
        return "unknown"
    return sorted(worker_healths)[0] if worker_healths else "unknown"


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

    health_dir = _build_backend_worker_health_dir(queue_root_dir)
    base_summary: dict[str, object] = {
        "status": "external",
        "entrypoint": "python -m backend.workers.main",
        "health_dir": str(health_dir),
    }
    heartbeat_paths = _list_backend_worker_health_paths(health_dir)
    if not heartbeat_paths:
        return {
            **base_summary,
            "health": "offline",
            "reason": "heartbeat_missing",
            "worker_count": 0,
            "workers": [],
        }

    workers = [
        _read_backend_worker_health_file(
            health_path,
            stale_after_seconds=stale_after_seconds,
        )
        for health_path in heartbeat_paths
    ]
    health = _resolve_backend_worker_group_health(workers)
    running_workers = [worker for worker in workers if worker.get("health") == "running"]
    stale_workers = [worker for worker in workers if worker.get("health") == "stale"]
    stopped_workers = [worker for worker in workers if worker.get("health") == "stopped"]
    unreadable_workers = [
        worker for worker in workers if worker.get("reason") == "heartbeat_unreadable"
    ]
    primary_worker = running_workers[0] if running_workers else workers[0]
    return {
        **base_summary,
        **{
            key: value
            for key, value in primary_worker.items()
            if key not in {"health", "health_file"}
        },
        "health": health,
        "stale_after_seconds": stale_after_seconds,
        "worker_count": len(workers),
        "running_count": len(running_workers),
        "stale_count": len(stale_workers),
        "stopped_count": len(stopped_workers),
        "unreadable_count": len(unreadable_workers),
        "health_files": [str(path) for path in heartbeat_paths],
        "workers": workers,
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
    temp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _read_optional_str(payload: dict[str, Any], key: str) -> str | None:
    """从字典读取可选字符串字段。"""

    value = payload.get(key)
    return value if isinstance(value, str) and value.strip() else None
