from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from backend.workers.health import (
    BackendWorkerHeartbeat,
    BackendWorkerHeartbeatInfo,
    build_backend_worker_profile_health_path,
    read_backend_worker_health_summary,
)


def test_worker_health_summary_reports_offline_when_heartbeat_missing(tmp_path) -> None:
    """没有心跳文件时，诊断应明确显示 worker 离线。"""

    summary = read_backend_worker_health_summary(queue_root_dir=tmp_path)

    assert summary["health"] == "offline"
    assert summary["reason"] == "heartbeat_missing"


def test_worker_health_summary_reads_running_heartbeat(tmp_path) -> None:
    """读取到新鲜心跳时，诊断应显示 worker 正在运行。"""

    heartbeat = BackendWorkerHeartbeat(
        info=BackendWorkerHeartbeatInfo(
            app_name="amvision worker",
            app_version="0.1.3",
            workspace_dir=tmp_path / "worker",
            queue_root_dir=tmp_path,
            enabled_consumer_kinds=("dataset-import", "dataset-export"),
            max_concurrent_tasks=2,
            poll_interval_seconds=1.0,
        )
    )

    heartbeat.start()
    try:
        summary = read_backend_worker_health_summary(queue_root_dir=tmp_path)
    finally:
        heartbeat.stop()

    assert summary["health"] == "running"
    assert summary["worker_count"] == 1
    assert summary["running_count"] == 1
    assert summary["app_name"] == "amvision worker"
    assert summary["enabled_consumer_count"] == 2
    assert summary["workers"][0]["app_name"] == "amvision worker"


def test_worker_health_summary_reads_multiple_profile_heartbeats(tmp_path) -> None:
    """多个独立 worker profile 应分别写心跳并聚合为 running。"""

    import_workers = BackendWorkerHeartbeat(
        info=BackendWorkerHeartbeatInfo(
            app_name="amvision dataset import worker",
            app_version="0.1.3",
            workspace_dir=tmp_path / "worker" / "dataset-import",
            queue_root_dir=tmp_path,
            enabled_consumer_kinds=("dataset-import",),
            max_concurrent_tasks=1,
            poll_interval_seconds=1.0,
        )
    )
    export_workers = BackendWorkerHeartbeat(
        info=BackendWorkerHeartbeatInfo(
            app_name="amvision dataset export worker",
            app_version="0.1.3",
            workspace_dir=tmp_path / "worker" / "dataset-export",
            queue_root_dir=tmp_path,
            enabled_consumer_kinds=("dataset-export",),
            max_concurrent_tasks=1,
            poll_interval_seconds=1.0,
        )
    )

    import_workers.start()
    export_workers.start()
    try:
        summary = read_backend_worker_health_summary(queue_root_dir=tmp_path)
    finally:
        export_workers.stop()
        import_workers.stop()

    assert summary["health"] == "running"
    assert summary["worker_count"] == 2
    assert summary["running_count"] == 2
    worker_names = {worker["app_name"] for worker in summary["workers"]}
    assert worker_names == {
        "amvision dataset import worker",
        "amvision dataset export worker",
    }


def test_worker_health_summary_marks_old_heartbeat_stale(tmp_path) -> None:
    """心跳过期时，诊断应显示 stale，而不是继续显示 running。"""

    health_path = build_backend_worker_profile_health_path(
        tmp_path,
        worker_name="amvision stale worker",
    )
    health_path.parent.mkdir(parents=True)
    health_path.write_text(
        json.dumps(
            {
                "health": "running",
                "heartbeat_at": (datetime.now(UTC) - timedelta(seconds=60)).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    summary = read_backend_worker_health_summary(queue_root_dir=tmp_path, stale_after_seconds=5)

    assert summary["health"] == "stale"
    assert summary["reported_health"] == "running"


def test_worker_health_summary_ignores_stale_profile_covered_by_running_worker(
    tmp_path,
) -> None:
    """旧 profile 的 consumer 已被当前 worker 覆盖时不应误报 degraded。"""

    stale_path = build_backend_worker_profile_health_path(
        tmp_path,
        worker_name="amvision dataset import worker",
    )
    stale_path.parent.mkdir(parents=True)
    stale_path.write_text(
        json.dumps(
            {
                "health": "running",
                "app_name": "amvision dataset import worker",
                "heartbeat_at": (
                    datetime.now(UTC) - timedelta(seconds=60)
                ).isoformat(),
                "enabled_consumer_kinds": ["dataset-import"],
            }
        ),
        encoding="utf-8",
    )
    current_worker = BackendWorkerHeartbeat(
        info=BackendWorkerHeartbeatInfo(
            app_name="amvision worker",
            app_version="0.1.3",
            workspace_dir=tmp_path / "worker",
            queue_root_dir=tmp_path,
            enabled_consumer_kinds=("dataset-import", "dataset-export"),
            max_concurrent_tasks=2,
            poll_interval_seconds=1.0,
        )
    )

    current_worker.start()
    try:
        summary = read_backend_worker_health_summary(
            queue_root_dir=tmp_path,
            stale_after_seconds=5,
        )
    finally:
        current_worker.stop()

    assert summary["health"] == "running"
    assert summary["running_count"] == 1
    assert summary["stale_count"] == 1
    assert summary["superseded_count"] == 1
    stale_worker = next(
        worker
        for worker in summary["workers"]
        if worker["app_name"] == "amvision dataset import worker"
    )
    assert stale_worker["health"] == "stale"
    assert stale_worker["effective_health"] == "superseded"
    assert stale_worker["reason"] == "consumer_coverage_superseded"


def test_worker_health_summary_keeps_uncovered_stale_profile_degraded(tmp_path) -> None:
    """running worker 未覆盖的旧 profile 仍应报告部分故障。"""

    stale_path = build_backend_worker_profile_health_path(
        tmp_path,
        worker_name="amvision dataset import worker",
    )
    stale_path.parent.mkdir(parents=True)
    stale_path.write_text(
        json.dumps(
            {
                "health": "running",
                "app_name": "amvision dataset import worker",
                "heartbeat_at": (
                    datetime.now(UTC) - timedelta(seconds=60)
                ).isoformat(),
                "enabled_consumer_kinds": ["dataset-import"],
            }
        ),
        encoding="utf-8",
    )
    current_worker = BackendWorkerHeartbeat(
        info=BackendWorkerHeartbeatInfo(
            app_name="amvision export worker",
            app_version="0.1.3",
            workspace_dir=tmp_path / "worker",
            queue_root_dir=tmp_path,
            enabled_consumer_kinds=("dataset-export",),
            max_concurrent_tasks=1,
            poll_interval_seconds=1.0,
        )
    )

    current_worker.start()
    try:
        summary = read_backend_worker_health_summary(
            queue_root_dir=tmp_path,
            stale_after_seconds=5,
        )
    finally:
        current_worker.stop()

    assert summary["health"] == "degraded"
    assert summary["running_count"] == 1
    assert summary["stale_count"] == 1
    assert summary["superseded_count"] == 0
