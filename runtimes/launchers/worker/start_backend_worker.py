"""backend-worker Python launcher。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


LAUNCHERS_ROOT = Path(__file__).resolve().parents[1]
if str(LAUNCHERS_ROOT) not in sys.path:
    sys.path.insert(0, str(LAUNCHERS_ROOT))

from common import json_env_value, load_json_file, resolve_app_root, run_python_module


def build_argument_parser() -> argparse.ArgumentParser:
    """构造 backend-worker launcher 参数解析器。"""

    parser = argparse.ArgumentParser(description="amvision backend-worker launcher")
    parser.add_argument("--app-root", help="应用根目录；未传入时按 launcher 相对位置自动解析")
    parser.add_argument("--python-executable", help="用于启动 backend-worker 的 Python 解释器路径")
    parser.add_argument(
        "--worker-profile-file",
        help="worker profile manifest 路径；相对路径按应用根目录解析",
    )
    parser.add_argument(
        "--enabled-consumer-kind",
        action="append",
        default=None,
        help="显式指定要启用的 consumer kind；可重复传入",
    )
    parser.add_argument("--max-concurrent-tasks", type=int, help="覆盖 worker 最大并发数")
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        help="覆盖 worker 空闲轮询间隔秒数",
    )
    parser.add_argument(
        "--workspace-root-dir",
        help="覆盖 worker workspace.root_dir；未传入时按 profile_id 自动落到 data/worker/<profile_id>",
    )
    return parser


def _resolve_worker_profile(
    app_root: Path,
    worker_profile_file: str | None,
) -> dict[str, object] | None:
    """读取 worker profile manifest。"""

    if worker_profile_file is None or not worker_profile_file.strip():
        return None
    return load_json_file(app_root, worker_profile_file.strip())


def main(argv: list[str] | None = None) -> int:
    """执行 backend-worker launcher 主入口。"""

    parser = build_argument_parser()
    args = parser.parse_args(argv)
    app_root = resolve_app_root(script_file=Path(__file__), explicit_app_root=args.app_root)
    worker_profile = _resolve_worker_profile(app_root, args.worker_profile_file)

    enabled_consumer_kinds: list[str] = []
    if args.enabled_consumer_kind is not None:
        enabled_consumer_kinds.extend(args.enabled_consumer_kind)
    elif worker_profile is not None:
        worker_profile_consumer_kinds = worker_profile.get("enabled_consumer_kinds")
        if isinstance(worker_profile_consumer_kinds, list):
            enabled_consumer_kinds.extend(str(item) for item in worker_profile_consumer_kinds)

    extra_env: dict[str, str] = {}
    if enabled_consumer_kinds:
        extra_env["AMVISION_WORKER_TASK_MANAGER__ENABLED_CONSUMER_KINDS"] = json_env_value(
            enabled_consumer_kinds
        )

    max_concurrent_tasks = args.max_concurrent_tasks
    if max_concurrent_tasks is None and worker_profile is not None:
        raw_max_concurrent_tasks = worker_profile.get("max_concurrent_tasks")
        if isinstance(raw_max_concurrent_tasks, int):
            max_concurrent_tasks = raw_max_concurrent_tasks
    if max_concurrent_tasks is not None:
        extra_env["AMVISION_WORKER_TASK_MANAGER__MAX_CONCURRENT_TASKS"] = str(max_concurrent_tasks)

    poll_interval_seconds = args.poll_interval_seconds
    if poll_interval_seconds is None and worker_profile is not None:
        raw_poll_interval_seconds = worker_profile.get("poll_interval_seconds")
        if isinstance(raw_poll_interval_seconds, int | float):
            poll_interval_seconds = float(raw_poll_interval_seconds)
    if poll_interval_seconds is not None:
        extra_env["AMVISION_WORKER_TASK_MANAGER__POLL_INTERVAL_SECONDS"] = str(
            poll_interval_seconds
        )

    if worker_profile is not None:
        profile_id = str(worker_profile.get("profile_id", "worker"))
        display_name = str(worker_profile.get("display_name", f"amvision worker {profile_id}"))
        extra_env["AMVISION_WORKER_APP__APP_NAME"] = display_name
        workspace_root_dir = args.workspace_root_dir or f"./data/worker/{profile_id}"
        extra_env["AMVISION_WORKER_WORKSPACE__ROOT_DIR"] = workspace_root_dir
    elif args.workspace_root_dir is not None:
        extra_env["AMVISION_WORKER_WORKSPACE__ROOT_DIR"] = args.workspace_root_dir

    return run_python_module(
        app_root=app_root,
        module_name="backend.workers.main",
        module_args=(),
        python_executable=args.python_executable,
        extra_env=extra_env,
    )


if __name__ == "__main__":
    raise SystemExit(main())