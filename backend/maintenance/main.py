"""backend-maintenance 进程入口。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.maintenance.bootstrap import BackendMaintenanceBootstrap, BackendMaintenanceRuntime
from backend.maintenance.release_assembly import ReleaseAssemblyRequest, assemble_release
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.settings import BackendServiceSettings, get_backend_service_settings


def build_argument_parser() -> argparse.ArgumentParser:
    """构造 backend-maintenance 命令行参数解析器。

    返回：
    - argparse.ArgumentParser：maintenance 命令行参数解析器。
    """

    parser = argparse.ArgumentParser(description="amvision backend-maintenance")
    parser.add_argument(
        "command",
        choices=(
            "version",
            "show-config",
            "validate-layout",
            "assemble-release",
            "cleanup-preview-runs",
        ),
        help="要执行的 maintenance 命令",
    )
    parser.add_argument(
        "--output",
        choices=("json", "text"),
        default="json",
        help="命令结果输出格式",
    )
    parser.add_argument(
        "--profile-id",
        default="full",
        help="assemble-release 使用的 release profile id",
    )
    parser.add_argument(
        "--release-root",
        default="release",
        help="assemble-release 输出根目录",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="assemble-release 时允许覆盖现有目录",
    )
    return parser


def run_command(
    command: str,
    runtime: BackendMaintenanceRuntime,
    *,
    profile_id: str | None = None,
    release_root: str = "release",
    force: bool = False,
    backend_service_settings: BackendServiceSettings | None = None,
) -> dict[str, object]:
    """执行指定 maintenance 命令。

    参数：
    - command：要执行的 maintenance 命令。
    - runtime：当前 maintenance 运行时资源。
    - profile_id：assemble-release 使用的 profile id。
    - release_root：assemble-release 输出根目录。
    - force：assemble-release 时是否允许覆盖已存在目录。

    返回：
    - dict[str, object]：命令执行结果。
    """

    if command == "version":
        return {
            "command": command,
            "app_name": runtime.settings.app.app_name,
            "app_version": runtime.settings.app.app_version,
            "workspace_dir": str(runtime.workspace_dir),
        }
    if command == "show-config":
        return {
            "command": command,
            "settings": runtime.settings.model_dump(mode="json"),
        }
    if command == "validate-layout":
        app_root = Path.cwd()
        expected_paths = {
            "config": (app_root / "config",),
            "data": (app_root / "data",),
            "launchers": (
                app_root / "launchers",
                app_root / "runtimes" / "launchers",
            ),
            "release_profiles": (
                app_root / "manifests" / "release-profiles",
                app_root / "runtimes" / "manifests" / "release-profiles",
            ),
            "worker_profiles": (
                app_root / "manifests" / "worker-profiles",
                app_root / "runtimes" / "manifests" / "worker-profiles",
            ),
        }
        return {
            "command": command,
            "app_root": str(app_root),
            "workspace_dir": str(runtime.workspace_dir),
            "paths": {
                name: {
                    "path": str(next((path for path in paths if path.exists()), paths[0])),
                    "exists": any(path.exists() for path in paths),
                    "candidates": [str(path) for path in paths],
                }
                for name, paths in expected_paths.items()
            },
        }
    if command == "assemble-release":
        resolved_profile_id = "full" if profile_id is None or not profile_id.strip() else profile_id.strip()
        result = assemble_release(
            ReleaseAssemblyRequest(
                profile_id=resolved_profile_id,
                output_root=Path(release_root),
                overwrite=force,
            )
        )
        return {
            "command": command,
            "profile_id": result.profile_id,
            "release_dir": str(result.release_dir),
            "release_manifest": str(result.release_manifest_path),
            "requirements_file": str(result.requirements_path),
            "python_dir": str(result.bundled_python_dir),
            "generated_root_launchers": [str(path) for path in result.generated_root_launchers],
            "worker_profiles": list(result.worker_profile_ids),
            "generated_worker_launchers": [str(path) for path in result.generated_worker_launchers],
            "placeholder_dirs": [str(path) for path in result.placeholder_dirs],
        }
    if command == "cleanup-preview-runs":
        return cleanup_expired_preview_runs(
            backend_service_settings=backend_service_settings,
        )
    raise ValueError(f"unsupported maintenance command: {command}")


def cleanup_expired_preview_runs(
    *,
    backend_service_settings: BackendServiceSettings | None = None,
    now_iso: str | None = None,
) -> dict[str, object]:
    """按 retention_until 清理已过期的 preview run 记录和 snapshot 目录。"""

    service_settings = backend_service_settings or get_backend_service_settings()
    cutoff_time = _normalize_cutoff_time(now_iso)
    session_factory = SessionFactory(service_settings.to_database_settings())
    dataset_storage = LocalDatasetStorage(service_settings.to_dataset_storage_settings())
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        expired_preview_runs = unit_of_work.workflow_runtime.list_expired_preview_runs(
            cutoff_time
        )
        deleted_preview_run_ids = [
            item.preview_run_id for item in expired_preview_runs
        ]
        for preview_run in expired_preview_runs:
            unit_of_work.workflow_runtime.delete_preview_run(preview_run.preview_run_id)
        unit_of_work.commit()
    finally:
        unit_of_work.close()
        session_factory.engine.dispose()

    deleted_snapshot_dirs: list[str] = []
    for preview_run_id in deleted_preview_run_ids:
        snapshot_dir = f"workflows/runtime/preview-runs/{preview_run_id}"
        dataset_storage.delete_tree(snapshot_dir)
        deleted_snapshot_dirs.append(snapshot_dir)

    return {
        "command": "cleanup-preview-runs",
        "cutoff_time": cutoff_time,
        "expired_count": len(deleted_preview_run_ids),
        "deleted_preview_run_ids": deleted_preview_run_ids,
        "deleted_snapshot_dirs": deleted_snapshot_dirs,
    }


def format_text_output(payload: dict[str, object]) -> str:
    """把 maintenance 命令结果格式化为文本输出。

    参数：
    - payload：命令执行结果。

    返回：
    - str：适合终端输出的文本结果。
    """

    lines: list[str] = []
    for key, value in payload.items():
        if isinstance(value, dict):
            lines.append(f"{key}:")
            for nested_key, nested_value in value.items():
                lines.append(f"  {nested_key}: {nested_value}")
            continue
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """执行 backend-maintenance 主入口。

    参数：
    - argv：可选命令行参数列表；未传入时读取进程参数。

    返回：
    - int：进程退出码。
    """

    parser = build_argument_parser()
    args = parser.parse_args(argv)
    bootstrap = BackendMaintenanceBootstrap()
    runtime = bootstrap.build_runtime(bootstrap.load_settings())
    bootstrap.initialize(runtime)
    payload = run_command(
        args.command,
        runtime,
        profile_id=args.profile_id,
        release_root=args.release_root,
        force=args.force,
    )
    if args.output == "text":
        print(format_text_output(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _normalize_cutoff_time(now_iso: str | None) -> str:
    """规范化 preview run 清理使用的截止时间。"""

    if isinstance(now_iso, str) and now_iso.strip():
        return now_iso.strip()
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())