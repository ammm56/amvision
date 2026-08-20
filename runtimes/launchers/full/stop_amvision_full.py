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

from common import (  # noqa: E402
    process_identity_matches,
    resolve_app_root,
    resolve_path,
)

_ROOT_PROCESS_MIN_EXIT_WAIT_SECONDS = 15.0
FULL_SUPERVISOR_STATE_FORMAT_ID = "amvision.full-supervisor-state.v1"


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
        default=30.0,
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


def _wait_process_exit(identity: dict[str, object], timeout_seconds: float) -> bool:
    """等待状态文件记录的同一个进程退出。

    参数：
    - identity：包含 PID、创建时间、可执行文件、cwd 和命令行的进程身份。
    - timeout_seconds：等待秒数。

    返回：
    - bool：等待期间进程已退出时返回 True，否则返回 False。
    """

    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    while time.monotonic() < deadline:
        if not process_identity_matches(identity):
            return True
        time.sleep(0.1)
    return not process_identity_matches(identity)


def _stop_recorded_process(
    identity: dict[str, object],
    *,
    stop_mode: str,
    graceful_timeout_seconds: float,
) -> bool:
    """按状态文件记录的方式停止一个进程或进程组。

    参数：
    - identity：状态文件记录的完整进程身份。
    - stop_mode：停止模式；Windows 使用 process-tree，Unix 子进程使用 process-group。
    - graceful_timeout_seconds：发送终止信号后的等待秒数。

    返回：
    - bool：停止后进程已经退出时返回 True，否则返回 False。
    """

    if not process_identity_matches(identity):
        return True
    pid = identity["pid"]
    assert isinstance(pid, int)

    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return _wait_process_exit(identity, graceful_timeout_seconds)

    if stop_mode == "process-group":
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGTERM)
        if _wait_process_exit(identity, graceful_timeout_seconds):
            return True
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGKILL)
        return _wait_process_exit(identity, 1.0)

    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    if _wait_process_exit(identity, graceful_timeout_seconds):
        return True
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)
    return _wait_process_exit(identity, 1.0)


def _wait_root_process_exit(
    identity: dict[str, object],
    *,
    graceful_timeout_seconds: float,
) -> bool:
    """等待 full-stack root 在停掉子组件后自行收尾退出。

    参数：
    - identity：root 进程完整身份。
    - graceful_timeout_seconds：命令行传入的基础等待秒数。

    返回：
    - bool：等待窗口内 root 已退出时返回 True，否则返回 False。
    """

    return _wait_process_exit(
        identity,
        max(graceful_timeout_seconds, _ROOT_PROCESS_MIN_EXIT_WAIT_SECONDS),
    )


def main(argv: list[str] | None = None) -> int:
    """执行 full 发布目录一键停止入口。

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
    stack_state = _load_stack_state(state_file_path)
    if stack_state is None:
        print(f"未找到运行状态文件，无需停止：{state_file_path}", flush=True)
        return 0
    if stack_state.get("format_id") != FULL_SUPERVISOR_STATE_FORMAT_ID:
        print(
            f"运行状态文件格式无效，拒绝按 PID 停止未知进程：{state_file_path}",
            flush=True,
        )
        return 2

    stop_targets: list[tuple[str, dict[str, object], str]] = []
    seen_pids: set[int] = set()
    root_identity: dict[str, object] | None = None

    components_raw = stack_state.get("components")
    if isinstance(components_raw, list):
        for component_raw in reversed(components_raw):
            if not isinstance(component_raw, dict):
                continue
            process_identity = component_raw.get("process")
            if not isinstance(process_identity, dict):
                continue
            pid_raw = process_identity.get("pid")
            if not isinstance(pid_raw, int) or pid_raw in seen_pids:
                continue
            stop_targets.append(
                (
                    str(component_raw.get("name", f"process-{pid_raw}")),
                    process_identity,
                    str(component_raw.get("stop_mode", "process")),
                )
            )
            seen_pids.add(pid_raw)

    root_process_raw = stack_state.get("root_process")
    if isinstance(root_process_raw, dict):
        root_pid_raw = root_process_raw.get("pid")
        if isinstance(root_pid_raw, int) and root_pid_raw not in seen_pids:
            root_identity = root_process_raw

    if not stop_targets and root_identity is None:
        with contextlib.suppress(FileNotFoundError):
            state_file_path.unlink()
        print(f"运行状态文件中没有可停止的进程，已清理：{state_file_path}", flush=True)
        return 0

    failed_targets: list[tuple[str, int]] = []
    for component_name, identity, stop_mode in stop_targets:
        pid = identity["pid"]
        assert isinstance(pid, int)
        if not process_identity_matches(identity):
            print(f"{component_name} 已经退出，pid={pid}", flush=True)
            continue
        print(f"正在停止 {component_name}，pid={pid}", flush=True)
        stopped = _stop_recorded_process(
            identity,
            stop_mode=stop_mode,
            graceful_timeout_seconds=args.graceful_timeout_seconds,
        )
        if stopped:
            print(f"已停止 {component_name}，pid={pid}", flush=True)
            continue
        print(f"停止 {component_name} 超时，pid={pid}", flush=True)
        failed_targets.append((component_name, pid))

    if root_identity is not None:
        root_pid = root_identity["pid"]
        assert isinstance(root_pid, int)
        if not process_identity_matches(root_identity):
            print(f"full-stack-root 已经退出，pid={root_pid}", flush=True)
        elif stop_targets:
            print(f"等待 full-stack-root 自行退出，pid={root_pid}", flush=True)
            if _wait_root_process_exit(
                root_identity,
                graceful_timeout_seconds=args.graceful_timeout_seconds,
            ):
                print(f"已停止 full-stack-root，pid={root_pid}", flush=True)
            else:
                print(
                    f"full-stack-root 未在等待窗口内退出，转入强制停止，pid={root_pid}",
                    flush=True,
                )
                stopped = _stop_recorded_process(
                    root_identity,
                    stop_mode="process",
                    graceful_timeout_seconds=args.graceful_timeout_seconds,
                )
                if stopped:
                    print(f"已停止 full-stack-root，pid={root_pid}", flush=True)
                else:
                    print(f"停止 full-stack-root 超时，pid={root_pid}", flush=True)
                    failed_targets.append(("full-stack-root", root_pid))
        else:
            print(f"正在停止 full-stack-root，pid={root_pid}", flush=True)
            stopped = _stop_recorded_process(
                root_identity,
                stop_mode="process",
                graceful_timeout_seconds=args.graceful_timeout_seconds,
            )
            if stopped:
                print(f"已停止 full-stack-root，pid={root_pid}", flush=True)
            else:
                print(f"停止 full-stack-root 超时，pid={root_pid}", flush=True)
                failed_targets.append(("full-stack-root", root_pid))

    still_alive_targets = [
        (component_name, pid)
        for component_name, pid in failed_targets
        if any(
            isinstance(identity.get("pid"), int)
            and identity.get("pid") == pid
            and process_identity_matches(identity)
            for _name, identity, _mode in stop_targets
        )
        or (
            root_identity is not None
            and root_identity.get("pid") == pid
            and process_identity_matches(root_identity)
        )
    ]
    if still_alive_targets:
        failed_text = ", ".join(
            f"{name}(pid={pid})" for name, pid in still_alive_targets
        )
        print(
            f"仍有进程未停止，保留运行状态文件以便继续排查：{failed_text}；"
            f"state_file={state_file_path}",
            flush=True,
        )
        return 2

    with contextlib.suppress(FileNotFoundError):
        state_file_path.unlink()
    print(f"已清理运行状态文件：{state_file_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
