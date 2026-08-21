"""源码开发 backend-worker Supervisor 测试。"""

from __future__ import annotations

from pathlib import Path

from backend.workers.contracts import (
    BackendWorkerRuntimeLayout,
    load_worker_topology_manifest,
    load_worker_topology_pointer,
)
from backend.workers.supervisor import (
    DEFAULT_PROFILE_IDS,
    DevelopmentWorkerSupervisor,
    build_argument_parser,
)


def _build_supervisor(tmp_path: Path) -> DevelopmentWorkerSupervisor:
    """构造使用隔离 runtime 目录的源码 Supervisor。"""

    repository_root = Path(__file__).resolve().parents[1]
    supervisor = DevelopmentWorkerSupervisor(app_root=repository_root)
    supervisor.runtime_layout = BackendWorkerRuntimeLayout(tmp_path / "workers")
    return supervisor


def test_development_supervisor_activates_complete_source_topology(
    tmp_path: Path,
) -> None:
    """源码入口应激活六个严格 Profile，而不是旧通用 Worker。"""

    supervisor = _build_supervisor(tmp_path)
    supervisor._validate_source_layout()
    profiles = supervisor._load_profiles()

    assert tuple(profile.profile_id for profile in profiles) == DEFAULT_PROFILE_IDS

    topology = supervisor._activate_topology(profiles)
    pointer = load_worker_topology_pointer(
        supervisor.runtime_layout.active_topology_path
    )
    persisted = load_worker_topology_manifest(
        supervisor.runtime_layout.topology_manifest_path(topology.topology_epoch_id)
    )

    assert topology.state == "starting"
    assert topology.topology_generation == 1
    assert (
        tuple(profile.profile_id for profile in topology.expected_profiles)
        == DEFAULT_PROFILE_IDS
    )
    assert pointer.topology_epoch_id == topology.topology_epoch_id
    assert persisted == topology


def test_development_supervisor_increments_generation_and_preserves_failed_state(
    tmp_path: Path,
) -> None:
    """重新启动必须递增 generation，异常终态不能被 stopped 覆盖。"""

    first = _build_supervisor(tmp_path)
    profiles = first._load_profiles()
    first_topology = first._activate_topology(profiles)

    second = _build_supervisor(tmp_path)
    second_topology = second._activate_topology(profiles)
    second.topology = second_topology
    second._failed = True
    second._update_topology_state("failed")
    second._stop_workers()

    persisted = load_worker_topology_manifest(
        second.runtime_layout.topology_manifest_path(second_topology.topology_epoch_id)
    )
    assert second_topology.topology_generation == first_topology.topology_generation + 1
    assert persisted.state == "failed"


def test_development_supervisor_cli_defaults_to_source_root() -> None:
    """开发 CLI 默认只接收源码根目录和就绪超时。"""

    args = build_argument_parser().parse_args([])

    assert args.app_root == "."
    assert args.ready_timeout_seconds == 120.0
    assert len(DEFAULT_PROFILE_IDS) == 6
