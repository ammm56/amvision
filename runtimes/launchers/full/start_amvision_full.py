"""full 发布目录一键启动入口。"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import BinaryIO


LAUNCHERS_ROOT = Path(__file__).resolve().parent / "launchers"
if str(LAUNCHERS_ROOT) not in sys.path:
    sys.path.insert(0, str(LAUNCHERS_ROOT))

from common import is_pid_alive, resolve_app_root, resolve_path  # noqa: E402


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


def _pid_is_alive(pid: int) -> bool:
    """判断指定 pid 当前是否仍然存活。

    参数：
    - pid：待检查的进程 id。

    返回：
    - bool：进程仍然存活时返回 True，否则返回 False。
    """

    return is_pid_alive(pid)


def _ensure_stack_not_running(state_file_path: Path) -> None:
    """确认当前不存在活跃的 full 一键启动实例。

    参数：
    - state_file_path：运行状态文件路径。
    """

    stack_state = _load_stack_state(state_file_path)
    if stack_state is None:
        return

    active_pids: list[int] = []
    root_pid_raw = stack_state.get("root_pid")
    if isinstance(root_pid_raw, int) and _pid_is_alive(root_pid_raw):
        active_pids.append(root_pid_raw)

    components_raw = stack_state.get("components")
    if isinstance(components_raw, list):
        for component_raw in components_raw:
            if not isinstance(component_raw, dict):
                continue
            pid_raw = component_raw.get("pid")
            if isinstance(pid_raw, int) and _pid_is_alive(pid_raw):
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
        raise FileNotFoundError(f"文件不存在: {_format_runtime_path(app_root, manifest_path)}")
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
    ]
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
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        service_log_level,
    ]


def _build_worker_command(
    app_root: Path,
    worker_entry: dict[str, object],
    *,
    python_executable: str,
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
        "--worker-profile-file",
        str(worker_entry["manifest"]),
    ]


def _start_component(
    component_name: str,
    command: list[str],
    *,
    app_root: Path,
    log_file_path: Path,
) -> tuple[subprocess.Popen[bytes], BinaryIO]:
    """启动一个受监督的子进程，并把输出写入日志文件。

    参数：
    - component_name：组件名称，仅用于控制台提示。
    - command：启动命令。
    - app_root：当前应用根目录。
    - log_file_path：日志文件路径。

    返回：
    - tuple[subprocess.Popen[bytes], BinaryIO]：子进程对象和打开中的日志句柄。
    """

    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_file_path.open("ab")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=str(app_root),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    print(
        f"已启动 {component_name}，pid={process.pid}，日志={_format_runtime_path(app_root, log_file_path)}",
        flush=True,
    )
    return process, log_handle


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


def _read_log_tail(log_file_path: Path, *, max_bytes: int = 4096) -> str:
    """读取日志尾部，供启动失败时输出关键线索。"""

    if not log_file_path.is_file():
        return ""
    with log_file_path.open("rb") as log_file:
        log_file.seek(0, os.SEEK_END)
        file_size = log_file.tell()
        log_file.seek(max(0, file_size - max_bytes))
        return log_file.read().decode("utf-8", errors="replace")


def _wait_for_worker_ready(
    *,
    app_root: Path,
    component_name: str,
    process: subprocess.Popen[bytes],
    log_file_path: Path,
    timeout_seconds: float,
) -> None:
    """等待 backend-worker 完成初始化。

    说明：
    - worker 只有打印 backend-worker ready 后才真正进入轮询循环。
    - 如果 worker 在初始化阶段退出，立即带日志尾部报错，避免现场只看到 returncode。
    """

    deadline = time.monotonic() + max(1.0, timeout_seconds)
    ready_marker = "backend-worker ready"
    while time.monotonic() < deadline:
        return_code = process.poll()
        log_tail = _read_log_tail(log_file_path)
        if ready_marker in log_tail:
            print(f"{component_name} 已就绪。", flush=True)
            return
        if return_code is not None:
            raise RuntimeError(
                f"{component_name} 初始化失败，returncode={return_code}，"
                f"日志={_format_runtime_path(app_root, log_file_path)}\n"
                f"{log_tail}"
            )
        time.sleep(0.2)

    raise TimeoutError(
        f"{component_name} 未在 {timeout_seconds:.0f}s 内完成初始化，"
        f"日志={_format_runtime_path(app_root, log_file_path)}\n"
        f"{_read_log_tail(log_file_path)}"
    )


def _write_stack_state(
    app_root: Path,
    *,
    state_file_path: Path,
    release_manifest_file: str,
    python_executable: str,
    logs_dir: Path,
    components: list[tuple[str, subprocess.Popen[bytes], BinaryIO, Path]],
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
        "app_root": str(app_root),
        "root_pid": os.getpid(),
        "release_manifest_file": release_manifest_file,
        "python_executable": python_executable,
        "logs_dir": _format_runtime_path(app_root, logs_dir),
        "state_file": _format_runtime_path(app_root, state_file_path),
        "components": [
            {
                "name": component_name,
                "pid": process.pid,
                "log_file": _format_runtime_path(app_root, log_file_path),
                "stop_mode": "process-tree" if os.name == "nt" else "process-group",
            }
            for component_name, process, _log_handle, log_file_path in components
        ],
    }
    state_file_path.parent.mkdir(parents=True, exist_ok=True)
    state_file_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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
    state_file_path = _resolve_stack_state_file(
        app_root,
        logs_subdir=args.logs_subdir,
        explicit_state_file=args.state_file,
    )
    _ensure_stack_not_running(state_file_path)

    release_manifest_path = _resolve_release_manifest_path(app_root, args.release_manifest_file)
    release_manifest = _load_release_manifest(app_root, release_manifest_path)
    worker_entries = _select_worker_entries(release_manifest, args.worker_profile_id)
    _validate_required_files(app_root, release_manifest, worker_entries)

    python_executable = args.python_executable or sys.executable
    logs_dir = app_root / "logs" / args.logs_subdir
    components: list[tuple[str, subprocess.Popen[bytes], BinaryIO, Path]] = []

    try:
        service_log_file_path = logs_dir / "service.log"
        service_command = _build_service_command(
            app_root,
            release_manifest,
            python_executable=python_executable,
            host=args.host,
            port=args.port,
            service_log_level=args.service_log_level,
        )
        service_process, service_log_handle = _start_component(
            "backend-service",
            service_command,
            app_root=app_root,
            log_file_path=service_log_file_path,
        )
        components.append(
            (
                "backend-service",
                service_process,
                service_log_handle,
                service_log_file_path,
            )
        )

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
            worker_log_file_path = logs_dir / f"worker-{profile_id}.log"
            worker_command = _build_worker_command(
                app_root,
                worker_entry,
                python_executable=python_executable,
            )
            worker_process, worker_log_handle = _start_component(
                f"backend-worker:{profile_id}",
                worker_command,
                app_root=app_root,
                log_file_path=worker_log_file_path,
            )
            components.append(
                (
                    f"backend-worker:{profile_id}",
                    worker_process,
                    worker_log_handle,
                    worker_log_file_path,
                )
            )
            _wait_for_worker_ready(
                app_root=app_root,
                component_name=f"backend-worker:{profile_id}",
                process=worker_process,
                log_file_path=worker_log_file_path,
                timeout_seconds=args.worker_ready_timeout_seconds,
            )

        _write_stack_state(
            app_root,
            state_file_path=state_file_path,
            release_manifest_file=_format_runtime_path(app_root, release_manifest_path),
            python_executable=python_executable,
            logs_dir=logs_dir,
            components=components,
        )
        print(
            f"运行状态文件已写入 {_format_runtime_path(app_root, state_file_path)}。",
            flush=True,
        )
        print("full 发布目录全部组件已启动。按 Ctrl+C 停止全部子进程。", flush=True)

        while True:
            for component_name, process, _log_handle, _log_file_path in components:
                return_code = process.poll()
                if return_code is None:
                    continue
                print(
                    f"检测到 {component_name} 已退出，returncode={return_code}；正在停止其余组件。",
                    flush=True,
                )
                return 1 if return_code == 0 else return_code
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("收到终止信号，正在停止全部子进程。", flush=True)
        return 0
    finally:
        for _component_name, process, _log_handle, _log_file_path in reversed(
            components
        ):
            _stop_component(process)
        for _component_name, _process, log_handle, _log_file_path in components:
            with contextlib.suppress(Exception):
                log_handle.close()
        with contextlib.suppress(FileNotFoundError):
            state_file_path.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
