"""开发阶段 Workflow 数据和文件的受控全量重置。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from uuid import uuid4

from sqlalchemy import delete, func, select

from backend.contracts.workflows.resource_semantics import (
    WORKFLOW_PREVIEW_RUN_TERMINAL_STATES,
    WORKFLOW_RUN_TERMINAL_STATES,
)
from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.workflow_runtime_orm import (
    WorkflowApplicationLifecycleRecord,
    WorkflowAppRuntimeRecord,
    WorkflowAppVersionRecord,
    WorkflowExecutionPolicyRecord,
    WorkflowPreviewRunRecord,
    WorkflowRunRecord,
    WorkflowRuntimeRevisionRecord,
)
from backend.service.infrastructure.persistence.workflow_trigger_source_orm import (
    WorkflowTriggerSourceRecord,
)


DEVELOPMENT_WORKFLOW_RESET_COMMAND = "reset-development-workflow-state"
DEVELOPMENT_WORKFLOW_HISTORY_CLEAR_COMMAND = "clear-development-workflow-history"
_STOPPED_STATE = "stopped"


@dataclass(frozen=True)
class DevelopmentWorkflowResetRequest:
    """描述一次开发期 Workflow 全量重置请求。"""

    confirm: bool = False


@dataclass(frozen=True)
class DevelopmentWorkflowHistoryClearRequest:
    """描述一次开发期 Workflow 执行历史清理请求。"""

    confirm: bool = False


def clear_development_workflow_history(
    *,
    request: DevelopmentWorkflowHistoryClearRequest,
    backend_service_settings: object,
) -> dict[str, object]:
    """清除 Run、Preview 和执行文件，但保留正式 Workflow 资源。"""

    session_factory = SessionFactory(backend_service_settings.to_database_settings())
    dataset_storage = LocalDatasetStorage(
        backend_service_settings.to_dataset_storage_settings()
    )
    initialize_database_schema(session_factory)
    storage_paths = _resolve_history_storage_paths(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    preview = {
        "database_counts": _read_history_counts(session_factory=session_factory),
        "active_resources": _read_active_resource_counts(
            session_factory=session_factory
        ),
        "storage_paths": [str(path) for path in storage_paths if path.exists()],
    }
    if not request.confirm:
        session_factory.engine.dispose()
        return {
            "command": DEVELOPMENT_WORKFLOW_HISTORY_CLEAR_COMMAND,
            "confirmed": False,
            "preview": preview,
        }

    active_resources = preview["active_resources"]
    if isinstance(active_resources, dict) and any(active_resources.values()):
        session_factory.engine.dispose()
        raise RuntimeError(
            "Workflow 执行历史清理被拒绝：必须先停止全部 Runtime、Trigger 和调用；"
            f" active_resources={active_resources}"
        )

    staging_token = uuid4().hex
    staged_paths: list[tuple[Path, Path]] = []
    try:
        for source_path in storage_paths:
            if not source_path.exists():
                continue
            staging_path = source_path.with_name(
                f".{source_path.name}.workflow-history-clear-{staging_token}"
            )
            if staging_path.exists():
                raise RuntimeError(f"Workflow 历史暂存路径已存在: {staging_path}")
            source_path.rename(staging_path)
            staged_paths.append((source_path, staging_path))
        deleted_counts = _delete_execution_history(session_factory=session_factory)
    except Exception:
        for source_path, staging_path in reversed(staged_paths):
            if staging_path.exists() and not source_path.exists():
                staging_path.rename(source_path)
        session_factory.engine.dispose()
        raise

    pending_cleanup = _finalize_staged_paths(staged_paths)
    remaining_counts = _read_database_counts(session_factory=session_factory)
    session_factory.engine.dispose()
    return {
        "command": DEVELOPMENT_WORKFLOW_HISTORY_CLEAR_COMMAND,
        "confirmed": True,
        "deleted_counts": deleted_counts,
        "remaining_counts": remaining_counts,
        "deleted_storage_paths": [str(source) for source, _ in staged_paths],
        "pending_cleanup": pending_cleanup,
    }


def reset_development_workflow_state(
    *,
    request: DevelopmentWorkflowResetRequest,
    backend_service_settings: object,
) -> dict[str, object]:
    """清除全部 Workflow 持久化状态，同时保留其他业务模块数据。"""

    session_factory = SessionFactory(backend_service_settings.to_database_settings())
    dataset_storage = LocalDatasetStorage(
        backend_service_settings.to_dataset_storage_settings()
    )
    buffer_root = Path(backend_service_settings.local_memory.root_dir).resolve()
    initialize_database_schema(session_factory)
    preview = _build_reset_preview(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        buffer_root=buffer_root,
    )
    if not request.confirm:
        session_factory.engine.dispose()
        return {
            "command": DEVELOPMENT_WORKFLOW_RESET_COMMAND,
            "confirmed": False,
            "preview": preview,
        }

    active_resources = preview["active_resources"]
    if isinstance(active_resources, dict) and any(active_resources.values()):
        session_factory.engine.dispose()
        raise RuntimeError(
            "Workflow 重置被拒绝：必须先停止全部 Runtime、Trigger 和运行中的调用；"
            f" active_resources={active_resources}"
        )

    staging_token = uuid4().hex
    staged_paths: list[tuple[Path, Path]] = []
    try:
        for source_path in _resolve_reset_storage_paths(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            buffer_root=buffer_root,
        ):
            if not source_path.exists():
                continue
            staging_path = source_path.with_name(
                f".{source_path.name}.workflow-reset-{staging_token}"
            )
            if staging_path.exists():
                raise RuntimeError(f"Workflow 重置暂存路径已存在: {staging_path}")
            source_path.rename(staging_path)
            staged_paths.append((source_path, staging_path))

        deleted_counts = _delete_database_state(session_factory=session_factory)
    except Exception:
        for source_path, staging_path in reversed(staged_paths):
            if staging_path.exists() and not source_path.exists():
                staging_path.rename(source_path)
        session_factory.engine.dispose()
        raise

    pending_cleanup = _finalize_staged_paths(staged_paths)

    _recreate_workflow_roots(dataset_storage=dataset_storage)
    remaining_counts = _read_database_counts(session_factory=session_factory)
    session_factory.engine.dispose()
    return {
        "command": DEVELOPMENT_WORKFLOW_RESET_COMMAND,
        "confirmed": True,
        "deleted_counts": deleted_counts,
        "remaining_counts": remaining_counts,
        "deleted_storage_paths": [str(source) for source, _ in staged_paths],
        "pending_cleanup": pending_cleanup,
        "preserved": {
            "database": "当前实时数据库中的非 Workflow 数据",
            "dataset_storage": "数据集、模型、部署和非 Workflow Project 文件",
            "local_memory": "local-buffer、inference mailbox、training telemetry",
        },
    }


def _build_reset_preview(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    buffer_root: Path,
) -> dict[str, object]:
    """构建无副作用的 Workflow 重置预览。"""

    storage_paths = _resolve_reset_storage_paths(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        buffer_root=buffer_root,
    )
    return {
        "database_counts": _read_database_counts(session_factory=session_factory),
        "active_resources": _read_active_resource_counts(
            session_factory=session_factory
        ),
        "storage_paths": [str(path) for path in storage_paths if path.exists()],
    }


def _read_database_counts(*, session_factory: SessionFactory) -> dict[str, int]:
    """读取全部 Workflow ORM 表的记录数量。"""

    with session_factory.create_session() as session:
        return {
            "workflow_trigger_sources": _count_rows(
                session, WorkflowTriggerSourceRecord
            ),
            "workflow_runs": _count_rows(session, WorkflowRunRecord),
            "workflow_app_runtimes": _count_rows(session, WorkflowAppRuntimeRecord),
            "workflow_runtime_revisions": _count_rows(
                session, WorkflowRuntimeRevisionRecord
            ),
            "workflow_app_versions": _count_rows(
                session, WorkflowAppVersionRecord
            ),
            "workflow_application_lifecycles": _count_rows(
                session, WorkflowApplicationLifecycleRecord
            ),
            "workflow_preview_runs": _count_rows(session, WorkflowPreviewRunRecord),
            "workflow_execution_policies": _count_rows(
                session, WorkflowExecutionPolicyRecord
            ),
        }


def _read_active_resource_counts(
    *, session_factory: SessionFactory
) -> dict[str, int]:
    """读取会阻止重置的活动 Runtime、Trigger 和执行记录数量。"""

    with session_factory.create_session() as session:
        return {
            "workflow_app_runtimes": int(
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowAppRuntimeRecord)
                    .where(
                        (WorkflowAppRuntimeRecord.desired_state != _STOPPED_STATE)
                        | (WorkflowAppRuntimeRecord.observed_state != _STOPPED_STATE)
                    )
                )
                or 0
            ),
            "workflow_trigger_sources": int(
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowTriggerSourceRecord)
                    .where(
                        (WorkflowTriggerSourceRecord.enabled.is_(True))
                        | (WorkflowTriggerSourceRecord.desired_state != _STOPPED_STATE)
                        | (WorkflowTriggerSourceRecord.observed_state != _STOPPED_STATE)
                    )
                )
                or 0
            ),
            "workflow_runs": int(
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowRunRecord)
                    .where(WorkflowRunRecord.state.not_in(WORKFLOW_RUN_TERMINAL_STATES))
                )
                or 0
            ),
            "workflow_preview_runs": int(
                session.scalar(
                    select(func.count())
                    .select_from(WorkflowPreviewRunRecord)
                    .where(
                        WorkflowPreviewRunRecord.state.not_in(
                            WORKFLOW_PREVIEW_RUN_TERMINAL_STATES
                        )
                    )
                )
                or 0
            ),
        }


def _delete_database_state(*, session_factory: SessionFactory) -> dict[str, int]:
    """按外键依赖顺序删除全部 Workflow ORM 数据。"""

    counts = _read_database_counts(session_factory=session_factory)
    with session_factory.create_session() as session:
        session.execute(delete(WorkflowTriggerSourceRecord))
        session.execute(delete(WorkflowRunRecord))
        session.execute(delete(WorkflowAppRuntimeRecord))
        session.flush()
        session.execute(delete(WorkflowAppVersionRecord))
        session.flush()
        session.execute(delete(WorkflowApplicationLifecycleRecord))
        session.execute(delete(WorkflowPreviewRunRecord))
        session.execute(delete(WorkflowExecutionPolicyRecord))
        session.commit()
    return counts


def _read_history_counts(*, session_factory: SessionFactory) -> dict[str, int]:
    """读取会被执行历史清理删除的记录数量。"""

    with session_factory.create_session() as session:
        return {
            "workflow_runs": _count_rows(session, WorkflowRunRecord),
            "workflow_preview_runs": _count_rows(session, WorkflowPreviewRunRecord),
        }


def _delete_execution_history(*, session_factory: SessionFactory) -> dict[str, int]:
    """删除执行历史，并清空当前资源上的调用诊断残留。"""

    counts = _read_history_counts(session_factory=session_factory)
    with session_factory.create_session() as session:
        session.execute(delete(WorkflowRunRecord))
        session.execute(delete(WorkflowPreviewRunRecord))
        for trigger_source in session.scalars(select(WorkflowTriggerSourceRecord)):
            trigger_source.last_triggered_at = None
            trigger_source.last_error = None
            trigger_source.health_summary_json = {}
        for runtime in session.scalars(select(WorkflowAppRuntimeRecord)):
            runtime.last_error = None
            runtime.health_summary_json = {}
        session.commit()
    return counts


def _resolve_reset_storage_paths(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    buffer_root: Path,
) -> tuple[Path, ...]:
    """解析允许删除的 Workflow 专属目录，并拒绝越过受信根。"""

    dataset_root = dataset_storage.root_dir.resolve()
    resolved_buffer_root = buffer_root.resolve()
    runtime_ids = _read_runtime_ids(session_factory=session_factory)
    paths: list[tuple[Path, Path]] = [
        (dataset_storage.resolve("workflows"), dataset_root),
        (
            resolved_buffer_root / "local-message" / "workflow-trigger",
            resolved_buffer_root,
        ),
    ]

    projects_root = dataset_storage.resolve("projects")
    if projects_root.is_dir():
        for project_path in sorted(projects_root.iterdir(), key=lambda item: item.name):
            if not project_path.is_dir():
                continue
            paths.extend(
                (
                    (project_path / "workflow", dataset_root),
                    (
                        project_path / "inputs" / "workflow-applications",
                        dataset_root,
                    ),
                    (
                        project_path / "results" / "workflow-applications",
                        dataset_root,
                    ),
                )
            )

    runtime_inputs_root = dataset_storage.resolve("runtime/inputs")
    for runtime_id in runtime_ids:
        paths.append((runtime_inputs_root / runtime_id, dataset_root))

    unique_paths: list[Path] = []
    seen: set[Path] = set()
    for candidate, trusted_root in paths:
        resolved_candidate = candidate.resolve()
        resolved_trusted_root = trusted_root.resolve()
        if resolved_candidate == resolved_trusted_root or not resolved_candidate.is_relative_to(
            resolved_trusted_root
        ):
            raise RuntimeError(
                "Workflow 重置路径越过受信根: "
                f"path={resolved_candidate}, root={resolved_trusted_root}"
            )
        if resolved_candidate in seen:
            continue
        seen.add(resolved_candidate)
        unique_paths.append(resolved_candidate)
    return tuple(unique_paths)


def _resolve_history_storage_paths(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> tuple[Path, ...]:
    """解析只属于 Workflow 执行历史的文件目录。"""

    dataset_root = dataset_storage.root_dir.resolve()
    paths: list[Path] = []
    runtime_root = dataset_storage.resolve("workflows/runtime")
    if runtime_root.is_dir():
        for child_path in sorted(runtime_root.iterdir(), key=lambda item: item.name):
            if child_path.name.startswith("workflow-run-") or child_path.name in {
                "preview-runs",
                "cleanup-staging",
            }:
                paths.append(child_path)

    projects_root = dataset_storage.resolve("projects")
    if projects_root.is_dir():
        for project_path in sorted(projects_root.iterdir(), key=lambda item: item.name):
            if project_path.is_dir():
                paths.append(
                    project_path / "results" / "workflow-applications"
                )

    runtime_inputs_root = dataset_storage.resolve("runtime/inputs")
    for runtime_id in _read_runtime_ids(session_factory=session_factory):
        paths.append(runtime_inputs_root / runtime_id)

    unique_paths: list[Path] = []
    seen: set[Path] = set()
    for candidate in paths:
        resolved_candidate = candidate.resolve()
        if resolved_candidate == dataset_root or not resolved_candidate.is_relative_to(
            dataset_root
        ):
            raise RuntimeError(
                "Workflow 历史路径越过数据根目录: "
                f"path={resolved_candidate}, root={dataset_root}"
            )
        if resolved_candidate in seen:
            continue
        seen.add(resolved_candidate)
        unique_paths.append(resolved_candidate)
    return tuple(unique_paths)


def _finalize_staged_paths(staged_paths: list[tuple[Path, Path]]) -> list[str]:
    """物理删除已脱离服务可见路径的暂存文件。"""

    pending_cleanup: list[str] = []
    for _, staging_path in staged_paths:
        try:
            if staging_path.is_dir():
                shutil.rmtree(staging_path)
            else:
                staging_path.unlink()
        except OSError:
            pending_cleanup.append(str(staging_path))
    return pending_cleanup


def _read_runtime_ids(*, session_factory: SessionFactory) -> tuple[str, ...]:
    """读取当前所有 Runtime id，用于精确定位临时输入目录。"""

    with session_factory.create_session() as session:
        return tuple(
            session.scalars(
                select(WorkflowAppRuntimeRecord.workflow_runtime_id).order_by(
                    WorkflowAppRuntimeRecord.workflow_runtime_id
                )
            )
        )


def _recreate_workflow_roots(*, dataset_storage: LocalDatasetStorage) -> None:
    """重建服务写入时依赖的空 Workflow 根目录。"""

    for relative_path in ("workflows/projects", "workflows/runtime"):
        dataset_storage.resolve(relative_path).mkdir(parents=True, exist_ok=True)


def _count_rows(session: object, entity: type) -> int:
    """统计 ORM 实体记录数量。"""

    return int(session.scalar(select(func.count()).select_from(entity)) or 0)
