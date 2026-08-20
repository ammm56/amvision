"""backend-worker Python launcher。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


LAUNCHERS_ROOT = Path(__file__).resolve().parents[1]
if str(LAUNCHERS_ROOT) not in sys.path:
    sys.path.insert(0, str(LAUNCHERS_ROOT))

from common import (  # noqa: E402
    WINDOWS_SYSTEM_CONFIGURATION_REQUIRED_EXIT_CODE,
    ensure_windows_long_paths_enabled,
    resolve_app_root,
    resolve_code_root,
    run_python_module,
)


def build_argument_parser() -> argparse.ArgumentParser:
    """构造 backend-worker launcher 参数解析器。"""

    parser = argparse.ArgumentParser(description="amvision backend-worker launcher")
    parser.add_argument(
        "--app-root", help="应用根目录；未传入时按 launcher 相对位置自动解析"
    )
    parser.add_argument(
        "--python-executable", help="用于启动 backend-worker 的 Python 解释器路径"
    )
    parser.add_argument(
        "--worker-profile-file",
        required=True,
        help="worker profile manifest 路径；相对路径按应用根目录解析",
    )
    parser.add_argument("--topology-id", required=True, help="当前 Worker Topology id")
    parser.add_argument(
        "--topology-generation",
        required=True,
        type=int,
        help="当前 Worker Topology generation",
    )
    parser.add_argument(
        "--topology-epoch-id", required=True, help="当前 Worker Topology epoch id"
    )
    parser.add_argument(
        "--worker-instance-id", required=True, help="当前 Worker 进程实例 id"
    )
    parser.add_argument(
        "--worker-runtime-root",
        required=True,
        help="Worker Topology 运行态根目录",
    )
    return parser


def _resolve_required_path(app_root: Path, value: str) -> Path:
    """解析 launcher 必填路径。"""

    path = Path(value)
    return path.resolve() if path.is_absolute() else (app_root / path).resolve()


def main(argv: list[str] | None = None) -> int:
    """执行 backend-worker launcher 主入口。"""

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
    code_root = resolve_code_root(app_root)
    if str(code_root) not in sys.path:
        sys.path.insert(0, str(code_root))
    from backend.workers.contracts import (  # noqa: PLC0415
        WORKER_INSTANCE_ID_ENV,
        WORKER_PROFILE_FILE_ENV,
        WORKER_RUNTIME_ROOT_ENV,
        WORKER_TOPOLOGY_EPOCH_ID_ENV,
        WORKER_TOPOLOGY_GENERATION_ENV,
        WORKER_TOPOLOGY_ID_ENV,
        load_worker_profile_manifest,
    )

    profile_path = _resolve_required_path(app_root, args.worker_profile_file)
    runtime_root = _resolve_required_path(app_root, args.worker_runtime_root)
    profile = load_worker_profile_manifest(profile_path)
    extra_env = {
        WORKER_PROFILE_FILE_ENV: str(profile_path),
        WORKER_RUNTIME_ROOT_ENV: str(runtime_root),
        WORKER_TOPOLOGY_ID_ENV: args.topology_id,
        WORKER_TOPOLOGY_GENERATION_ENV: str(args.topology_generation),
        WORKER_TOPOLOGY_EPOCH_ID_ENV: args.topology_epoch_id,
        WORKER_INSTANCE_ID_ENV: args.worker_instance_id,
        "AMVISION_WORKER_APP__APP_NAME": profile.display_name,
        "AMVISION_WORKER_WORKSPACE__ROOT_DIR": f"./data/worker/{profile.profile_id}",
    }

    return run_python_module(
        app_root=app_root,
        module_name="backend.workers.main",
        module_args=(),
        python_executable=args.python_executable,
        extra_env=extra_env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
