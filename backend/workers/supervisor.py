"""源码开发环境的 backend-worker Topology Supervisor。"""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from backend.workers.contracts import (
    DEFAULT_WORKER_RUNTIME_ROOT,
    WORKER_INSTANCE_ID_ENV,
    WORKER_PROFILE_FILE_ENV,
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
    load_worker_heartbeat,
    load_worker_profile_manifest,
    load_worker_topology_pointer,
    utc_now,
    write_worker_contract,
)
from backend.workers.profile_lock import BackendWorkerProfileLock


DEFAULT_PROFILE_IDS = (
    "dataset-import",
    "dataset-export",
    "training",
    "conversion",
    "evaluation",
    "inference",
)


@dataclass
class _WorkerProcess:
    """保存一个源码开发 Worker Profile 的进程信息。"""

    profile: WorkerProfileManifest
    worker_instance_id: str
    process: subprocess.Popen[bytes]


class DevelopmentWorkerSupervisor:
    """在源码目录中激活并监督一代完整 Worker Topology。"""

    def __init__(
        self,
        *,
        app_root: Path,
        profile_ids: tuple[str, ...] = DEFAULT_PROFILE_IDS,
        ready_timeout_seconds: float = 120.0,
    ) -> None:
        """初始化 Supervisor，但不启动任何 Worker。"""

        self.app_root = app_root.resolve()
        self.profile_ids = profile_ids
        self.ready_timeout_seconds = max(1.0, float(ready_timeout_seconds))
        self.runtime_layout = BackendWorkerRuntimeLayout(
            (self.app_root / DEFAULT_WORKER_RUNTIME_ROOT).resolve()
        )
        self.supervisor_instance_id = f"development-supervisor-{uuid4().hex}"
        self.topology_lock = BackendWorkerProfileLock(
            lock_path=self.runtime_layout.topology_lock_path,
            owner={
                "topology_id": WORKER_TOPOLOGY_ID,
                "supervisor_instance_id": self.supervisor_instance_id,
                "mode": "source-development",
            },
        )
        self.topology: WorkerTopologyManifest | None = None
        self.processes: list[_WorkerProcess] = []
        self._failed = False

    def run_forever(self) -> None:
        """激活完整 Topology，等待所有 Profile 就绪并持续监督。"""

        self._validate_source_layout()
        self.topology_lock.acquire()
        try:
            profiles = self._load_profiles()
            self.topology = self._activate_topology(profiles)
            for profile in profiles:
                worker = self._start_worker(profile)
                self.processes.append(worker)
                self._wait_for_worker_ready(worker)
            self._update_topology_state("running")
            print(
                "backend-worker development topology ready "
                f"generation={self.topology.topology_generation} "
                f"epoch={self.topology.topology_epoch_id} "
                f"profiles={list(self.profile_ids)!r}",
                flush=True,
            )
            self._monitor_workers()
        except KeyboardInterrupt:
            print("正在停止源码开发 Worker Topology。", flush=True)
        except BaseException:
            self._failed = True
            with contextlib.suppress(Exception):
                self._update_topology_state("failed")
            raise
        finally:
            if not self._failed:
                with contextlib.suppress(Exception):
                    self._update_topology_state("stopping")
            self._stop_workers()
            if not self._failed:
                with contextlib.suppress(Exception):
                    self._update_topology_state("stopped")
            self.topology_lock.release()

    def _validate_source_layout(self) -> None:
        """拒绝把源码开发入口误用于发行目录。"""

        required_paths = (
            self.app_root / "backend" / "workers" / "main.py",
            self.app_root / "config" / "backend-worker.json",
            self.app_root / "runtimes" / "manifests" / "worker-profiles",
        )
        missing = [str(path) for path in required_paths if not path.exists()]
        if missing:
            raise FileNotFoundError(
                "源码开发 Worker Supervisor 缺少必需路径: " + ", ".join(missing)
            )

    def _load_profiles(self) -> tuple[WorkerProfileManifest, ...]:
        """按固定顺序加载完整且不可重复的 Worker Profile。"""

        if not self.profile_ids:
            raise ValueError("至少需要一个 Worker Profile")
        if len(self.profile_ids) != len(set(self.profile_ids)):
            raise ValueError("Worker Profile id 不能重复")
        profiles_root = self.app_root / "runtimes" / "manifests" / "worker-profiles"
        profiles: list[WorkerProfileManifest] = []
        for profile_id in self.profile_ids:
            profile = load_worker_profile_manifest(profiles_root / f"{profile_id}.json")
            if profile.profile_id != profile_id:
                raise ValueError(
                    "Worker Profile 文件名与 manifest profile_id 不一致: "
                    f"declared={profile_id!r}, actual={profile.profile_id!r}"
                )
            profiles.append(profile)
        return tuple(profiles)

    def _activate_topology(
        self,
        profiles: tuple[WorkerProfileManifest, ...],
    ) -> WorkerTopologyManifest:
        """创建并原子激活新一代源码开发 Topology。"""

        generation = 1
        if self.runtime_layout.active_topology_path.is_file():
            with contextlib.suppress(OSError, ValueError):
                previous = load_worker_topology_pointer(
                    self.runtime_layout.active_topology_path
                )
                generation = previous.topology_generation + 1
        topology = WorkerTopologyManifest(
            format_id=WORKER_TOPOLOGY_FORMAT_ID,
            topology_id=WORKER_TOPOLOGY_ID,
            topology_generation=generation,
            topology_epoch_id=f"epoch-{uuid4().hex}",
            state="starting",
            supervisor_instance_id=self.supervisor_instance_id,
            activated_at=utc_now(),
            heartbeat_interval_seconds=2.0,
            stale_after_seconds=15.0,
            expected_profiles=tuple(
                WorkerTopologyProfile.from_manifest(profile) for profile in profiles
            ),
        )
        write_worker_contract(
            self.runtime_layout.topology_manifest_path(topology.topology_epoch_id),
            topology,
        )
        write_worker_contract(
            self.runtime_layout.active_topology_path,
            build_topology_pointer(topology),
        )
        return topology

    def _update_topology_state(self, state: str) -> None:
        """更新当前 Topology 状态，不改变其身份和 Profile。"""

        topology = self.topology
        if topology is None:
            return
        self.topology = topology.model_copy(update={"state": state})
        write_worker_contract(
            self.runtime_layout.topology_manifest_path(topology.topology_epoch_id),
            self.topology,
        )

    def _start_worker(self, profile: WorkerProfileManifest) -> _WorkerProcess:
        """使用当前开发解释器启动一个严格 Profile Worker。"""

        topology = self._require_topology()
        profile_path = (
            self.app_root
            / "runtimes"
            / "manifests"
            / "worker-profiles"
            / f"{profile.profile_id}.json"
        ).resolve()
        worker_instance_id = f"worker-{profile.profile_id}-{uuid4().hex}"
        environment = os.environ.copy()
        environment.update(
            {
                "PYTHONUNBUFFERED": "1",
                WORKER_PROFILE_FILE_ENV: str(profile_path),
                WORKER_RUNTIME_ROOT_ENV: str(self.runtime_layout.root_dir),
                WORKER_TOPOLOGY_ID_ENV: topology.topology_id,
                WORKER_TOPOLOGY_GENERATION_ENV: str(topology.topology_generation),
                WORKER_TOPOLOGY_EPOCH_ID_ENV: topology.topology_epoch_id,
                WORKER_INSTANCE_ID_ENV: worker_instance_id,
                "AMVISION_WORKER_APP__APP_NAME": profile.display_name,
                "AMVISION_WORKER_WORKSPACE__ROOT_DIR": (
                    f"./data/worker/{profile.profile_id}"
                ),
            }
        )
        process = subprocess.Popen(
            [sys.executable, "-m", "backend.workers.main"],
            cwd=str(self.app_root),
            env=environment,
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            ),
            start_new_session=os.name != "nt",
        )
        print(
            f"已启动 backend-worker:{profile.profile_id}，pid={process.pid}。",
            flush=True,
        )
        return _WorkerProcess(
            profile=profile,
            worker_instance_id=worker_instance_id,
            process=process,
        )

    def _wait_for_worker_ready(self, worker: _WorkerProcess) -> None:
        """等待当前 Profile 的严格心跳进入 running。"""

        topology = self._require_topology()
        heartbeat_path = self.runtime_layout.profile_heartbeat_path(
            topology.topology_epoch_id,
            worker.profile.profile_id,
        )
        deadline = time.monotonic() + self.ready_timeout_seconds
        while time.monotonic() < deadline:
            return_code = worker.process.poll()
            if return_code is not None:
                raise RuntimeError(
                    f"backend-worker:{worker.profile.profile_id} 初始化退出，"
                    f"returncode={return_code}"
                )
            if heartbeat_path.is_file():
                with contextlib.suppress(OSError, ValueError):
                    heartbeat = load_worker_heartbeat(heartbeat_path)
                    if (
                        heartbeat.topology_id == topology.topology_id
                        and heartbeat.topology_generation
                        == topology.topology_generation
                        and heartbeat.topology_epoch_id == topology.topology_epoch_id
                        and heartbeat.profile_id == worker.profile.profile_id
                        and heartbeat.profile_fingerprint
                        == worker.profile.fingerprint()
                        and heartbeat.worker_instance_id == worker.worker_instance_id
                    ):
                        if heartbeat.status == "running":
                            print(
                                f"backend-worker:{worker.profile.profile_id} 已就绪。",
                                flush=True,
                            )
                            return
                        if heartbeat.status == "failed":
                            raise RuntimeError(
                                f"backend-worker:{worker.profile.profile_id} 初始化失败："
                                f"{heartbeat.failure_message or 'unknown'}"
                            )
            time.sleep(0.2)
        raise TimeoutError(
            f"backend-worker:{worker.profile.profile_id} 未在 "
            f"{self.ready_timeout_seconds:.0f}s 内就绪"
        )

    def _monitor_workers(self) -> None:
        """持续监督完整 Topology；任一 Profile 退出即让问题显式失败。"""

        while True:
            for worker in self.processes:
                return_code = worker.process.poll()
                if return_code is not None:
                    raise RuntimeError(
                        f"backend-worker:{worker.profile.profile_id} 意外退出，"
                        f"returncode={return_code}"
                    )
            time.sleep(0.5)

    def _stop_workers(self) -> None:
        """按启动顺序的逆序停止所有子进程。"""

        for worker in reversed(self.processes):
            process = worker.process
            if process.poll() is not None:
                continue
            _stop_process_tree(process)
        self.processes.clear()

    def _require_topology(self) -> WorkerTopologyManifest:
        """返回已激活的 Topology，否则明确失败。"""

        if self.topology is None:
            raise RuntimeError("Worker Topology 尚未激活")
        return self.topology


def build_argument_parser() -> argparse.ArgumentParser:
    """构造源码开发 Worker Supervisor 参数。"""

    parser = argparse.ArgumentParser(
        description="amvision source-development backend-worker supervisor"
    )
    parser.add_argument(
        "--app-root",
        default=".",
        help="源码仓库根目录，默认使用当前目录",
    )
    parser.add_argument(
        "--ready-timeout-seconds",
        type=float,
        default=120.0,
        help="单个 Worker Profile 初始化超时秒数",
    )
    return parser


def _stop_process_tree(process: subprocess.Popen[bytes]) -> None:
    """停止一个 Worker 根进程及其训练、转换等子进程。"""

    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=10.0)
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    try:
        process.wait(timeout=10.0)
        return
    except subprocess.TimeoutExpired:
        pass
    with contextlib.suppress(ProcessLookupError):
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    process.wait(timeout=10.0)


def main(argv: list[str] | None = None) -> int:
    """执行源码开发 Worker Supervisor。"""

    args = build_argument_parser().parse_args(argv)
    DevelopmentWorkerSupervisor(
        app_root=Path(args.app_root),
        ready_timeout_seconds=args.ready_timeout_seconds,
    ).run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
