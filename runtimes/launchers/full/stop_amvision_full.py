"""full 发布目录一键停止入口。"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


LAUNCHERS_ROOT = Path(__file__).resolve().parent / "launchers"
if str(LAUNCHERS_ROOT) not in sys.path:
    sys.path.insert(0, str(LAUNCHERS_ROOT))

from common import resolve_app_root, resolve_path


def build_argument_parser() -> argparse.ArgumentParser:
    """构造 full 发布目录一键停止参数解析器。

    返回：
    - argparse.ArgumentParser：命令行参数解析器。
    """

    parser = argparse.ArgumentParser(description="amvision full stack stopper")
    parser.add_argument("--app-root", help="应用根目录；未传入时按脚本相对位置自动解析")
    parser.add_argument(
        "--logs-subdir",
        default="full-stack",
        help="运行状态文件所在的 logs 子目录名",
    )
    parser.add_argument(
        "--state-file",
        help="运行状态文件路径；未传入时默认读取 logs/<subdir>/runtime-state.json",
    )
    parser.add_argument(
        "--graceful-timeout-seconds",
        type=float,
        default=5.0,
        help="发送终止信号后等待进程退出的秒数",
    )
    return parser


def _resolve_stack_state_file(
    app_root: Path,
    *,
    logs_subdir: str,
    explicit_state_file: str | None,
) -> Path:
    """解析 full 一键停止使用的运行状态文件路径。

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
    """读取 full 一键停止的运行状态文件。

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

    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _wait_pid_exit(pid: int, timeout_seconds: float) -> bool:
    """等待指定 pid 在给定时间内退出。

    参数：
    - pid：待等待的进程 id。
    - timeout_seconds：等待秒数。

    返回：
    - bool：等待期间进程已退出时返回 True，否则返回 False。
    """

    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    while time.monotonic() < deadline:
        if not _pid_is_alive(pid):
            return True
        time.sleep(0.1)
    return not _pid_is_alive(pid)


def _stop_recorded_process(pid: int, *, stop_mode: str, graceful_timeout_seconds: float) -> bool:
    """按状态文件记录的方式停止一个进程或进程组。

    参数：
    - pid：待停止的进程 id。
    - stop_mode：停止模式；Windows 使用 process-tree，Unix 子进程使用 process-group。
    - graceful_timeout_seconds：发送终止信号后的等待秒数。

    返回：
    - bool：停止后进程已经退出时返回 True，否则返回 False。
    """

    if not _pid_is_alive(pid):
        return True

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return _wait_pid_exit(pid, graceful_timeout_seconds)

    if stop_mode == "process-group":
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGTERM)
        if _wait_pid_exit(pid, graceful_timeout_seconds):
            return True
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGKILL)
        return _wait_pid_exit(pid, 1.0)

    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    if _wait_pid_exit(pid, graceful_timeout_seconds):
        return True
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)
    return _wait_pid_exit(pid, 1.0)


def main(argv: list[str] | None = None) -> int:
    """执行 full 发布目录一键停止入口。

    参数：
    - argv：可选命令行参数列表；未传入时读取进程参数。

    返回：
    - int：进程退出码。
    """

    parser = build_argument_parser()
    args = parser.parse_args(argv)
    app_root = resolve_app_root(script_file=Path(__file__), explicit_app_root=args.app_root)
    state_file_path = _resolve_stack_state_file(
        app_root,
        logs_subdir=args.logs_subdir,
        explicit_state_file=args.state_file,
    )
    stack_state = _load_stack_state(state_file_path)
    if stack_state is None:
        print(f"未找到运行状态文件，无需停止：{state_file_path}", flush=True)
        return 0

    stop_targets: list[tuple[str, int, str]] = []
    seen_pids: set[int] = set()

    components_raw = stack_state.get("components")
    if isinstance(components_raw, list):
        for component_raw in reversed(components_raw):
            if not isinstance(component_raw, dict):
                continue
            pid_raw = component_raw.get("pid")
            if not isinstance(pid_raw, int) or pid_raw in seen_pids:
                continue
            stop_targets.append(
                (
                    str(component_raw.get("name", f"process-{pid_raw}")),
                    pid_raw,
                    str(component_raw.get("stop_mode", "process")),
                )
            )
            seen_pids.add(pid_raw)

    root_pid_raw = stack_state.get("root_pid")
    if isinstance(root_pid_raw, int) and root_pid_raw not in seen_pids:
        stop_targets.append(("full-stack-root", root_pid_raw, "process"))

    if not stop_targets:
        with contextlib.suppress(FileNotFoundError):
            state_file_path.unlink()
        print(f"运行状态文件中没有可停止的进程，已清理：{state_file_path}", flush=True)
        return 0

    for component_name, pid, stop_mode in stop_targets:
        if not _pid_is_alive(pid):
            print(f"{component_name} 已经退出，pid={pid}", flush=True)
            continue
        print(f"正在停止 {component_name}，pid={pid}", flush=True)
        stopped = _stop_recorded_process(
            pid,
            stop_mode=stop_mode,
            graceful_timeout_seconds=args.graceful_timeout_seconds,
        )
        if stopped:
            print(f"已停止 {component_name}，pid={pid}", flush=True)
            continue
        print(f"停止 {component_name} 超时，pid={pid}", flush=True)

    with contextlib.suppress(FileNotFoundError):
        state_file_path.unlink()
    print(f"已清理运行状态文件：{state_file_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())