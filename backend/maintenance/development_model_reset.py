"""开发阶段模型、任务和部署派生数据断代重置。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import delete, func, select

from backend.service.application.models.catalog.pretrained_catalog import (
    YoloXPretrainedModelCatalogSeeder,
)
from backend.service.application.models.catalog.yolo_model_pretrained_catalog import (
    YoloModelPretrainedCatalogSeeder,
)
from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.deployment_orm import (
    DeploymentInstanceRecord,
)
from backend.service.infrastructure.persistence.model_file_orm import ModelFileRecord
from backend.service.infrastructure.persistence.model_orm import (
    ModelBuildRecord,
    ModelRecord,
    ModelVersionRecord,
)
from backend.service.infrastructure.persistence.task_orm import (
    TaskAttemptEntity,
    TaskEventEntity,
    TaskRecordEntity,
)
from backend.service.infrastructure.persistence.workflow_runtime_orm import (
    WorkflowAppRuntimeRecord,
    WorkflowPreviewRunRecord,
    WorkflowRunRecord,
)
from backend.service.infrastructure.persistence.workflow_trigger_source_orm import (
    WorkflowTriggerSourceRecord,
)


DEVELOPMENT_MODEL_RESET_COMMAND = "reset-development-model-state"
_PRESERVED_TASK_KINDS = frozenset({"dataset-import", "dataset-export"})
_PRESERVED_QUEUE_NAMES = frozenset(
    {"_worker_health", "dataset-exports", "dataset-imports"}
)
_DERIVED_STORAGE_PATHS = (
    "task-runs",
    "deployments/instances",
    "workflows/runtime",
)


@dataclass(frozen=True)
class DevelopmentModelResetRequest:
    """描述一次开发模型状态重置请求。"""

    confirm: bool = False


def reset_development_model_state(
    *,
    request: DevelopmentModelResetRequest,
    backend_service_settings: object,
) -> dict[str, object]:
    """删除模型派生状态并从磁盘 manifest 重新登记预训练模型。"""

    session_factory = SessionFactory(backend_service_settings.to_database_settings())
    dataset_storage = LocalDatasetStorage(
        backend_service_settings.to_dataset_storage_settings()
    )
    queue_root = Path(backend_service_settings.queue.root_dir)
    worker_root = queue_root.parent / "worker"
    buffer_root = Path(backend_service_settings.local_buffer_broker.root_dir)
    initialize_database_schema(session_factory)
    preview = _build_reset_preview(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_root=queue_root,
        worker_root=worker_root,
        buffer_root=buffer_root,
    )
    if not request.confirm:
        session_factory.engine.dispose()
        return {
            "command": DEVELOPMENT_MODEL_RESET_COMMAND,
            "confirmed": False,
            "preview": preview,
        }

    validated_seed_counts = _validate_pretrained_catalog_seed(
        dataset_storage=dataset_storage
    )
    staging_token = uuid4().hex
    staged_paths: list[tuple[Path, Path]] = []
    try:
        for source_path in _resolve_reset_storage_paths(
            dataset_storage=dataset_storage,
            queue_root=queue_root,
            worker_root=worker_root,
            buffer_root=buffer_root,
        ):
            if not source_path.exists():
                continue
            staging_path = source_path.with_name(
                f".{source_path.name}.model-reset-{staging_token}"
            )
            source_path.rename(staging_path)
            staged_paths.append((source_path, staging_path))

        deleted_counts = _delete_database_state(session_factory=session_factory)
    except Exception:
        for source_path, staging_path in reversed(staged_paths):
            if staging_path.exists() and not source_path.exists():
                staging_path.rename(source_path)
        session_factory.engine.dispose()
        raise

    pending_cleanup: list[str] = []
    for _, staging_path in staged_paths:
        try:
            if staging_path.is_dir():
                shutil.rmtree(staging_path)
            else:
                staging_path.unlink()
        except OSError:
            pending_cleanup.append(str(staging_path))

    _recreate_runtime_directories(
        dataset_storage=dataset_storage,
        queue_root=queue_root,
        worker_root=worker_root,
        buffer_root=buffer_root,
    )
    seed_runtime = SimpleNamespace(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    YoloXPretrainedModelCatalogSeeder().seed(seed_runtime)
    YoloModelPretrainedCatalogSeeder().seed(seed_runtime)
    seeded_counts = _read_model_counts(session_factory=session_factory)
    session_factory.engine.dispose()
    return {
        "command": DEVELOPMENT_MODEL_RESET_COMMAND,
        "confirmed": True,
        "preserved": {
            "dataset_storage": "datasets",
            "pretrained_storage": "models/pretrained",
            "dataset_task_kinds": sorted(_PRESERVED_TASK_KINDS),
            "workflow_templates": "workflows/projects",
        },
        "deleted_counts": deleted_counts,
        "validated_seed_counts": validated_seed_counts,
        "seeded_counts": seeded_counts,
        "pending_cleanup": pending_cleanup,
    }


def _build_reset_preview(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    queue_root: Path,
    worker_root: Path,
    buffer_root: Path,
) -> dict[str, object]:
    """构建不修改数据库和文件系统的重置预览。"""

    with session_factory.create_session() as session:
        model_task_count = session.scalar(
            select(func.count())
            .select_from(TaskRecordEntity)
            .where(TaskRecordEntity.task_kind.not_in(_PRESERVED_TASK_KINDS))
        )
        return {
            **_read_model_counts(session_factory=session_factory),
            "model_task_count": int(model_task_count or 0),
            "storage_paths": [
                str(path)
                for path in _resolve_reset_storage_paths(
                    dataset_storage=dataset_storage,
                    queue_root=queue_root,
                    worker_root=worker_root,
                    buffer_root=buffer_root,
                )
                if path.exists()
            ],
        }


def _delete_database_state(*, session_factory: SessionFactory) -> dict[str, int]:
    """按依赖顺序删除模型、部署和非数据集任务记录。"""

    with session_factory.create_session() as session:
        model_task_ids = tuple(
            session.scalars(
                select(TaskRecordEntity.task_id).where(
                    TaskRecordEntity.task_kind.not_in(_PRESERVED_TASK_KINDS)
                )
            )
        )
        counts = {
            "workflow_trigger_sources": _count_rows(
                session, WorkflowTriggerSourceRecord
            ),
            "workflow_runs": _count_rows(session, WorkflowRunRecord),
            "workflow_app_runtimes": _count_rows(
                session, WorkflowAppRuntimeRecord
            ),
            "workflow_preview_runs": _count_rows(
                session, WorkflowPreviewRunRecord
            ),
            "deployment_instances": _count_rows(session, DeploymentInstanceRecord),
            "model_files": _count_rows(session, ModelFileRecord),
            "model_builds": _count_rows(session, ModelBuildRecord),
            "model_versions": _count_rows(session, ModelVersionRecord),
            "models": _count_rows(session, ModelRecord),
            "tasks": len(model_task_ids),
        }
        session.execute(delete(WorkflowTriggerSourceRecord))
        session.execute(delete(WorkflowRunRecord))
        session.execute(delete(WorkflowAppRuntimeRecord))
        session.execute(delete(WorkflowPreviewRunRecord))
        session.execute(delete(DeploymentInstanceRecord))
        session.execute(delete(ModelFileRecord))
        session.execute(delete(ModelBuildRecord))
        session.execute(delete(ModelVersionRecord))
        session.execute(delete(ModelRecord))
        if model_task_ids:
            session.execute(
                delete(TaskEventEntity).where(
                    TaskEventEntity.task_id.in_(model_task_ids)
                )
            )
            session.execute(
                delete(TaskAttemptEntity).where(
                    TaskAttemptEntity.task_id.in_(model_task_ids)
                )
            )
            session.execute(
                delete(TaskRecordEntity).where(
                    TaskRecordEntity.task_id.in_(model_task_ids)
                )
            )
        session.commit()
        return counts


def _read_model_counts(*, session_factory: SessionFactory) -> dict[str, int]:
    """读取当前模型聚合数量。"""

    with session_factory.create_session() as session:
        return {
            "models": _count_rows(session, ModelRecord),
            "model_versions": _count_rows(session, ModelVersionRecord),
            "model_builds": _count_rows(session, ModelBuildRecord),
            "model_files": _count_rows(session, ModelFileRecord),
            "deployment_instances": _count_rows(session, DeploymentInstanceRecord),
        }


def _validate_pretrained_catalog_seed(
    *,
    dataset_storage: LocalDatasetStorage,
) -> dict[str, int]:
    """在独立内存数据库中验证全部预训练 manifest 可按新契约登记。"""

    validation_session_factory = SessionFactory(
        DatabaseSettings(url="sqlite+pysqlite:///:memory:")
    )
    initialize_database_schema(validation_session_factory)
    seed_runtime = SimpleNamespace(
        session_factory=validation_session_factory,
        dataset_storage=dataset_storage,
    )
    try:
        YoloXPretrainedModelCatalogSeeder().seed(seed_runtime)
        YoloModelPretrainedCatalogSeeder().seed(seed_runtime)
        return _read_model_counts(session_factory=validation_session_factory)
    finally:
        validation_session_factory.engine.dispose()


def _count_rows(session: object, entity: type) -> int:
    """统计 ORM 实体记录数量。"""

    return int(session.scalar(select(func.count()).select_from(entity)) or 0)


def _resolve_reset_storage_paths(
    *,
    dataset_storage: LocalDatasetStorage,
    queue_root: Path,
    worker_root: Path,
    buffer_root: Path,
) -> tuple[Path, ...]:
    """解析允许重置的固定派生目录。"""

    queue_paths = (
        tuple(
            path
            for path in queue_root.iterdir()
            if path.name not in _PRESERVED_QUEUE_NAMES
        )
        if queue_root.exists()
        else ()
    )
    paths = [
        *(dataset_storage.resolve(item) for item in _DERIVED_STORAGE_PATHS),
        *queue_paths,
        worker_root.resolve(),
        buffer_root.resolve(),
    ]
    protected_paths = {
        dataset_storage.resolve("datasets").resolve(),
        dataset_storage.resolve("models/pretrained").resolve(),
        dataset_storage.resolve("workflows/projects").resolve(),
    }
    for path in paths:
        resolved_path = path.resolve()
        if resolved_path in protected_paths:
            raise RuntimeError(f"重置路径命中受保护目录: {resolved_path}")
    return tuple(paths)


def _recreate_runtime_directories(
    *,
    dataset_storage: LocalDatasetStorage,
    queue_root: Path,
    worker_root: Path,
    buffer_root: Path,
) -> None:
    """重建运行期需要的空目录。"""

    for path in (
        *(dataset_storage.resolve(item) for item in _DERIVED_STORAGE_PATHS),
        queue_root,
        worker_root,
        buffer_root,
    ):
        path.mkdir(parents=True, exist_ok=True)
