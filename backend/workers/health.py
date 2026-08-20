"""基于当前 Topology epoch 的 backend-worker 健康心跳。"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Literal

from pydantic import ValidationError

from backend.workers.contracts import (
    WORKER_HEARTBEAT_FORMAT_ID,
    BackendWorkerLaunchBundle,
    BackendWorkerRuntimeLayout,
    WorkerHeartbeatRecord,
    WorkerTopologyManifest,
    load_worker_heartbeat,
    load_worker_topology_manifest,
    load_worker_topology_pointer,
    utc_now,
    write_worker_contract,
)


DEFAULT_BACKEND_WORKER_HEARTBEAT_INTERVAL_SECONDS = 2.0
DEFAULT_BACKEND_WORKER_STALE_AFTER_SECONDS = 15.0


@dataclass(frozen=True)
class BackendWorkerHeartbeatInfo:
    """描述单个 Worker Profile 心跳写入所需的稳定信息。"""

    launch_bundle: BackendWorkerLaunchBundle
    app_version: str
    workspace_dir: Path
    queue_root_dir: Path


class BackendWorkerHeartbeat:
    """在受监督线程中维护当前 epoch 的单 Profile 心跳。"""

    def __init__(
        self,
        *,
        info: BackendWorkerHeartbeatInfo,
        interval_seconds: float = DEFAULT_BACKEND_WORKER_HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        """初始化 Worker 心跳写入器。"""

        self.info = info
        self.interval_seconds = max(0.5, float(interval_seconds))
        self._process_started_at = utc_now()
        self._status: Literal[
            "starting", "running", "stopping", "stopped", "failed"
        ] = "starting"
        self._failure_message: str | None = None
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._state_lock = Lock()
        self._thread_error: BaseException | None = None

    @property
    def heartbeat_path(self) -> Path:
        """返回当前 epoch/Profile 的唯一心跳路径。"""

        context = self.info.launch_bundle.context
        profile = self.info.launch_bundle.profile
        return context.runtime_layout.profile_heartbeat_path(
            context.topology_epoch_id,
            profile.profile_id,
        )

    def start(self) -> None:
        """启动心跳线程，并先同步写入 starting 状态。"""

        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("backend-worker 心跳线程已经启动")
        self._stop_event.clear()
        with self._state_lock:
            self._thread_error = None
            self._status = "starting"
            self._failure_message = None
        self._write_snapshot()
        self._thread = Thread(
            target=self._run,
            name=(
                f"backend-worker-heartbeat-{self.info.launch_bundle.profile.profile_id}"
            ),
            daemon=True,
        )
        self._thread.start()

    def mark_running(self) -> None:
        """在消费者完成装配后发布 running 状态。"""

        self._set_status("running")

    def mark_failed(self, error: BaseException) -> None:
        """记录 Worker 主循环失败并立即刷新心跳。"""

        self._set_status(
            "failed",
            failure_message=str(error) or error.__class__.__name__,
        )

    def assert_healthy(self) -> None:
        """确保心跳线程仍在正常工作，否则让 Worker 主循环失败退出。"""

        with self._state_lock:
            error = self._thread_error
            thread = self._thread
        if error is not None:
            raise RuntimeError("backend-worker 心跳写入线程异常退出") from error
        if thread is None or not thread.is_alive():
            raise RuntimeError("backend-worker 心跳写入线程意外停止")

    def stop(self) -> None:
        """停止心跳线程，并尽力写入 stopped 状态。"""

        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.5, self.interval_seconds * 2))
        with self._state_lock:
            self._thread = None
            previous_status = self._status
        if previous_status != "failed":
            self._set_status("stopped")

    def _set_status(
        self,
        status: Literal["starting", "running", "stopping", "stopped", "failed"],
        *,
        failure_message: str | None = None,
    ) -> None:
        """同步更新并刷新当前 Profile 状态。"""

        with self._state_lock:
            self._status = status
            self._failure_message = failure_message
        self._write_snapshot()

    def _run(self) -> None:
        """持续刷新心跳；任何写入异常都交回主循环处理。"""

        try:
            while not self._stop_event.wait(self.interval_seconds):
                self._assert_active_topology()
                self._write_snapshot()
        except BaseException as error:  # noqa: BLE001 - 线程故障必须原样交给主循环
            with self._state_lock:
                self._thread_error = error
            self._stop_event.set()

    def _assert_active_topology(self) -> None:
        """确认当前进程仍属于唯一激活且可运行的 Topology。"""

        bundle = self.info.launch_bundle
        context = bundle.context
        pointer = load_worker_topology_pointer(
            context.runtime_layout.active_topology_path
        )
        topology = load_worker_topology_manifest(
            context.runtime_layout.topology_manifest_path(context.topology_epoch_id)
        )
        expected_identity = (
            context.topology_id,
            context.topology_generation,
            context.topology_epoch_id,
        )
        if (
            pointer.topology_id,
            pointer.topology_generation,
            pointer.topology_epoch_id,
        ) != expected_identity:
            raise RuntimeError("backend-worker 已不属于当前 active Topology")
        if (
            topology.topology_id,
            topology.topology_generation,
            topology.topology_epoch_id,
        ) != expected_identity:
            raise RuntimeError("backend-worker Topology Manifest 身份已变化")
        if topology.supervisor_instance_id != bundle.topology.supervisor_instance_id:
            raise RuntimeError("backend-worker Supervisor 身份已变化")
        if topology.state not in {"starting", "running"}:
            raise RuntimeError(
                f"backend-worker Topology 已停止接收任务: state={topology.state!r}"
            )

    def _write_snapshot(self) -> None:
        """原子写入当前严格心跳契约。"""

        bundle = self.info.launch_bundle
        context = bundle.context
        profile = bundle.profile
        with self._state_lock:
            status = self._status
            failure_message = self._failure_message
        record = WorkerHeartbeatRecord(
            format_id=WORKER_HEARTBEAT_FORMAT_ID,
            topology_id=context.topology_id,
            topology_generation=context.topology_generation,
            topology_epoch_id=context.topology_epoch_id,
            profile_id=profile.profile_id,
            profile_fingerprint=profile.fingerprint(),
            worker_instance_id=context.worker_instance_id,
            status=status,
            app_version=self.info.app_version,
            process_id=os.getpid(),
            python_executable=sys.executable,
            process_started_at=self._process_started_at,
            heartbeat_at=utc_now(),
            workspace_dir=str(self.info.workspace_dir),
            queue_root_dir=str(self.info.queue_root_dir),
            enabled_consumer_kinds=profile.enabled_consumer_kinds,
            max_concurrent_tasks=profile.max_concurrent_tasks,
            poll_interval_seconds=profile.poll_interval_seconds,
            failure_message=failure_message,
        )
        write_worker_contract(self.heartbeat_path, record)


def read_backend_worker_health_summary(
    *,
    worker_runtime_root_dir: str | Path,
    stale_after_seconds: float | None = None,
) -> dict[str, object]:
    """只读取 active Topology 声明的期望 Profile 心跳。"""

    layout = BackendWorkerRuntimeLayout(Path(worker_runtime_root_dir).resolve())
    base_summary: dict[str, object] = {
        "status": "external",
        "entrypoint": "amvision full supervisor",
        "runtime_root_dir": str(layout.root_dir),
        "active_topology_path": str(layout.active_topology_path),
    }
    if not layout.active_topology_path.is_file():
        return {
            **base_summary,
            "health": "offline",
            "reason": "active_topology_missing",
            "worker_count": 0,
            "workers": [],
        }
    try:
        pointer = load_worker_topology_pointer(layout.active_topology_path)
        manifest_path = layout.topology_manifest_path(pointer.topology_epoch_id)
        topology = load_worker_topology_manifest(manifest_path)
        _validate_active_topology(
            pointer_identity=(
                pointer.topology_id,
                pointer.topology_generation,
                pointer.topology_epoch_id,
            ),
            topology=topology,
        )
    except (OSError, ValueError, ValidationError) as error:
        return {
            **base_summary,
            "health": "failed",
            "reason": "active_topology_invalid",
            "error_type": error.__class__.__name__,
            "error": str(error),
            "worker_count": 0,
            "workers": [],
        }

    effective_stale_after = (
        topology.stale_after_seconds
        if stale_after_seconds is None
        else max(1.0, float(stale_after_seconds))
    )
    workers = [
        _read_expected_profile_health(
            layout=layout,
            topology=topology,
            profile_id=profile.profile_id,
            display_name=profile.display_name,
            profile_fingerprint=profile.profile_fingerprint,
            enabled_consumer_kinds=profile.enabled_consumer_kinds,
            max_concurrent_tasks=profile.max_concurrent_tasks,
            poll_interval_seconds=profile.poll_interval_seconds,
            stale_after_seconds=effective_stale_after,
        )
        for profile in topology.expected_profiles
    ]
    aggregate_health = _resolve_topology_health(topology=topology, workers=workers)
    statuses = (
        "starting",
        "running",
        "failed",
        "stopping",
        "stopped",
        "offline",
        "stale",
    )
    status_counts = {
        status: sum(worker.get("health") == status for worker in workers)
        for status in statuses
    }
    return {
        **base_summary,
        "health": aggregate_health,
        "topology_id": topology.topology_id,
        "topology_generation": topology.topology_generation,
        "topology_epoch_id": topology.topology_epoch_id,
        "topology_state": topology.state,
        "supervisor_instance_id": topology.supervisor_instance_id,
        "activated_at": topology.activated_at.isoformat(),
        "stale_after_seconds": effective_stale_after,
        "worker_count": len(workers),
        **{f"{status}_count": count for status, count in status_counts.items()},
        "workers": workers,
    }


def _read_expected_profile_health(
    *,
    layout: BackendWorkerRuntimeLayout,
    topology: WorkerTopologyManifest,
    profile_id: str,
    display_name: str,
    profile_fingerprint: str,
    enabled_consumer_kinds: tuple[str, ...],
    max_concurrent_tasks: int,
    poll_interval_seconds: float,
    stale_after_seconds: float,
) -> dict[str, object]:
    """读取并校验一个期望 Profile 的唯一心跳。"""

    path = layout.profile_heartbeat_path(topology.topology_epoch_id, profile_id)
    base: dict[str, object] = {
        "profile_id": profile_id,
        "display_name": display_name,
        "health_file": str(path),
        "expected_profile_fingerprint": profile_fingerprint,
        "enabled_consumer_kinds": list(enabled_consumer_kinds),
        "enabled_consumer_count": len(enabled_consumer_kinds),
        "max_concurrent_tasks": max_concurrent_tasks,
        "poll_interval_seconds": poll_interval_seconds,
    }
    if not path.is_file():
        return {**base, "health": "offline", "reason": "heartbeat_missing"}
    try:
        record = load_worker_heartbeat(path)
    except (OSError, ValueError, ValidationError) as error:
        return {
            **base,
            "health": "failed",
            "reason": "heartbeat_invalid",
            "error_type": error.__class__.__name__,
            "error": str(error),
        }
    expected_identity = (
        topology.topology_id,
        topology.topology_generation,
        topology.topology_epoch_id,
        profile_id,
        profile_fingerprint,
    )
    record_identity = (
        record.topology_id,
        record.topology_generation,
        record.topology_epoch_id,
        record.profile_id,
        record.profile_fingerprint,
    )
    if record_identity != expected_identity:
        return {
            **base,
            "health": "failed",
            "reason": "heartbeat_identity_mismatch",
            "worker_instance_id": record.worker_instance_id,
        }
    heartbeat_age_seconds = max(
        0.0,
        (datetime.now(UTC) - record.heartbeat_at).total_seconds(),
    )
    health = record.status
    reason: str | None = None
    if heartbeat_age_seconds > stale_after_seconds and record.status not in {
        "stopped",
        "failed",
    }:
        health = "stale"
        reason = "heartbeat_stale"
    return {
        **base,
        **record.model_dump(mode="json"),
        "health": health,
        "reason": reason,
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "stale_after_seconds": stale_after_seconds,
        "enabled_consumer_count": len(record.enabled_consumer_kinds),
    }


def _resolve_topology_health(
    *,
    topology: WorkerTopologyManifest,
    workers: list[dict[str, object]],
) -> str:
    """按当前 Topology 的期望 Profile 集合计算总健康状态。"""

    if topology.state == "failed":
        return "failed"
    if topology.state == "stopping":
        return "stopping"
    if topology.state == "stopped":
        return "stopped"
    healths = [str(worker.get("health") or "failed") for worker in workers]
    if healths and all(health == "running" for health in healths):
        return "running"
    if topology.state == "starting" and all(
        health in {"starting", "running", "offline"} for health in healths
    ):
        return "starting"
    if any(health == "running" for health in healths):
        return "degraded"
    if any(health in {"failed", "stale"} for health in healths):
        return "failed"
    if healths and all(health == "stopped" for health in healths):
        return "stopped"
    return "offline"


def _validate_active_topology(
    *,
    pointer_identity: tuple[str, int, str],
    topology: WorkerTopologyManifest,
) -> None:
    """拒绝 active pointer 与 Manifest 身份不一致的运行目录。"""

    manifest_identity = (
        topology.topology_id,
        topology.topology_generation,
        topology.topology_epoch_id,
    )
    if pointer_identity != manifest_identity:
        raise ValueError("active Topology pointer 与 Manifest 身份不一致")
