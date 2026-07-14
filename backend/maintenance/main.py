"""backend-maintenance 进程入口。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.maintenance.bootstrap import BackendMaintenanceBootstrap, BackendMaintenanceRuntime
from backend.maintenance.extension_pretrained_manifests import (
    sync_extension_pretrained_manifests,
)
from backend.maintenance.release_assembly import ReleaseAssemblyRequest, assemble_release
from backend.maintenance.pycache_maintenance import (
    REBUILD_PYCACHE_COMMAND,
    build_pycache_request,
    rebuild_pycache,
)
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
from backend.service.infrastructure.object_store.object_key_layout import RUNTIME_INPUTS_STORAGE_ROOT


def _load_release_manifest_artifacts_for_layout(app_root: Path) -> dict[str, object]:
    """读取发布目录中的 release manifest artifacts，用于布局校验分支判断。

    参数：
    - app_root：当前 maintenance 工作目录。

    返回：
    - dict[str, object]：当前发布 profile 的 artifacts 字典；找不到或格式异常时返回空字典。
    """

    release_profile_dir = app_root / "manifests" / "release-profiles"
    if not release_profile_dir.is_dir():
        return {}
    preferred_manifest_path = release_profile_dir / "full.json"
    manifest_paths = sorted(release_profile_dir.glob("*.json"))
    manifest_path = (
        preferred_manifest_path
        if preferred_manifest_path.is_file()
        else (manifest_paths[0] if len(manifest_paths) == 1 else None)
    )
    if manifest_path is None:
        return {}
    try:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    artifacts = manifest_payload.get("artifacts")
    return artifacts if isinstance(artifacts, dict) else {}


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
            REBUILD_PYCACHE_COMMAND,
            "sync-extension-pretrained-manifests",
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
        "--bundled-python-source-dir",
        default=None,
        help="仅在需要重建 release/python 时显式指定 bundled Python 来源目录",
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
    parser.add_argument(
        "--pycache-root",
        action="append",
        default=None,
        help=(
            "rebuild-pycache 要处理的仓库内源码目录，可重复传入；"
            "不传时默认处理 backend、custom_nodes、tests、scripts"
        ),
    )
    parser.add_argument(
        "--python-package",
        action="append",
        default=None,
        help="rebuild-pycache 要额外处理的当前解释器依赖包名，例如 sqlalchemy；可重复传入",
    )
    parser.add_argument(
        "--clean-only",
        action="store_true",
        help="rebuild-pycache 只删除 __pycache__，不重新编译",
    )
    parser.add_argument(
        "--compile-only",
        action="store_true",
        help="rebuild-pycache 只重新编译，不删除已有 __pycache__",
    )
    return parser


def run_command(
    command: str,
    runtime: BackendMaintenanceRuntime,
    *,
    profile_id: str | None = None,
    release_root: str = "release",
    force: bool = False,
    bundled_python_source_dir: str | None = None,
    now_iso: str | None = None,
    retention_hours: int = WORKFLOW_RUNTIME_STORAGE_DEFAULT_RETENTION_HOURS,
    pycache_roots: list[str] | None = None,
    python_packages: list[str] | None = None,
    clean_only: bool = False,
    compile_only: bool = False,
    backend_service_settings: object | None = None,
) -> dict[str, object]:
    """执行指定 maintenance 命令。

    参数：
    - command：要执行的 maintenance 命令。
    - runtime：当前 maintenance 运行时资源。
    - profile_id：assemble-release 使用的 profile id。
    - release_root：assemble-release 输出根目录。
    - force：assemble-release 时是否允许覆盖已存在目录。
    - bundled_python_source_dir：可选的 bundled Python 来源目录，仅在需要重建时使用。
    - pycache_roots：rebuild-pycache 要处理的源码目录。
    - python_packages：rebuild-pycache 要处理的当前解释器依赖包名。
    - clean_only：rebuild-pycache 是否只删除缓存。
    - compile_only：rebuild-pycache 是否只编译缓存。

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
        layout_kind = "release" if (app_root / "app" / "backend").is_dir() else "source"
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
        if layout_kind == "release":
            release_artifacts = _load_release_manifest_artifacts_for_layout(app_root)
            expected_paths.update(
                {
                    "app_backend": (app_root / "app" / "backend",),
                    "app_requirements": (app_root / "app" / "requirements.txt",),
                    "custom_nodes": (app_root / "custom_nodes",),
                    "ffmpeg_tools": (
                        app_root / "tools" / "ffmpeg",
                    ),
                    "frontend_index": (app_root / "frontend" / "index.html",),
                    "frontend_runtime_config": (
                        app_root / "frontend" / "runtime-config.json",
                    ),
                    "python_executable": (
                        app_root / "python" / "python.exe",
                        app_root / "python" / "bin" / "python3",
                        app_root / "python" / "bin" / "python",
                    ),
                }
            )
            if bool(release_artifacts.get("include_tensorrt_runtime", False)):
                expected_paths["tensorrt_tools"] = (app_root / "tools" / "tensorrt",)
            if bool(release_artifacts.get("include_cudnn_runtime", False)):
                expected_paths["cudnn_tools"] = (app_root / "tools" / "cudnn",)
        return {
            "command": command,
            "app_root": str(app_root),
            "layout_kind": layout_kind,
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
                bundled_python_source_dir=(
                    Path(bundled_python_source_dir)
                    if bundled_python_source_dir
                    else (
                        Path(runtime.settings.release.bundled_python.source_dir)
                        if runtime.settings.release.bundled_python.source_dir
                        else None
                    )
                ),
                frontend_dist_dir=Path(runtime.settings.release.frontend.dist_dir),
                frontend_runtime_config_source_file=(
                    Path(runtime.settings.release.frontend.runtime_config_source_file)
                    if runtime.settings.release.frontend.runtime_config_source_file
                    else None
                ),
                frontend_runtime_config_template_file=Path(
                    runtime.settings.release.frontend.runtime_config_template_file
                ),
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
    if command == REBUILD_PYCACHE_COMMAND:
        return rebuild_pycache(
            build_pycache_request(
                project_source_roots=(
                    tuple(pycache_roots)
                    if pycache_roots is not None and len(pycache_roots) > 0
                    else None
                ),
                python_package_names=tuple(python_packages or ()),
                clean_only=clean_only,
                compile_only=compile_only,
            )
        )
    if command == "sync-extension-pretrained-manifests":
        result = sync_extension_pretrained_manifests()
        return {
            "command": command,
            "moved_legacy_yoloe_root": result.moved_legacy_yoloe_root,
            "written_manifest_paths": [str(path) for path in result.written_manifest_paths],
            "warnings": list(result.warnings),
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
    backend_service_settings: object | None = None,
    now_iso: str | None = None,
) -> dict[str, object]:
    """按 retention_until 清理已过期的 preview run 记录和 snapshot 目录。"""

    from backend.service.application.workflows.preview_run_cleanup import (
        finalize_staged_preview_run_storage,
        restore_staged_preview_run_storage,
        stage_preview_run_storage_for_cleanup,
    )
    from backend.service.infrastructure.db.session import SessionFactory
    from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
    from backend.service.infrastructure.object_store.local_dataset_storage import (
        LocalDatasetStorage,
    )
    from backend.service.settings import get_backend_service_settings

    service_settings = backend_service_settings or get_backend_service_settings()
    cutoff_time = _normalize_cutoff_time(now_iso)
    session_factory = SessionFactory(service_settings.to_database_settings())
    dataset_storage = LocalDatasetStorage(service_settings.to_dataset_storage_settings())
    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    staged_snapshot_dirs: list[tuple[str, str | None]] = []
    try:
        expired_preview_runs = unit_of_work.workflow_runtime.list_expired_preview_runs(
            cutoff_time
        )
        deleted_preview_run_ids = [
            item.preview_run_id for item in expired_preview_runs
        ]
        for preview_run in expired_preview_runs:
            staged_snapshot_dirs.append(
                (
                    preview_run.preview_run_id,
                    stage_preview_run_storage_for_cleanup(
                        dataset_storage=dataset_storage,
                        preview_run_id=preview_run.preview_run_id,
                    ),
                )
            )
        for preview_run in expired_preview_runs:
            unit_of_work.workflow_runtime.delete_preview_run(preview_run.preview_run_id)
        try:
            unit_of_work.commit()
        except Exception:
            for preview_run_id, staging_dir in staged_snapshot_dirs:
                restore_staged_preview_run_storage(
                    dataset_storage=dataset_storage,
                    preview_run_id=preview_run_id,
                    staging_dir=staging_dir,
                )
            raise
    finally:
        unit_of_work.close()
        session_factory.engine.dispose()

    deleted_snapshot_dirs: list[str] = []
    pending_staging_dirs: list[str] = []
    for preview_run_id, staging_dir in staged_snapshot_dirs:
        snapshot_dir = build_workflow_preview_run_storage_dir(preview_run_id)
        deleted_snapshot_dirs.append(snapshot_dir)
        pending_staging_dir = finalize_staged_preview_run_storage(
            dataset_storage=dataset_storage,
            staging_dir=staging_dir,
        )
        if pending_staging_dir is not None:
            pending_staging_dirs.append(pending_staging_dir)

    return {
        "command": WORKFLOW_PREVIEW_RUN_CLEANUP_COMMAND,
        "cutoff_time": cutoff_time,
        "expired_count": len(deleted_preview_run_ids),
        "deleted_preview_run_ids": deleted_preview_run_ids,
        "deleted_snapshot_dirs": deleted_snapshot_dirs,
        "pending_staging_dirs": pending_staging_dirs,
    }


def cleanup_runtime_storage(
    *,
    backend_service_settings: object | None = None,
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

    from backend.service.infrastructure.db.session import SessionFactory
    from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
    from backend.service.infrastructure.object_store.local_dataset_storage import (
        LocalDatasetStorage,
    )
    from backend.service.settings import get_backend_service_settings

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
        bundled_python_source_dir=args.bundled_python_source_dir,
        now_iso=args.now_iso,
        retention_hours=args.retention_hours,
        pycache_roots=args.pycache_root,
        python_packages=args.python_package,
        clean_only=args.clean_only,
        compile_only=args.compile_only,
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
