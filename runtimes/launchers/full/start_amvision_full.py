"""full 发布目录一键启动入口。"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable
from uuid import uuid4


LAUNCHERS_ROOT = Path(__file__).resolve().parent / "launchers"
if str(LAUNCHERS_ROOT) not in sys.path:
    sys.path.insert(0, str(LAUNCHERS_ROOT))

from common import (  # noqa: E402
    DailyAppendLogCapture,
    WINDOWS_SYSTEM_CONFIGURATION_REQUIRED_EXIT_CODE,
    build_daily_log_path,
    ensure_windows_long_paths_enabled,
    process_identity_matches,
    read_process_identity,
    resolve_app_root,
    resolve_path,
)


FULL_SUPERVISOR_STATE_FORMAT_ID = "amvision.full-supervisor-state.v1"


class SupervisedComponent:
    """描述 full Supervisor 当前管理的一个常驻组件。"""

    def __init__(
        self,
        *,
        name: str,
        process: subprocess.Popen[bytes] | None,
        log_capture: DailyAppendLogCapture | None,
        worker_entry: dict[str, object] | None = None,
        worker_profile: object | None = None,
        restart_count: int = 0,
        next_restart_at: float | None = None,
        started_monotonic: float = 0.0,
        last_return_code: int | None = None,
    ) -> None:
        """初始化一个受监督组件。"""

        self.name = name
        self.process = process
        self.log_capture = log_capture
        self.worker_entry = worker_entry
        self.worker_profile = worker_profile
        self.restart_count = restart_count
        self.next_restart_at = next_restart_at
        self.started_monotonic = started_monotonic
        self.last_return_code = last_return_code

    @property
    def is_worker(self) -> bool:
        """返回当前组件是否为可独立恢复的 Worker Profile。"""

        return self.worker_entry is not None


def _build_child_process_environment() -> dict[str, str]:
    """构造统一的 UTF-8 子进程环境，保证发布日志可稳定读取。"""

    runtime_env = os.environ.copy()
    runtime_env.setdefault("PYTHONUTF8", "1")
    runtime_env.setdefault("PYTHONIOENCODING", "utf-8")
    return runtime_env


def _request_stack_shutdown(_signum: int, _frame: object) -> None:
    """把操作系统终止信号统一转换为 launcher 清理流程。"""

    raise KeyboardInterrupt


def build_argument_parser() -> argparse.ArgumentParser:
    """构造 full 发布目录一键启动参数解析器。

    返回：
    - argparse.ArgumentParser：命令行参数解析器。
    """

    parser = argparse.ArgumentParser(description="amvision full stack launcher")
    parser.add_argument("--app-root", help="应用根目录；未传入时按脚本相对位置自动解析")
    parser.add_argument(
        "--python-executable", help="用于启动各子进程的 Python 解释器路径"
    )
    parser.add_argument(
        "--release-manifest-file",
        help="release manifest 路径；不传时要求发布目录中只有一个 manifest",
    )
    parser.add_argument("--host", default="0.0.0.0", help="backend-service 监听地址")
    parser.add_argument(
        "--port", type=int, default=5600, help="backend-service 监听端口"
    )
    parser.add_argument(
        "--service-log-level",
        default="info",
        help="backend-service 的 uvicorn 日志级别",
    )
    parser.add_argument(
        "--worker-profile-id",
        action="append",
        default=None,
        help="只启动指定 worker profile id；可重复传入",
    )
    parser.add_argument(
        "--startup-delay-seconds",
        type=float,
        default=1.0,
        help="service 与 worker 之间的启动间隔秒数",
    )
    parser.add_argument(
        "--service-ready-timeout-seconds",
        type=float,
        default=120.0,
        help="等待 backend-service health 可用的最长秒数；成功后再启动 worker",
    )
    parser.add_argument(
        "--worker-ready-timeout-seconds",
        type=float,
        default=30.0,
        help="等待单个 backend-worker 初始化完成的最长秒数",
    )
    parser.add_argument(
        "--logs-subdir",
        default="full-stack",
        help="写入 logs 目录下的子目录名",
    )
    parser.add_argument(
        "--state-file",
        help="运行状态文件路径；未传入时默认写到 logs/<subdir>/runtime-state.json",
    )
    return parser


def _format_runtime_path(app_root: Path, target_path: Path) -> str:
    """把路径格式化为相对应用根目录的展示字符串。

    参数：
    - app_root：当前应用根目录。
    - target_path：待格式化的目标路径。

    返回：
    - str：相对应用根目录的路径；无法相对化时返回绝对路径。
    """

    with contextlib.suppress(ValueError):
        return str(target_path.relative_to(app_root))
    return str(target_path)


def _resolve_stack_state_file(
    app_root: Path,
    *,
    logs_subdir: str,
    explicit_state_file: str | None,
) -> Path:
    """解析 full 一键启动使用的运行状态文件路径。

    参数：
    - app_root：当前应用根目录。
    - logs_subdir：日志子目录名。
    - explicit_state_file：命令行显式传入的状态文件路径。

    返回：
    - Path：运行状态文件绝对路径。
    """

    if explicit_state_file is not None and explicit_state_file.strip():
        return resolve_path(app_root, explicit_state_file.strip())
    return (app_root / "logs" / logs_subdir / "runtime-state.json").resolve()


def _load_stack_state(state_file_path: Path) -> dict[str, object] | None:
    """读取 full 一键启动的运行状态文件。

    参数：
    - state_file_path：运行状态文件路径。

    返回：
    - dict[str, object] | None：读取到的状态字典；文件不存在时返回 None。
    """

    if not state_file_path.is_file():
        return None
    return json.loads(state_file_path.read_text(encoding="utf-8"))


def _ensure_stack_not_running(state_file_path: Path) -> None:
    """确认当前不存在活跃的 full 一键启动实例。

    参数：
    - state_file_path：运行状态文件路径。
    """

    stack_state = _load_stack_state(state_file_path)
    if stack_state is None:
        return

    if stack_state.get("format_id") != FULL_SUPERVISOR_STATE_FORMAT_ID:
        raise RuntimeError(
            f"full stack 状态文件不是当前格式，必须先完成干净切换: {state_file_path}"
        )

    active_pids: list[int] = []
    root_process = stack_state.get("root_process")
    if isinstance(root_process, dict) and process_identity_matches(root_process):
        root_pid = root_process.get("pid")
        if isinstance(root_pid, int):
            active_pids.append(root_pid)

    components_raw = stack_state.get("components")
    if isinstance(components_raw, list):
        for component_raw in components_raw:
            if not isinstance(component_raw, dict):
                continue
            process_identity = component_raw.get("process")
            if isinstance(process_identity, dict) and process_identity_matches(
                process_identity
            ):
                pid_raw = process_identity.get("pid")
                if isinstance(pid_raw, int):
                    active_pids.append(pid_raw)

    if not active_pids:
        with contextlib.suppress(FileNotFoundError):
            state_file_path.unlink()
        return

    raise RuntimeError(
        "检测到已有 full stack 正在运行，"
        f"state_file={state_file_path}，active_pids={sorted(set(active_pids))}；"
        "请先执行 stop-amvision-full。"
    )


def _resolve_release_manifest_path(
    app_root: Path,
    release_manifest_file: str | None,
) -> Path:
    """解析一键启动应使用的 release manifest 文件。

    参数：
    - app_root：当前应用根目录。
    - release_manifest_file：可选的 release manifest 路径。

    返回：
    - Path：真实存在的 release manifest 文件路径。
    """

    if release_manifest_file is not None and release_manifest_file.strip():
        return resolve_path(app_root, release_manifest_file.strip())

    profile_manifest_paths = sorted(
        (app_root / "manifests" / "release-profiles").glob("*.json")
    )
    if len(profile_manifest_paths) != 1:
        raise ValueError(
            "未指定 release manifest，发布目录必须且只能包含一个 manifest: "
            f"count={len(profile_manifest_paths)}"
        )
    return profile_manifest_paths[0]


def _load_release_manifest(app_root: Path, manifest_path: Path) -> dict[str, object]:
    """读取 release manifest。

    参数：
    - app_root：当前应用根目录。
    - manifest_path：真实存在的 release manifest 文件路径。

    返回：
    - dict[str, object]：release manifest 内容。
    """

    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"文件不存在: {_format_runtime_path(app_root, manifest_path)}"
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _select_worker_entries(
    release_manifest: dict[str, object],
    requested_profile_ids: list[str] | None,
) -> list[dict[str, object]]:
    """从 release manifest 中挑出本次要启动的 worker。

    参数：
    - release_manifest：release manifest 内容。
    - requested_profile_ids：命令行显式要求启动的 worker profile id 列表。

    返回：
    - list[dict[str, object]]：要启动的 worker 条目列表。
    """

    worker_entries_raw = release_manifest.get("workers")
    if not isinstance(worker_entries_raw, list) or not worker_entries_raw:
        raise ValueError("release manifest 必须包含非空 workers")

    worker_entries = [entry for entry in worker_entries_raw if isinstance(entry, dict)]
    if requested_profile_ids is None:
        return worker_entries

    requested_profile_id_set = {
        profile_id.strip() for profile_id in requested_profile_ids if profile_id.strip()
    }
    if not requested_profile_id_set:
        return worker_entries

    missing_profile_ids = sorted(
        profile_id
        for profile_id in requested_profile_id_set
        if profile_id
        not in {str(entry.get("profile_id", "")) for entry in worker_entries}
    )
    if missing_profile_ids:
        raise ValueError(
            f"release manifest 中不存在这些 worker profile: {', '.join(missing_profile_ids)}"
        )

    return [
        entry
        for entry in worker_entries
        if str(entry.get("profile_id", "")) in requested_profile_id_set
    ]


def _validate_required_files(
    app_root: Path,
    release_manifest: dict[str, object],
    worker_entries: list[dict[str, object]],
) -> None:
    """校验 full 一键启动依赖的关键文件是否存在。

    参数：
    - app_root：当前应用根目录。
    - release_manifest：release manifest 内容。
    - worker_entries：本次要启动的 worker 条目列表。
    """

    service_entry = release_manifest.get("service")
    if not isinstance(service_entry, dict):
        raise ValueError("release manifest 必须包含 service")

    required_paths = [
        app_root / "config" / "backend-service.json",
        app_root / "config" / "backend-worker.json",
        app_root / "app" / "backend",
        resolve_path(app_root, str(service_entry["python_launcher"])),
        app_root / "app" / "backend" / "inference_daemon" / "main.py",
        app_root / "app" / "backend" / "alembic.ini",
        app_root / "app" / "backend" / "alembic" / "env.py",
        app_root / "launchers" / "maintenance" / "invoke_backend_maintenance.py",
        app_root / "launchers" / "enable_windows_long_paths.py",
    ]
    daemon_entry = release_manifest.get("inference_daemon")
    if not isinstance(daemon_entry, dict):
        raise ValueError("release manifest 必须包含 inference_daemon")
    required_paths.append(resolve_path(app_root, str(daemon_entry["python_launcher"])))
    for worker_entry in worker_entries:
        required_paths.append(
            resolve_path(app_root, str(worker_entry["python_launcher"]))
        )
        required_paths.append(resolve_path(app_root, str(worker_entry["manifest"])))

    missing_paths = [str(path) for path in required_paths if not path.exists()]
    if missing_paths:
        raise FileNotFoundError(
            "full 一键启动缺少必要文件: " + ", ".join(missing_paths)
        )


def _build_service_command(
    app_root: Path,
    release_manifest: dict[str, object],
    *,
    python_executable: str,
    host: str,
    port: int,
    service_log_level: str,
) -> list[str]:
    """构造 backend-service 子进程命令。

    参数：
    - app_root：当前应用根目录。
    - release_manifest：release manifest 内容。
    - python_executable：要使用的 Python 解释器路径。
    - host：监听地址。
    - port：监听端口。
    - service_log_level：uvicorn 日志级别。

    返回：
    - list[str]：可直接传给 subprocess 的命令列表。
    """

    service_entry = release_manifest["service"]
    assert isinstance(service_entry, dict)
    service_launcher_path = resolve_path(
        app_root, str(service_entry["python_launcher"])
    )
    return [
        python_executable,
        str(service_launcher_path),
        "--app-root",
        str(app_root),
        "--python-executable",
        python_executable,
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        service_log_level,
    ]


def _build_inference_daemon_command(
    app_root: Path,
    release_manifest: dict[str, object],
    *,
    python_executable: str,
) -> list[str]:
    """构造独立 inference daemon 子进程命令。"""

    daemon_entry = release_manifest.get("inference_daemon")
    if not isinstance(daemon_entry, dict):
        raise ValueError("release manifest 必须包含 inference_daemon")
    launcher_path = resolve_path(
        app_root, str(daemon_entry.get("python_launcher") or "")
    )
    return [
        python_executable,
        str(launcher_path),
        "--app-root",
        str(app_root),
        "--python-executable",
        python_executable,
    ]


def _build_database_migration_command(
    app_root: Path,
    *,
    python_executable: str,
) -> list[str]:
    """构造发布启动前的数据库迁移命令。"""

    maintenance_launcher = (
        app_root / "launchers" / "maintenance" / "invoke_backend_maintenance.py"
    )
    return [
        python_executable,
        str(maintenance_launcher),
        "--python-executable",
        python_executable,
        "migrate-database",
        "--output",
        "text",
    ]


def _build_worker_command(
    app_root: Path,
    worker_entry: dict[str, object],
    *,
    python_executable: str,
    topology: object,
    worker_instance_id: str,
    worker_runtime_root: Path,
) -> list[str]:
    """构造单个 worker 子进程命令。

    参数：
    - app_root：当前应用根目录。
    - worker_entry：worker manifest 条目。
    - python_executable：要使用的 Python 解释器路径。

    返回：
    - list[str]：可直接传给 subprocess 的命令列表。
    """

    worker_launcher_path = resolve_path(app_root, str(worker_entry["python_launcher"]))
    return [
        python_executable,
        str(worker_launcher_path),
        "--app-root",
        str(app_root),
        "--python-executable",
        python_executable,
        "--worker-profile-file",
        str(worker_entry["manifest"]),
        "--topology-id",
        str(getattr(topology, "topology_id")),
        "--topology-generation",
        str(getattr(topology, "topology_generation")),
        "--topology-epoch-id",
        str(getattr(topology, "topology_epoch_id")),
        "--worker-instance-id",
        worker_instance_id,
        "--worker-runtime-root",
        str(worker_runtime_root),
    ]


def _import_worker_runtime_modules(app_root: Path) -> tuple[object, object]:
    """从源码或发布目录导入 Worker 运行契约和单实例锁模块。"""

    backend_root = app_root if (app_root / "backend").is_dir() else app_root / "app"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    contracts = importlib.import_module("backend.workers.contracts")
    profile_lock = importlib.import_module("backend.workers.profile_lock")
    return contracts, profile_lock


def _acquire_topology_lock(app_root: Path) -> tuple[object, str]:
    """获取唯一 Topology 锁，并返回本次 Supervisor 实例 id。"""

    contracts, profile_lock_module = _import_worker_runtime_modules(app_root)
    layout = contracts.BackendWorkerRuntimeLayout(
        (app_root / "data" / "runtime" / "backend-workers").resolve()
    )
    supervisor_instance_id = f"supervisor-{uuid4().hex}"
    topology_lock = profile_lock_module.BackendWorkerProfileLock(
        lock_path=layout.topology_lock_path,
        owner={
            "topology_id": contracts.WORKER_TOPOLOGY_ID,
            "supervisor_instance_id": supervisor_instance_id,
        },
    )
    topology_lock.acquire()
    return topology_lock, supervisor_instance_id


def _activate_worker_topology(
    app_root: Path,
    worker_entries: list[dict[str, object]],
    *,
    supervisor_instance_id: str,
) -> tuple[object, object, dict[str, object]]:
    """创建并原子激活一代严格 Worker Topology。"""

    contracts, _profile_lock_module = _import_worker_runtime_modules(app_root)
    layout = contracts.BackendWorkerRuntimeLayout(
        (app_root / "data" / "runtime" / "backend-workers").resolve()
    )
    topology_generation = 1
    if layout.active_topology_path.is_file():
        try:
            previous = contracts.load_worker_topology_pointer(
                layout.active_topology_path
            )
        except (OSError, ValueError):
            previous = None
        if previous is not None:
            topology_generation = previous.topology_generation + 1
    profiles: dict[str, object] = {}
    for worker_entry in worker_entries:
        profile_path = resolve_path(app_root, str(worker_entry["manifest"]))
        profile = contracts.load_worker_profile_manifest(profile_path)
        declared_profile_id = str(worker_entry.get("profile_id") or "")
        if profile.profile_id != declared_profile_id:
            raise ValueError(
                "release manifest 的 worker profile_id 与 Profile Manifest 不一致: "
                f"declared={declared_profile_id!r}, actual={profile.profile_id!r}"
            )
        if profile.profile_id in profiles:
            raise ValueError(
                f"release manifest 重复声明 worker profile: {profile.profile_id}"
            )
        profiles[profile.profile_id] = profile
    topology = contracts.WorkerTopologyManifest(
        format_id=contracts.WORKER_TOPOLOGY_FORMAT_ID,
        topology_id=contracts.WORKER_TOPOLOGY_ID,
        topology_generation=topology_generation,
        topology_epoch_id=f"epoch-{uuid4().hex}",
        state="starting",
        supervisor_instance_id=supervisor_instance_id,
        activated_at=contracts.utc_now(),
        heartbeat_interval_seconds=2.0,
        stale_after_seconds=15.0,
        expected_profiles=tuple(
            contracts.WorkerTopologyProfile.from_manifest(profile)
            for profile in profiles.values()
        ),
    )
    contracts.write_worker_contract(
        layout.topology_manifest_path(topology.topology_epoch_id),
        topology,
    )
    contracts.write_worker_contract(
        layout.active_topology_path,
        contracts.build_topology_pointer(topology),
    )
    return layout, topology, profiles


def _update_worker_topology_state(
    app_root: Path,
    *,
    layout: object,
    topology: object,
    state: str,
) -> object:
    """更新当前 epoch 的 Supervisor 状态，并保持身份和 Profile 不变。"""

    contracts, _profile_lock_module = _import_worker_runtime_modules(app_root)
    updated = topology.model_copy(update={"state": state})
    contracts.write_worker_contract(
        layout.topology_manifest_path(updated.topology_epoch_id),
        updated,
    )
    return updated


def _start_component(
    component_name: str,
    command: list[str],
    *,
    app_root: Path,
    log_file_path: Path,
) -> tuple[subprocess.Popen[bytes], DailyAppendLogCapture]:
    """启动一个受监督的子进程，并把输出写入日志文件。

    参数：
    - component_name：组件名称，仅用于控制台提示。
    - command：启动命令。
    - app_root：当前应用根目录。
    - log_file_path：日志文件路径。

    返回：
    - 子进程对象和按日日志捕获器。
    """

    log_capture = DailyAppendLogCapture(
        logs_dir=log_file_path.parent,
        component_name=log_file_path.stem,
    )
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=str(app_root),
        env=_build_child_process_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    assert process.stdout is not None
    log_capture.start(process.stdout)
    print(
        f"已启动 {component_name}，pid={process.pid}，"
        f"日志={_format_runtime_path(app_root, log_capture.current_log_path)}",
        flush=True,
    )
    return process, log_capture


def _resolve_health_host(host: str) -> str:
    """把监听地址转换成当前机器可访问的 health 探测地址。"""

    normalized_host = host.strip()
    if normalized_host in {"", "0.0.0.0", "::"}:
        return "127.0.0.1"
    return normalized_host


def _wait_for_backend_service_ready(
    *,
    host: str,
    port: int,
    timeout_seconds: float,
    process: subprocess.Popen[bytes],
) -> None:
    """等待 backend-service health endpoint 可用。

    说明：
    - backend-service 负责数据库 schema 和 seeder 初始化。
    - worker profiles 必须等该初始化完成后再启动。
    """

    deadline = time.monotonic() + max(1.0, timeout_seconds)
    health_url = f"http://{_resolve_health_host(host)}:{port}/api/v1/system/health"
    last_error = ""
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(f"backend-service 已退出，returncode={return_code}")
        try:
            with urllib.request.urlopen(health_url, timeout=5.0) as response:
                if response.status < 500:
                    print(
                        "backend-service health 已就绪，开始启动 worker。", flush=True
                    )
                    return
                last_error = f"HTTP {response.status}"
        except (OSError, urllib.error.URLError) as error:
            last_error = str(error)
        time.sleep(1.0)

    raise TimeoutError(
        f"backend-service health 未在 {timeout_seconds:.0f}s 内就绪：{last_error}"
    )


def _wait_for_worker_ready(
    *,
    app_root: Path,
    component_name: str,
    process: subprocess.Popen[bytes],
    log_capture: DailyAppendLogCapture,
    timeout_seconds: float,
    worker_runtime_layout: object,
    topology: object,
    profile: object,
) -> None:
    """等待 backend-worker 完成初始化。

    说明：
    - 就绪只以当前 Topology epoch 的严格心跳为准，不解析日志文本。
    - 如果 worker 在初始化阶段退出，仍附带当日日志尾部帮助定位。
    """

    deadline = time.monotonic() + max(1.0, timeout_seconds)
    contracts, _profile_lock_module = _import_worker_runtime_modules(app_root)
    heartbeat_path = worker_runtime_layout.profile_heartbeat_path(
        topology.topology_epoch_id,
        profile.profile_id,
    )
    while time.monotonic() < deadline:
        return_code = process.poll()
        if heartbeat_path.is_file():
            try:
                heartbeat = contracts.load_worker_heartbeat(heartbeat_path)
            except (OSError, ValueError):
                heartbeat = None
            if heartbeat is not None:
                heartbeat_identity = (
                    heartbeat.topology_id,
                    heartbeat.topology_generation,
                    heartbeat.topology_epoch_id,
                    heartbeat.profile_id,
                    heartbeat.profile_fingerprint,
                )
                expected_identity = (
                    topology.topology_id,
                    topology.topology_generation,
                    topology.topology_epoch_id,
                    profile.profile_id,
                    profile.fingerprint(),
                )
                if (
                    heartbeat_identity == expected_identity
                    and heartbeat.status == "running"
                ):
                    print(
                        f"{component_name} 已就绪，worker_instance_id="
                        f"{heartbeat.worker_instance_id}。",
                        flush=True,
                    )
                    return
                if (
                    heartbeat_identity == expected_identity
                    and heartbeat.status == "failed"
                ):
                    raise RuntimeError(
                        f"{component_name} 初始化失败：{heartbeat.failure_message or 'unknown'}"
                    )
        if return_code is not None:
            raise RuntimeError(
                f"{component_name} 初始化失败，returncode={return_code}，"
                f"日志={_format_runtime_path(app_root, log_capture.current_log_path)}\n"
                f"{log_capture.tail_text()}"
            )
        time.sleep(0.2)

    raise TimeoutError(
        f"{component_name} 未在 {timeout_seconds:.0f}s 内完成初始化，"
        f"日志={_format_runtime_path(app_root, log_capture.current_log_path)}\n"
        f"{log_capture.tail_text()}"
    )


def _wait_for_inference_daemon_ready(
    *,
    app_root: Path,
    process: subprocess.Popen[bytes],
    log_capture: DailyAppendLogCapture,
    timeout_seconds: float,
    probe_command: list[str] | None = None,
) -> None:
    """等待 daemon 初始化，并用真实控制队列往返确认可用。"""

    deadline = time.monotonic() + max(1.0, timeout_seconds)
    ready_marker = "inference-daemon ready"
    last_probe_error = ""
    while time.monotonic() < deadline:
        return_code = process.poll()
        log_capture.assert_healthy()
        log_tail = log_capture.tail_text()
        if ready_marker in log_tail:
            if probe_command is None:
                print("inference-daemon 已就绪。", flush=True)
                return
            try:
                probe_result = subprocess.run(
                    [*probe_command, "--probe"],
                    cwd=str(app_root),
                    env=_build_child_process_environment(),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=min(30.0, max(1.0, deadline - time.monotonic())),
                )
            except subprocess.TimeoutExpired:
                last_probe_error = "probe 子进程超时"
                time.sleep(0.2)
                continue
            if probe_result.returncode == 0:
                print("inference-daemon 控制队列探测成功。", flush=True)
                return
            last_probe_error = f"probe returncode={probe_result.returncode}"
        if return_code is not None:
            raise RuntimeError(
                f"inference-daemon 初始化失败，returncode={return_code}，"
                f"日志={_format_runtime_path(app_root, log_capture.current_log_path)}\n{log_tail}"
            )
        time.sleep(0.2)
    raise TimeoutError(
        f"inference-daemon 未在 {timeout_seconds:.0f}s 内完成初始化，"
        f"日志={_format_runtime_path(app_root, log_capture.current_log_path)}\n"
        f"最近探测错误={last_probe_error}\n"
        f"{log_capture.tail_text()}"
    )


def _run_database_migration(
    *,
    app_root: Path,
    command: list[str],
    log_file_path: Path,
) -> None:
    """在任何常驻组件启动前完成数据库升级，失败时阻止整套服务启动。"""

    daily_log_file_path = build_daily_log_path(
        log_file_path.parent,
        log_file_path.stem,
    )
    daily_log_file_path.parent.mkdir(parents=True, exist_ok=True)
    with daily_log_file_path.open("ab") as log_handle:
        result = subprocess.run(
            command,
            cwd=str(app_root),
            env=_build_child_process_environment(),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError(
            "数据库迁移失败，禁止继续启动；"
            f"returncode={result.returncode}，"
            f"日志={_format_runtime_path(app_root, daily_log_file_path)}"
        )
    print("数据库 schema 已升级到当前版本。", flush=True)


def _write_stack_state(
    app_root: Path,
    *,
    state_file_path: Path,
    release_manifest_file: str,
    python_executable: str,
    logs_dir: Path,
    components: list[SupervisedComponent],
) -> None:
    """把当前 full stack 的运行状态写入状态文件。

    参数：
    - app_root：当前应用根目录。
    - state_file_path：运行状态文件路径。
    - release_manifest_file：release manifest 路径。
    - python_executable：当前使用的 Python 解释器路径。
    - logs_dir：当前日志目录。
    - components：已启动组件列表。
    """

    payload = {
        "format_id": FULL_SUPERVISOR_STATE_FORMAT_ID,
        "app_root": str(app_root),
        "root_process": read_process_identity(os.getpid()),
        "release_manifest_file": release_manifest_file,
        "python_executable": python_executable,
        "logs_dir": _format_runtime_path(app_root, logs_dir),
        "state_file": _format_runtime_path(app_root, state_file_path),
        "components": [
            _build_component_state(app_root, component) for component in components
        ],
    }
    state_file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_file_path.with_name(f"{state_file_path.name}.{os.getpid()}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(state_file_path)


def _build_component_state(
    app_root: Path,
    component: SupervisedComponent,
) -> dict[str, object]:
    """把一个 Supervisor 组件转换为可恢复的状态记录。"""

    process = component.process
    log_capture = component.log_capture
    process_identity: dict[str, object] | None = None
    if process is not None and process.poll() is None:
        with contextlib.suppress(Exception):
            process_identity = read_process_identity(process.pid)
    return {
        "name": component.name,
        "process": process_identity,
        "state": "running"
        if process is not None and process.poll() is None
        else "recovering",
        "profile_id": (
            str(component.worker_entry.get("profile_id"))
            if component.worker_entry is not None
            else None
        ),
        "restart_count": component.restart_count,
        "last_return_code": component.last_return_code,
        "log_file": (
            _format_runtime_path(app_root, log_capture.current_log_path)
            if log_capture is not None
            else None
        ),
        "log_pattern": log_capture.log_pattern if log_capture is not None else None,
        "stop_mode": "process-tree" if os.name == "nt" else "process-group",
    }


def _stop_component(process: subprocess.Popen[bytes]) -> None:
    """停止一个已经启动的子进程树。

    参数：
    - process：待停止的根子进程。
    """

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
            process.wait(timeout=10)
        return

    with contextlib.suppress(ProcessLookupError):
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=10)
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)


def _launch_worker_profile(
    *,
    app_root: Path,
    python_executable: str,
    logs_dir: Path,
    worker_entry: dict[str, object],
    profile: object,
    worker_runtime_layout: object,
    worker_topology: object,
    ready_timeout_seconds: float,
    on_started: Callable[[subprocess.Popen[bytes], DailyAppendLogCapture], None]
    | None = None,
) -> tuple[subprocess.Popen[bytes], DailyAppendLogCapture]:
    """启动一个 Worker Profile，并等待严格 epoch 心跳进入 running。"""

    profile_id = str(worker_entry["profile_id"])
    worker_process, worker_log_capture = _start_component(
        f"backend-worker:{profile_id}",
        _build_worker_command(
            app_root,
            worker_entry,
            python_executable=python_executable,
            topology=worker_topology,
            worker_instance_id=f"worker-{profile_id}-{uuid4().hex}",
            worker_runtime_root=worker_runtime_layout.root_dir,
        ),
        app_root=app_root,
        log_file_path=logs_dir / f"backend-worker-{profile_id}.log",
    )
    if on_started is not None:
        on_started(worker_process, worker_log_capture)
    try:
        _wait_for_worker_ready(
            app_root=app_root,
            component_name=f"backend-worker:{profile_id}",
            process=worker_process,
            log_capture=worker_log_capture,
            timeout_seconds=ready_timeout_seconds,
            worker_runtime_layout=worker_runtime_layout,
            topology=worker_topology,
            profile=profile,
        )
    except BaseException:
        _stop_component(worker_process)
        worker_log_capture.close()
        raise
    return worker_process, worker_log_capture


def _calculate_worker_restart_delay(restart_count: int) -> float:
    """返回无抖动、封顶的 Worker Profile 恢复退避秒数。"""

    return min(30.0, 2.0 ** max(0, min(restart_count - 1, 5)))


def main(argv: list[str] | None = None) -> int:
    """执行 full 发布目录一键启动入口。

    参数：
    - argv：可选命令行参数列表；未传入时读取进程参数。

    返回：
    - int：进程退出码。
    """

    parser = build_argument_parser()
    args = parser.parse_args(argv)
    app_root = resolve_app_root(
        script_file=Path(__file__), explicit_app_root=args.app_root
    )
    if not ensure_windows_long_paths_enabled(
        app_root=app_root,
        python_executable=args.python_executable,
    ):
        return WINDOWS_SYSTEM_CONFIGURATION_REQUIRED_EXIT_CODE
    state_file_path = _resolve_stack_state_file(
        app_root,
        logs_subdir=args.logs_subdir,
        explicit_state_file=args.state_file,
    )
    _ensure_stack_not_running(state_file_path)

    release_manifest_path = _resolve_release_manifest_path(
        app_root, args.release_manifest_file
    )
    release_manifest = _load_release_manifest(app_root, release_manifest_path)
    worker_entries = _select_worker_entries(release_manifest, args.worker_profile_id)
    _validate_required_files(app_root, release_manifest, worker_entries)

    bundled_python_executable = app_root / "python" / "python.exe"
    python_executable_path = (
        Path(args.python_executable).resolve()
        if args.python_executable
        else bundled_python_executable.resolve()
    )
    if not python_executable_path.is_file():
        raise FileNotFoundError(
            "full 发行目录缺少可用的 python/python.exe，禁止回退到系统 Python"
        )
    python_executable = str(python_executable_path)
    topology_lock, supervisor_instance_id = _acquire_topology_lock(app_root)
    worker_runtime_layout: object | None = None
    worker_topology: object | None = None
    worker_profiles: dict[str, object] = {}
    try:
        (
            worker_runtime_layout,
            worker_topology,
            worker_profiles,
        ) = _activate_worker_topology(
            app_root,
            worker_entries,
            supervisor_instance_id=supervisor_instance_id,
        )
    except BaseException:
        topology_lock.release()
        raise
    logs_dir = app_root / "logs" / args.logs_subdir
    components: list[SupervisedComponent] = []
    signal.signal(signal.SIGTERM, _request_stack_shutdown)
    if os.name == "nt" and hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _request_stack_shutdown)

    def persist_stack_state() -> None:
        """在每个组件启动后立即持久化 pid，保证启动中也能可靠停止。"""

        _write_stack_state(
            app_root,
            state_file_path=state_file_path,
            release_manifest_file=_format_runtime_path(app_root, release_manifest_path),
            python_executable=python_executable,
            logs_dir=logs_dir,
            components=components,
        )

    try:
        _run_database_migration(
            app_root=app_root,
            command=_build_database_migration_command(
                app_root,
                python_executable=python_executable,
            ),
            log_file_path=logs_dir / "database-migration.log",
        )
        daemon_log_file_path = logs_dir / "inference-daemon.log"
        daemon_process, daemon_log_capture = _start_component(
            "inference-daemon",
            _build_inference_daemon_command(
                app_root,
                release_manifest,
                python_executable=python_executable,
            ),
            app_root=app_root,
            log_file_path=daemon_log_file_path,
        )
        components.append(
            SupervisedComponent(
                name="inference-daemon",
                process=daemon_process,
                log_capture=daemon_log_capture,
                started_monotonic=time.monotonic(),
            )
        )
        persist_stack_state()
        _wait_for_inference_daemon_ready(
            app_root=app_root,
            process=daemon_process,
            log_capture=daemon_log_capture,
            timeout_seconds=args.service_ready_timeout_seconds,
            probe_command=_build_inference_daemon_command(
                app_root,
                release_manifest,
                python_executable=python_executable,
            ),
        )

        service_log_file_path = logs_dir / "backend-service.log"
        service_command = _build_service_command(
            app_root,
            release_manifest,
            python_executable=python_executable,
            host=args.host,
            port=args.port,
            service_log_level=args.service_log_level,
        )
        service_process, service_log_capture = _start_component(
            "backend-service",
            service_command,
            app_root=app_root,
            log_file_path=service_log_file_path,
        )
        components.append(
            SupervisedComponent(
                name="backend-service",
                process=service_process,
                log_capture=service_log_capture,
                started_monotonic=time.monotonic(),
            )
        )
        persist_stack_state()

        if args.startup_delay_seconds > 0:
            time.sleep(args.startup_delay_seconds)
        _wait_for_backend_service_ready(
            host=args.host,
            port=args.port,
            timeout_seconds=args.service_ready_timeout_seconds,
            process=service_process,
        )

        for worker_entry in worker_entries:
            profile_id = str(worker_entry["profile_id"])
            component = SupervisedComponent(
                name=f"backend-worker:{profile_id}",
                process=None,
                log_capture=None,
                worker_entry=worker_entry,
                worker_profile=worker_profiles[profile_id],
            )
            components.append(component)

            def record_worker_start(
                process: subprocess.Popen[bytes],
                log_capture: DailyAppendLogCapture,
                *,
                target: SupervisedComponent = component,
            ) -> None:
                """在启动等待前持久化新 Worker pid。"""

                target.process = process
                target.log_capture = log_capture
                target.started_monotonic = time.monotonic()
                persist_stack_state()

            worker_process, worker_log_capture = _launch_worker_profile(
                app_root=app_root,
                python_executable=python_executable,
                logs_dir=logs_dir,
                worker_entry=worker_entry,
                profile=worker_profiles[profile_id],
                worker_runtime_layout=worker_runtime_layout,
                worker_topology=worker_topology,
                ready_timeout_seconds=args.worker_ready_timeout_seconds,
                on_started=record_worker_start,
            )
            component.process = worker_process
            component.log_capture = worker_log_capture
            component.started_monotonic = time.monotonic()
            component.restart_count = 0
            component.next_restart_at = None
            component.last_return_code = None
            persist_stack_state()

        worker_topology = _update_worker_topology_state(
            app_root,
            layout=worker_runtime_layout,
            topology=worker_topology,
            state="running",
        )
        persist_stack_state()
        print(
            f"运行状态文件已写入 {_format_runtime_path(app_root, state_file_path)}。",
            flush=True,
        )
        print("full 发布目录全部组件已启动。按 Ctrl+C 停止全部子进程。", flush=True)

        while True:
            now = time.monotonic()
            for component in components:
                process = component.process
                log_capture = component.log_capture
                if log_capture is not None:
                    log_capture.assert_healthy()
                if process is not None:
                    return_code = process.poll()
                    if return_code is None:
                        continue
                    component.last_return_code = return_code
                    if not component.is_worker:
                        print(
                            f"检测到 {component.name} 已退出，returncode={return_code}；"
                            "正在停止整套服务。",
                            flush=True,
                        )
                        return 1 if return_code == 0 else return_code
                    if log_capture is not None:
                        log_capture.close()
                    if now - component.started_monotonic >= 300:
                        component.restart_count = 0
                    component.restart_count += 1
                    component.process = None
                    component.log_capture = None
                    restart_delay = _calculate_worker_restart_delay(
                        component.restart_count
                    )
                    component.next_restart_at = now + restart_delay
                    print(
                        f"{component.name} 已退出，returncode={return_code}；"
                        f"仅恢复该 Profile，{restart_delay:.0f}s 后重启。",
                        flush=True,
                    )
                    persist_stack_state()
                    continue
                if not component.is_worker:
                    continue
                restart_at = component.next_restart_at
                if restart_at is None or now < restart_at:
                    continue

                def record_recovery_start(
                    recovered_process: subprocess.Popen[bytes],
                    recovered_log_capture: DailyAppendLogCapture,
                    *,
                    target: SupervisedComponent = component,
                ) -> None:
                    """持久化恢复中的 Worker 新进程身份。"""

                    target.process = recovered_process
                    target.log_capture = recovered_log_capture
                    target.started_monotonic = time.monotonic()
                    target.next_restart_at = None
                    persist_stack_state()

                try:
                    recovered_process, recovered_log_capture = _launch_worker_profile(
                        app_root=app_root,
                        python_executable=python_executable,
                        logs_dir=logs_dir,
                        worker_entry=component.worker_entry,
                        profile=component.worker_profile,
                        worker_runtime_layout=worker_runtime_layout,
                        worker_topology=worker_topology,
                        ready_timeout_seconds=args.worker_ready_timeout_seconds,
                        on_started=record_recovery_start,
                    )
                except Exception as error:  # noqa: BLE001 - 单 Profile 故障不停止整栈
                    component.process = None
                    component.log_capture = None
                    component.restart_count += 1
                    restart_delay = _calculate_worker_restart_delay(
                        component.restart_count
                    )
                    component.next_restart_at = time.monotonic() + restart_delay
                    print(
                        f"{component.name} 恢复失败：{error}；"
                        f"{restart_delay:.0f}s 后再次启动该 Profile。",
                        flush=True,
                    )
                    persist_stack_state()
                    continue
                component.process = recovered_process
                component.log_capture = recovered_log_capture
                component.started_monotonic = time.monotonic()
                component.next_restart_at = None
                component.last_return_code = None
                print(f"{component.name} 已独立恢复。", flush=True)
                persist_stack_state()
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("收到终止信号，正在停止全部子进程。", flush=True)
        return 0
    finally:
        if worker_runtime_layout is not None and worker_topology is not None:
            with contextlib.suppress(Exception):
                worker_topology = _update_worker_topology_state(
                    app_root,
                    layout=worker_runtime_layout,
                    topology=worker_topology,
                    state="stopping",
                )
        for component in reversed(components):
            if component.process is not None:
                _stop_component(component.process)
        for component in components:
            if component.log_capture is not None:
                with contextlib.suppress(Exception):
                    component.log_capture.close()
        if worker_runtime_layout is not None and worker_topology is not None:
            with contextlib.suppress(Exception):
                worker_topology = _update_worker_topology_state(
                    app_root,
                    layout=worker_runtime_layout,
                    topology=worker_topology,
                    state="stopped",
                )
        topology_lock.release()
        with contextlib.suppress(FileNotFoundError):
            state_file_path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
