"""full 发布目录一键停止入口。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


SCRIPT_FILE = Path(__file__).resolve()
RELEASE_LAUNCHERS_ROOT = SCRIPT_FILE.parent / "launchers"
LAUNCHERS_ROOT = (
    RELEASE_LAUNCHERS_ROOT
    if (RELEASE_LAUNCHERS_ROOT / "common.py").is_file()
    else SCRIPT_FILE.parents[1]
)
if str(LAUNCHERS_ROOT) not in sys.path:
    sys.path.insert(0, str(LAUNCHERS_ROOT))

from common import (  # noqa: E402
    clear_full_state,
    full_state_guard,
    process_identity_matches,
    resolve_app_root,
    resolve_code_root,
    resolve_path,
)

_ROOT_PROCESS_MIN_EXIT_WAIT_SECONDS = 15.0
FULL_SUPERVISOR_STATE_FORMAT_ID = "amvision.full-supervisor-state.v3"
FULL_SUPERVISOR_SHUTDOWN_FORMAT_ID = "amvision.full-supervisor-shutdown.v1"


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
    parser.add_argument("--expected-root-identity-file", help="启动器提供的本次 root 身份 JSON 文件")
    parser.add_argument("--graceful-only", action="store_true", help="仅等待优雅退出，超时不强杀")
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


def _resolve_shutdown_request_file(state_file_path: Path) -> Path:
    """返回与运行状态文件绑定的优雅停止请求文件路径。"""

    return state_file_path.with_name(
        f"{state_file_path.stem}.shutdown-request.json"
    )


def _write_shutdown_request(
    shutdown_request_file_path: Path,
    *,
    root_process_identity: dict[str, object],
) -> None:
    """原子写入只对当前 full Supervisor 生效的优雅停止请求。"""

    payload = {
        "format_id": FULL_SUPERVISOR_SHUTDOWN_FORMAT_ID,
        "root_process": root_process_identity,
    }
    shutdown_request_file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = shutdown_request_file_path.with_name(
        f"{shutdown_request_file_path.name}.{os.getpid()}.tmp"
    )
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(shutdown_request_file_path)


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
    code_root = resolve_code_root(app_root)
    if str(code_root) not in sys.path:
        sys.path.insert(0, str(code_root))
    state_file_path = _resolve_stack_state_file(
        app_root,
        logs_subdir=args.logs_subdir,
        explicit_state_file=args.state_file,
    )
    stack_state = _load_stack_state(state_file_path)
    expected_root: dict[str, object] | None = None
    if args.expected_root_identity_file:
        try:
            request = json.loads(Path(args.expected_root_identity_file).read_text(encoding="utf-8"))
            if request.get("format_id") != "amvision.launcher-stop-target.v2" or not isinstance(request.get("root_process"), dict):
                raise ValueError("预期 root 身份格式无效")
            expected_root = request["root_process"]
        except (OSError, ValueError, AttributeError) as error:
            print(f"停止请求无效：{error}", flush=True)
            return 2
        if stack_state is None:
            if process_identity_matches(expected_root):
                print("本次 root 仍存活但状态文件尚未出现，请继续等待。", flush=True)
                return 2
        elif stack_state.get("root_process") != expected_root:
            print("运行状态已属于另一个 root，拒绝停止。", flush=True)
            return 2
    if stack_state is None:
        print(f"未找到运行状态文件，无需停止：{state_file_path}", flush=True)
        return 0
    if stack_state.get("format_id") != FULL_SUPERVISOR_STATE_FORMAT_ID:
        print(
            f"运行状态文件格式无效，拒绝按 PID 停止未知进程：{state_file_path}",
            flush=True,
        )
        return 2
    shutdown_request_file_path = _resolve_shutdown_request_file(state_file_path)

    from backend.runtime.processes.ownership import OwnershipScope
    from backend.runtime.processes.owner_control import stop_owner

    root_identity = stack_state.get("root_process")
    if not isinstance(root_identity, dict) or not stack_state.get("ownership_scope"):
        print("运行状态缺少完整归属，拒绝停止及清理。", flush=True)
        return 2
    scope = OwnershipScope(Path(stack_state["ownership_scope"]))
    try:
        scope.validate()
        if process_identity_matches(root_identity):
            with full_state_guard(state_file_path):
                current = _load_stack_state(state_file_path)
                if current is None or current.get("root_process") != root_identity:
                    print("停止目标已经改变，拒绝操作。", flush=True)
                    return 2
                _write_shutdown_request(shutdown_request_file_path, root_process_identity=root_identity)
            exited = _wait_root_process_exit(root_identity, graceful_timeout_seconds=args.graceful_timeout_seconds)
            if not exited:
                if args.graceful_only:
                    print("本次运行尚未退出，保留归属以便重试。", flush=True)
                    return 2
                # 封闭组登记后停止唯一 owner，禁止它继续创建下一代。
                scope.seal()
                stop_owner(root_identity, timeout=args.graceful_timeout_seconds)
        if args.graceful_only:
            scope.require_empty()
        else:
            scope.stop(timeout=args.graceful_timeout_seconds)
            scope.require_empty()
        clear_full_state(state_file_path, root_identity)
        print("已确认全部受管进程组退出并清理本次运行状态。", flush=True)
        return 0
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        print(f"停止未完成，保留归属记录：{error}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
