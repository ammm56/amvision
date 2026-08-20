"""backend-worker Topology 启动身份与单实例锁测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.workers.contracts import (
    WORKER_INSTANCE_ID_ENV,
    WORKER_PROFILE_FILE_ENV,
    WORKER_PROFILE_FORMAT_ID,
    WORKER_RUNTIME_ROOT_ENV,
    WORKER_TOPOLOGY_EPOCH_ID_ENV,
    WORKER_TOPOLOGY_FORMAT_ID,
    WORKER_TOPOLOGY_GENERATION_ENV,
    WORKER_TOPOLOGY_ID,
    WORKER_TOPOLOGY_ID_ENV,
    BackendWorkerRuntimeLayout,
    WorkerProfileManifest,
    WorkerTopologyManifest,
    WorkerTopologyProfile,
    build_topology_pointer,
    load_backend_worker_launch_bundle,
    utc_now,
    write_worker_contract,
)
from backend.workers.profile_lock import BackendWorkerProfileLock


def _write_launch_contracts(
    tmp_path: Path,
) -> tuple[dict[str, str], BackendWorkerRuntimeLayout]:
    """写入一套完整的 Worker 启动契约。"""

    layout = BackendWorkerRuntimeLayout(tmp_path / "runtime")
    profile_path = tmp_path / "profile.json"
    profile = WorkerProfileManifest(
        format_id=WORKER_PROFILE_FORMAT_ID,
        profile_id="dataset-import",
        display_name="amvision dataset import worker",
        description="测试 dataset import Profile。",
        enabled_consumer_kinds=("dataset-import",),
        max_concurrent_tasks=1,
        poll_interval_seconds=0.1,
    )
    topology = WorkerTopologyManifest(
        format_id=WORKER_TOPOLOGY_FORMAT_ID,
        topology_id=WORKER_TOPOLOGY_ID,
        topology_generation=3,
        topology_epoch_id="epoch-test-000000000003",
        state="starting",
        supervisor_instance_id="supervisor-test-00000003",
        activated_at=utc_now(),
        heartbeat_interval_seconds=2.0,
        stale_after_seconds=15.0,
        expected_profiles=(WorkerTopologyProfile.from_manifest(profile),),
    )
    write_worker_contract(profile_path, profile)
    write_worker_contract(
        layout.topology_manifest_path(topology.topology_epoch_id), topology
    )
    write_worker_contract(layout.active_topology_path, build_topology_pointer(topology))
    environment = {
        WORKER_PROFILE_FILE_ENV: str(profile_path),
        WORKER_RUNTIME_ROOT_ENV: str(layout.root_dir),
        WORKER_TOPOLOGY_ID_ENV: topology.topology_id,
        WORKER_TOPOLOGY_GENERATION_ENV: str(topology.topology_generation),
        WORKER_TOPOLOGY_EPOCH_ID_ENV: topology.topology_epoch_id,
        WORKER_INSTANCE_ID_ENV: "worker-instance-test-00000003",
    }
    return environment, layout


def test_launch_bundle_requires_supervisor_identity_and_matches_active_topology(
    tmp_path: Path,
) -> None:
    """Worker 只能使用 Supervisor 注入且与 active Topology 完全一致的身份启动。"""

    environment, _layout = _write_launch_contracts(tmp_path)

    bundle = load_backend_worker_launch_bundle(environment)

    assert bundle.profile.profile_id == "dataset-import"
    assert bundle.context.topology_generation == 3
    assert bundle.context.worker_instance_id == "worker-instance-test-00000003"


def test_launch_bundle_rejects_raw_or_stale_launch_context(tmp_path: Path) -> None:
    """裸启动和旧 epoch 身份都必须立即失败。"""

    with pytest.raises(RuntimeError, match="Supervisor 启动参数"):
        load_backend_worker_launch_bundle({})

    environment, _layout = _write_launch_contracts(tmp_path)
    environment[WORKER_TOPOLOGY_EPOCH_ID_ENV] = "epoch-stale-0000000001"

    with pytest.raises((FileNotFoundError, RuntimeError)):
        load_backend_worker_launch_bundle(environment)


def test_launch_bundle_rejects_stopped_topology(tmp_path: Path) -> None:
    """已经停止的 Topology 即使仍被 active pointer 指向也不能启动 Worker。"""

    environment, layout = _write_launch_contracts(tmp_path)
    manifest_path = layout.topology_manifest_path("epoch-test-000000000003")
    topology = WorkerTopologyManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    write_worker_contract(
        manifest_path,
        topology.model_copy(update={"state": "stopped"}),
    )

    with pytest.raises(RuntimeError, match="不接受新进程"):
        load_backend_worker_launch_bundle(environment)


def test_profile_lock_rejects_second_process_slot_for_same_epoch_profile(
    tmp_path: Path,
) -> None:
    """同一 epoch/Profile 同时只能持有一个进程锁。"""

    _environment, layout = _write_launch_contracts(tmp_path)
    lock_path = layout.profile_lock_path("epoch-test-000000000003", "dataset-import")
    first = BackendWorkerProfileLock(lock_path=lock_path, owner={"instance": "first"})
    second = BackendWorkerProfileLock(lock_path=lock_path, owner={"instance": "second"})

    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="已有运行实例"):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    second.release()
