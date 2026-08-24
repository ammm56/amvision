"""Worker Topology 心跳与诊断聚合测试。"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import time

import pytest

import backend.workers.contracts as worker_contracts_module
from backend.workers.contracts import (
    WORKER_HEARTBEAT_FORMAT_ID,
    WORKER_PROFILE_FORMAT_ID,
    WORKER_TOPOLOGY_FORMAT_ID,
    WORKER_TOPOLOGY_ID,
    BackendWorkerLaunchBundle,
    BackendWorkerLaunchContext,
    BackendWorkerRuntimeLayout,
    WorkerHeartbeatRecord,
    WorkerProfileManifest,
    WorkerTopologyManifest,
    WorkerTopologyProfile,
    build_topology_pointer,
    utc_now,
    write_worker_contract,
)
from backend.workers.health import (
    BackendWorkerHeartbeat,
    BackendWorkerHeartbeatInfo,
    BackendWorkerTopologyStopping,
    read_backend_worker_health_summary,
)


def _profile(profile_id: str, consumer_kind: str) -> WorkerProfileManifest:
    """构造测试 Profile。"""

    return WorkerProfileManifest(
        format_id=WORKER_PROFILE_FORMAT_ID,
        profile_id=profile_id,
        display_name=f"amvision {profile_id} worker",
        description=f"测试 {profile_id} worker Profile。",
        enabled_consumer_kinds=(consumer_kind,),
        max_concurrent_tasks=1,
        poll_interval_seconds=0.1,
    )


def _activate_topology(
    runtime_root: Path,
    *profiles: WorkerProfileManifest,
    state: str = "running",
) -> tuple[BackendWorkerRuntimeLayout, WorkerTopologyManifest]:
    """写入一代测试 Topology 和 active pointer。"""

    layout = BackendWorkerRuntimeLayout(runtime_root)
    topology = WorkerTopologyManifest(
        format_id=WORKER_TOPOLOGY_FORMAT_ID,
        topology_id=WORKER_TOPOLOGY_ID,
        topology_generation=1,
        topology_epoch_id="epoch-test-000000000001",
        state=state,
        supervisor_instance_id="supervisor-test-00000001",
        activated_at=utc_now(),
        heartbeat_interval_seconds=0.5,
        stale_after_seconds=5.0,
        expected_profiles=tuple(
            WorkerTopologyProfile.from_manifest(profile) for profile in profiles
        ),
    )
    write_worker_contract(
        layout.topology_manifest_path(topology.topology_epoch_id), topology
    )
    write_worker_contract(layout.active_topology_path, build_topology_pointer(topology))
    return layout, topology


def _launch_bundle(
    *,
    layout: BackendWorkerRuntimeLayout,
    topology: WorkerTopologyManifest,
    profile: WorkerProfileManifest,
) -> BackendWorkerLaunchBundle:
    """构造已校验过的测试启动契约。"""

    return BackendWorkerLaunchBundle(
        context=BackendWorkerLaunchContext(
            profile_file=layout.root_dir / f"{profile.profile_id}.json",
            runtime_layout=layout,
            topology_id=topology.topology_id,
            topology_generation=topology.topology_generation,
            topology_epoch_id=topology.topology_epoch_id,
            worker_instance_id=f"worker-instance-{profile.profile_id}-0001",
        ),
        profile=profile,
        topology=topology,
    )


def _start_heartbeat(
    *,
    layout: BackendWorkerRuntimeLayout,
    topology: WorkerTopologyManifest,
    profile: WorkerProfileManifest,
) -> BackendWorkerHeartbeat:
    """启动一个测试 Profile 心跳。"""

    heartbeat = BackendWorkerHeartbeat(
        info=BackendWorkerHeartbeatInfo(
            launch_bundle=_launch_bundle(
                layout=layout,
                topology=topology,
                profile=profile,
            ),
            app_version="0.1.4",
            workspace_dir=layout.root_dir / "workspace" / profile.profile_id,
            queue_root_dir=layout.root_dir / "queue",
        ),
        interval_seconds=0.5,
    )
    heartbeat.start()
    heartbeat.mark_running()
    return heartbeat


def test_worker_contract_write_retries_transient_windows_reader_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """目标契约被短暂读取占用时，应有界重试并清理临时文件。"""

    target_path = tmp_path / "training-profile.json"
    original_replace = Path.replace
    sharing_violation_count = 0

    def replace_with_transient_lock(
        source_path: Path,
        current_target_path: str | Path,
    ) -> Path:
        nonlocal sharing_violation_count
        if (
            Path(current_target_path) == target_path
            and sharing_violation_count < 3
        ):
            sharing_violation_count += 1
            error = PermissionError("simulated Windows worker contract reader lock")
            error.winerror = 5  # type: ignore[attr-defined]
            raise error
        return original_replace(source_path, current_target_path)

    monkeypatch.setattr(Path, "replace", replace_with_transient_lock)

    write_worker_contract(target_path, _profile("training", "pose-training"))

    assert sharing_violation_count == 3
    assert target_path.is_file()
    assert list(tmp_path.glob("*.tmp")) == []


def test_worker_contract_write_cleans_temp_file_after_persistent_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """契约替换最终失败时，也不能遗留本次写入的临时文件。"""

    target_path = tmp_path / "training-profile.json"

    def fail_replace(*_args, **_kwargs) -> None:
        raise PermissionError("simulated persistent worker contract failure")

    monkeypatch.setattr(
        worker_contracts_module,
        "replace_path_with_retry",
        fail_replace,
    )

    with pytest.raises(PermissionError, match="persistent worker contract failure"):
        write_worker_contract(target_path, _profile("training", "pose-training"))

    assert list(tmp_path.glob("*.tmp")) == []


def test_worker_health_summary_reports_offline_without_active_topology(
    tmp_path,
) -> None:
    """没有 active Topology 时明确显示离线，不扫描历史文件。"""

    summary = read_backend_worker_health_summary(worker_runtime_root_dir=tmp_path)

    assert summary["health"] == "offline"
    assert summary["reason"] == "active_topology_missing"


def test_worker_health_summary_reads_only_expected_current_epoch_profiles(
    tmp_path,
) -> None:
    """诊断只聚合当前 epoch 声明的 Profile，完全忽略历史目录。"""

    import_profile = _profile("dataset-import", "dataset-import")
    export_profile = _profile("dataset-export", "dataset-export")
    layout, topology = _activate_topology(tmp_path, import_profile, export_profile)
    old_heartbeat = layout.profile_heartbeat_path("old-epoch-0000000001", "legacy")
    old_heartbeat.parent.mkdir(parents=True)
    old_heartbeat.write_bytes(b"\x00" * 128)
    import_heartbeat = _start_heartbeat(
        layout=layout,
        topology=topology,
        profile=import_profile,
    )
    export_heartbeat = _start_heartbeat(
        layout=layout,
        topology=topology,
        profile=export_profile,
    )
    try:
        summary = read_backend_worker_health_summary(worker_runtime_root_dir=tmp_path)
    finally:
        export_heartbeat.stop()
        import_heartbeat.stop()

    assert summary["health"] == "running"
    assert summary["worker_count"] == 2
    assert summary["running_count"] == 2
    assert {worker["profile_id"] for worker in summary["workers"]} == {
        "dataset-import",
        "dataset-export",
    }


def test_worker_health_summary_marks_missing_expected_profile_degraded(
    tmp_path,
) -> None:
    """当前 Topology 缺少一个期望 Profile 时报告真实降级。"""

    import_profile = _profile("dataset-import", "dataset-import")
    export_profile = _profile("dataset-export", "dataset-export")
    layout, topology = _activate_topology(tmp_path, import_profile, export_profile)
    heartbeat = _start_heartbeat(
        layout=layout,
        topology=topology,
        profile=import_profile,
    )
    try:
        summary = read_backend_worker_health_summary(worker_runtime_root_dir=tmp_path)
    finally:
        heartbeat.stop()

    assert summary["health"] == "degraded"
    assert summary["running_count"] == 1
    assert summary["offline_count"] == 1


def test_worker_health_summary_rejects_stale_and_mismatched_heartbeats(
    tmp_path,
) -> None:
    """过期心跳和身份不匹配心跳都不能被当作当前运行实例。"""

    import_profile = _profile("dataset-import", "dataset-import")
    export_profile = _profile("dataset-export", "dataset-export")
    layout, topology = _activate_topology(tmp_path, import_profile, export_profile)
    stale = WorkerHeartbeatRecord(
        format_id=WORKER_HEARTBEAT_FORMAT_ID,
        topology_id=topology.topology_id,
        topology_generation=topology.topology_generation,
        topology_epoch_id=topology.topology_epoch_id,
        profile_id=import_profile.profile_id,
        profile_fingerprint=import_profile.fingerprint(),
        worker_instance_id="worker-instance-import-0001",
        status="running",
        app_version="0.1.4",
        process_id=1234,
        python_executable="python",
        process_started_at=utc_now() - timedelta(minutes=2),
        heartbeat_at=utc_now() - timedelta(minutes=1),
        workspace_dir=str(tmp_path / "worker"),
        queue_root_dir=str(tmp_path / "queue"),
        enabled_consumer_kinds=import_profile.enabled_consumer_kinds,
        max_concurrent_tasks=1,
        poll_interval_seconds=0.1,
    )
    mismatched = stale.model_copy(
        update={
            "profile_id": export_profile.profile_id,
            "profile_fingerprint": "0" * 64,
            "heartbeat_at": utc_now(),
        }
    )
    write_worker_contract(
        layout.profile_heartbeat_path(
            topology.topology_epoch_id, import_profile.profile_id
        ),
        stale,
    )
    write_worker_contract(
        layout.profile_heartbeat_path(
            topology.topology_epoch_id, export_profile.profile_id
        ),
        mismatched,
    )

    summary = read_backend_worker_health_summary(
        worker_runtime_root_dir=tmp_path,
        stale_after_seconds=5,
    )

    assert summary["health"] == "failed"
    assert summary["stale_count"] == 1
    assert summary["failed_count"] == 1
    reasons = {worker["reason"] for worker in summary["workers"]}
    assert reasons == {"heartbeat_stale", "heartbeat_identity_mismatch"}


def test_worker_heartbeat_stops_worker_when_active_topology_is_stopped(
    tmp_path,
) -> None:
    """Supervisor 停止当前 Topology 后，遗留 Worker 必须主动退出主循环。"""

    profile = _profile("dataset-import", "dataset-import")
    layout, topology = _activate_topology(tmp_path, profile)
    heartbeat = _start_heartbeat(
        layout=layout,
        topology=topology,
        profile=profile,
    )
    write_worker_contract(
        layout.topology_manifest_path(topology.topology_epoch_id),
        topology.model_copy(update={"state": "stopped"}),
    )

    deadline = time.monotonic() + 3.0
    try:
        while time.monotonic() < deadline:
            try:
                heartbeat.assert_healthy()
            except BackendWorkerTopologyStopping as error:
                assert "Topology 正在停止" in str(error)
                break
            time.sleep(0.05)
        else:
            raise AssertionError("Worker 未在 Topology 停止后退出心跳线程")
    finally:
        heartbeat.stop()
