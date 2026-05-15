"""backend-maintenance 进程入口。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.maintenance.bootstrap import BackendMaintenanceBootstrap, BackendMaintenanceRuntime
from backend.maintenance.release_assembly import ReleaseAssemblyRequest, assemble_release
from backend.contracts.workflows.resource_semantics import (
    WORKFLOW_PREVIEW_RUN_CLEANUP_COMMAND,
    WORKFLOW_PREVIEW_RUN_STORAGE_ROOT,
    WORKFLOW_RUNTIME_STORAGE_CLEANUP_COMMAND,
    WORKFLOW_RUNTIME_STORAGE_DEFAULT_RETENTION_HOURS,
    WORKFLOW_RUN_STORAGE_ROOT,
    WORKFLOW_RUN_TERMINAL_STATES,
    WORKFLOW_RUNTIME_STORAGE_ROOT,
    build_workflow_preview_run_storage_dir,
)
from backend.service.domain.workflows.workflow_runtime_records import WorkflowRun
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.infrastructure.object_store.object_key_layout import RUNTIME_INPUTS_STORAGE_ROOT
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
            WORKFLOW_PREVIEW_RUN_CLEANUP_COMMAND,
            WORKFLOW_RUNTIME_STORAGE_CLEANUP_COMMAND,
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
    parser.add_argument(
        "--now-iso",
        default=None,
        help="cleanup 命令使用的当前时间覆盖值，格式为 ISO8601",
    )
    parser.add_argument(
        "--retention-hours",
        type=int,
        default=WORKFLOW_RUNTIME_STORAGE_DEFAULT_RETENTION_HOURS,
        help="cleanup-runtime-storage 使用的保留小时数",
    )
    return parser


def run_command(
    command: str,
    runtime: BackendMaintenanceRuntime,
    *,
    profile_id: str | None = None,
    release_root: str = "release",
    force: bool = False,
    now_iso: str | None = None,
    retention_hours: int = WORKFLOW_RUNTIME_STORAGE_DEFAULT_RETENTION_HOURS,
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
            "bundled_python_mode": result.bundled_python_mode,
            "generated_root_launchers": [str(path) for path in result.generated_root_launchers],
            "worker_profiles": list(result.worker_profile_ids),
            "generated_worker_launchers": [str(path) for path in result.generated_worker_launchers],
            "placeholder_dirs": [str(path) for path in result.placeholder_dirs],
        }
    if command == WORKFLOW_PREVIEW_RUN_CLEANUP_COMMAND:
        return cleanup_expired_preview_runs(
            backend_service_settings=backend_service_settings,
            now_iso=now_iso,
        )
    if command == WORKFLOW_RUNTIME_STORAGE_CLEANUP_COMMAND:
        return cleanup_runtime_storage(
            backend_service_settings=backend_service_settings,
            now_iso=now_iso,
            retention_hours=retention_hours,
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
        snapshot_dir = build_workflow_preview_run_storage_dir(preview_run_id)
        dataset_storage.delete_tree(snapshot_dir)
        deleted_snapshot_dirs.append(snapshot_dir)

    return {
        "command": WORKFLOW_PREVIEW_RUN_CLEANUP_COMMAND,
        "cutoff_time": cutoff_time,
        "expired_count": len(deleted_preview_run_ids),
        "deleted_preview_run_ids": deleted_preview_run_ids,
        "deleted_snapshot_dirs": deleted_snapshot_dirs,
    }


def cleanup_runtime_storage(
    *,
    backend_service_settings: BackendServiceSettings | None = None,
    now_iso: str | None = None,
    retention_hours: int = WORKFLOW_RUNTIME_STORAGE_DEFAULT_RETENTION_HOURS,
) -> dict[str, object]:
    """按统一 retention 窗口清理短期 runtime ObjectStore 数据。

    参数：
    - backend_service_settings：可选服务配置；为空时读取默认配置。
    - now_iso：可选当前时间覆盖值，格式为 ISO8601。
    - retention_hours：短期运行时数据的保留小时数。

    返回：
    - dict[str, object]：runtime cleanup 结果摘要。
    """

    if retention_hours <= 0:
        raise ValueError("retention_hours 必须大于 0")

    preview_cleanup_payload = cleanup_expired_preview_runs(
        backend_service_settings=backend_service_settings,
        now_iso=now_iso,
    )
    service_settings = backend_service_settings or get_backend_service_settings()
    cutoff_time = _resolve_retention_cutoff_time(now_iso, retention_hours=retention_hours)
    cutoff_datetime = _parse_iso_datetime_text(cutoff_time)
    session_factory = SessionFactory(service_settings.to_database_settings())
    dataset_storage = LocalDatasetStorage(service_settings.to_dataset_storage_settings())
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        deleted_runtime_input_entries = _cleanup_runtime_input_entries(
            dataset_storage=dataset_storage,
            cutoff_datetime=cutoff_datetime,
        )
        deleted_workflow_run_dirs = _cleanup_workflow_run_dirs(
            unit_of_work=unit_of_work,
            dataset_storage=dataset_storage,
            cutoff_datetime=cutoff_datetime,
        )
        deleted_orphan_preview_dirs = _cleanup_orphan_preview_run_dirs(
            unit_of_work=unit_of_work,
            dataset_storage=dataset_storage,
            cutoff_datetime=cutoff_datetime,
        )
        deleted_orphan_app_runtime_dirs = _cleanup_orphan_app_runtime_dirs(
            unit_of_work=unit_of_work,
            dataset_storage=dataset_storage,
            cutoff_datetime=cutoff_datetime,
        )
    finally:
        unit_of_work.close()
        session_factory.engine.dispose()

    deleted_count = (
        len(preview_cleanup_payload["deleted_snapshot_dirs"])
        + len(deleted_runtime_input_entries)
        + len(deleted_workflow_run_dirs)
        + len(deleted_orphan_preview_dirs)
        + len(deleted_orphan_app_runtime_dirs)
    )
    return {
        "command": WORKFLOW_RUNTIME_STORAGE_CLEANUP_COMMAND,
        "cutoff_time": cutoff_time,
        "retention_hours": retention_hours,
        "preview_cleanup": preview_cleanup_payload,
        "deleted_runtime_input_entries": deleted_runtime_input_entries,
        "deleted_workflow_run_dirs": deleted_workflow_run_dirs,
        "deleted_orphan_preview_dirs": deleted_orphan_preview_dirs,
        "deleted_orphan_app_runtime_dirs": deleted_orphan_app_runtime_dirs,
        "deleted_count": deleted_count,
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
        now_iso=args.now_iso,
        retention_hours=args.retention_hours,
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


def _resolve_retention_cutoff_time(now_iso: str | None, *, retention_hours: int) -> str:
    """把当前时间和保留窗口转换为 cleanup 截止时间。"""

    base_time = _parse_iso_datetime_text(_normalize_cutoff_time(now_iso))
    cutoff_time = base_time - timedelta(hours=retention_hours)
    return cutoff_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _cleanup_runtime_input_entries(
    *,
    dataset_storage: LocalDatasetStorage,
    cutoff_datetime: datetime,
) -> list[str]:
    """清理超过截止时间的 runtime/inputs 请求目录。"""

    runtime_inputs_root = dataset_storage.resolve(RUNTIME_INPUTS_STORAGE_ROOT)
    if not runtime_inputs_root.is_dir():
        return []

    deleted_entries: list[str] = []
    for consumer_path in sorted(runtime_inputs_root.iterdir(), key=lambda item: item.name):
        if not consumer_path.is_dir():
            continue
        for request_path in sorted(consumer_path.iterdir(), key=lambda item: item.name):
            if not _is_path_older_than_cutoff(request_path, cutoff_datetime=cutoff_datetime):
                continue
            relative_path = _to_relative_storage_path(
                dataset_storage=dataset_storage,
                path=request_path,
            )
            dataset_storage.delete_tree(relative_path)
            deleted_entries.append(relative_path)
    return deleted_entries


def _cleanup_workflow_run_dirs(
    *,
    unit_of_work: SqlAlchemyUnitOfWork,
    dataset_storage: LocalDatasetStorage,
    cutoff_datetime: datetime,
) -> list[str]:
    """清理过旧或失联的 WorkflowRun 运行目录。"""

    workflow_runtime_root = dataset_storage.resolve(WORKFLOW_RUN_STORAGE_ROOT)
    if not workflow_runtime_root.is_dir():
        return []

    deleted_dirs: list[str] = []
    for child_path in sorted(workflow_runtime_root.iterdir(), key=lambda item: item.name):
        if not child_path.is_dir():
            continue
        if child_path.name in {
            Path(WORKFLOW_PREVIEW_RUN_STORAGE_ROOT).name,
            Path(WORKFLOW_RUNTIME_STORAGE_ROOT).name,
        }:
            continue
        workflow_run = unit_of_work.workflow_runtime.get_workflow_run(child_path.name)
        if workflow_run is None:
            if not _is_path_older_than_cutoff(child_path, cutoff_datetime=cutoff_datetime):
                continue
        elif not _is_workflow_run_storage_expired(
            workflow_run,
            cutoff_datetime=cutoff_datetime,
        ):
            continue
        relative_path = _to_relative_storage_path(dataset_storage=dataset_storage, path=child_path)
        dataset_storage.delete_tree(relative_path)
        deleted_dirs.append(relative_path)
    return deleted_dirs


def _cleanup_orphan_preview_run_dirs(
    *,
    unit_of_work: SqlAlchemyUnitOfWork,
    dataset_storage: LocalDatasetStorage,
    cutoff_datetime: datetime,
) -> list[str]:
    """清理失去 preview run 记录的遗留 snapshot 目录。"""

    preview_root = dataset_storage.resolve(WORKFLOW_PREVIEW_RUN_STORAGE_ROOT)
    if not preview_root.is_dir():
        return []

    deleted_dirs: list[str] = []
    for child_path in sorted(preview_root.iterdir(), key=lambda item: item.name):
        if not child_path.is_dir():
            continue
        if unit_of_work.workflow_runtime.get_preview_run(child_path.name) is not None:
            continue
        if not _is_path_older_than_cutoff(child_path, cutoff_datetime=cutoff_datetime):
            continue
        relative_path = _to_relative_storage_path(dataset_storage=dataset_storage, path=child_path)
        dataset_storage.delete_tree(relative_path)
        deleted_dirs.append(relative_path)
    return deleted_dirs


def _cleanup_orphan_app_runtime_dirs(
    *,
    unit_of_work: SqlAlchemyUnitOfWork,
    dataset_storage: LocalDatasetStorage,
    cutoff_datetime: datetime,
) -> list[str]:
    """清理失去 WorkflowAppRuntime 记录的遗留 snapshot 目录。"""

    app_runtime_root = dataset_storage.resolve(WORKFLOW_RUNTIME_STORAGE_ROOT)
    if not app_runtime_root.is_dir():
        return []

    deleted_dirs: list[str] = []
    for child_path in sorted(app_runtime_root.iterdir(), key=lambda item: item.name):
        if not child_path.is_dir():
            continue
        if unit_of_work.workflow_runtime.get_workflow_app_runtime(child_path.name) is not None:
            continue
        if not _is_path_older_than_cutoff(child_path, cutoff_datetime=cutoff_datetime):
            continue
        relative_path = _to_relative_storage_path(dataset_storage=dataset_storage, path=child_path)
        dataset_storage.delete_tree(relative_path)
        deleted_dirs.append(relative_path)
    return deleted_dirs


def _is_workflow_run_storage_expired(
    workflow_run: WorkflowRun,
    *,
    cutoff_datetime: datetime,
) -> bool:
    """判断一条 WorkflowRun 的运行目录是否已经进入清理窗口。"""

    if workflow_run.state not in WORKFLOW_RUN_TERMINAL_STATES:
        return False
    anchor_text = workflow_run.finished_at or workflow_run.created_at
    anchor_datetime = _parse_optional_iso_datetime_text(anchor_text)
    if anchor_datetime is None:
        return False
    return anchor_datetime <= cutoff_datetime


def _is_path_older_than_cutoff(path: Path, *, cutoff_datetime: datetime) -> bool:
    """判断一个文件系统路径是否早于 cleanup 截止时间。"""

    try:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except FileNotFoundError:
        return False
    return modified_at <= cutoff_datetime


def _to_relative_storage_path(*, dataset_storage: LocalDatasetStorage, path: Path) -> str:
    """把文件系统路径转回 ObjectStore 相对路径。"""

    return path.relative_to(dataset_storage.root_dir).as_posix()


def _parse_iso_datetime_text(value: str) -> datetime:
    """把 ISO8601 文本解析为带时区的 UTC 时间。"""

    normalized_value = value.strip()
    if normalized_value.endswith("Z"):
        normalized_value = f"{normalized_value[:-1]}+00:00"
    parsed_value = datetime.fromisoformat(normalized_value)
    if parsed_value.tzinfo is None:
        parsed_value = parsed_value.replace(tzinfo=timezone.utc)
    return parsed_value.astimezone(timezone.utc)


def _parse_optional_iso_datetime_text(value: str | None) -> datetime | None:
    """把可选 ISO8601 文本解析为 UTC 时间。"""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _parse_iso_datetime_text(value)
    except ValueError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())