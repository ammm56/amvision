"""Project 删除预检与聚合删除服务。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from threading import Lock
from uuid import uuid4

from backend.queue import QueueBackend, QueueMessage
from backend.contracts.workflows import (
    build_workflow_app_runtime_storage_dir,
    build_workflow_preview_run_storage_dir,
    build_workflow_run_storage_dir,
    build_workflow_trigger_source_storage_dir,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceInUseError,
    ResourceNotFoundError,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.infrastructure.persistence.project_deletion_repository import (
    ProjectDatabaseInventory,
)


_ACTIVE_TASK_STATES = {"queued", "running", "paused"}
_ACTIVE_QUEUE_STATES = {"queued", "leased"}
_ACTIVE_PREVIEW_STATES = {"created", "running"}
_ACTIVE_RUN_STATES = {"created", "queued", "dispatching", "running"}
_ACTIVE_RUNTIME_STATES = {"starting", "running", "stopping"}
_VALIDATION_SESSION_ROOTS = (
    "runtime/validation-sessions",
    "runtime/validation-sessions-classification",
    "runtime/validation-sessions-segmentation",
    "runtime/validation-sessions-pose",
    "runtime/validation-sessions-obb",
)


@dataclass(frozen=True)
class ProjectDeletionBlocker:
    """描述一个阻止 Project 删除的活动资源。"""

    resource_kind: str
    resource_id: str
    state: str


@dataclass(frozen=True)
class ProjectDeletionPreview:
    """描述 Project 删除的可执行性和影响范围。"""

    project_id: str
    project_source: str
    protected: bool
    can_delete: bool
    blockers: tuple[ProjectDeletionBlocker, ...]
    resource_counts: dict[str, int]


@dataclass(frozen=True)
class ProjectDeletionResult:
    """描述已完成逻辑删除的 Project。"""

    project_id: str
    operation_id: str
    cleanup_object_key: str | None
    task_ids: tuple[str, ...]
    resource_counts: dict[str, int]


class ProjectDeletionService:
    """实现 Project 预检、事务删除和存储回滚。"""

    _lock_guard = Lock()
    _project_locks: dict[str, Lock] = {}

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        queue_backend: QueueBackend,
        default_project_id: str,
        configured_project_ids: tuple[str, ...],
    ) -> None:
        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.queue_backend = queue_backend
        self.default_project_id = default_project_id.strip()
        self.configured_project_ids = frozenset(
            project_id.strip() for project_id in configured_project_ids if project_id.strip()
        )

    def preview(self, *, project_id: str, project_source: str) -> ProjectDeletionPreview:
        """预检 Project 删除边界，不改变任何状态。"""

        normalized_project_id = self._require_project(project_id)
        unit_of_work = self._open_unit_of_work()
        try:
            inventory = unit_of_work.project_deletions.inspect(normalized_project_id)
        finally:
            unit_of_work.close()
        queue_messages = self.queue_backend.list_tasks_by_references(
            references=self._build_queue_references(
                project_id=normalized_project_id,
                task_ids=tuple(task_id for task_id, _state in inventory.tasks),
            )
        )
        protected = (
            normalized_project_id == self.default_project_id
            or normalized_project_id in self.configured_project_ids
            or project_source != "local_disk"
        )
        blockers = self._build_blockers(inventory, queue_messages=queue_messages)
        counts = self._build_resource_counts(
            project_id=normalized_project_id,
            inventory=inventory,
            queue_messages=queue_messages,
        )
        return ProjectDeletionPreview(
            project_id=normalized_project_id,
            project_source=project_source,
            protected=protected,
            can_delete=not protected and not blockers,
            blockers=blockers,
            resource_counts=counts,
        )

    def delete(
        self,
        *,
        project_id: str,
        project_source: str,
        confirmation: str,
    ) -> ProjectDeletionResult:
        """在项目锁内重新预检，再删除数据库和本地存储。"""

        normalized_project_id = self._require_project(project_id)
        if confirmation.strip() != normalized_project_id:
            raise InvalidRequestError(
                "删除确认必须与 Project id 完全一致",
                details={"project_id": normalized_project_id},
            )
        with self._get_project_lock(normalized_project_id):
            preview = self.preview(
                project_id=normalized_project_id,
                project_source=project_source,
            )
            if preview.protected:
                raise InvalidRequestError(
                    "默认 Project 和配置目录中的 Project 不允许删除",
                    details={"project_id": normalized_project_id},
                )
            if preview.blockers:
                raise ResourceInUseError(
                    "Project 仍有活动资源，停止或取消后才能删除",
                    details={
                        "project_id": normalized_project_id,
                        "blockers": [blocker.__dict__ for blocker in preview.blockers],
                    },
                )
            operation_id = f"project-deletion-{uuid4().hex}"
            staging_root = f"runtime/project-deletion-staging/{operation_id}"
            unit_of_work = self._open_unit_of_work()
            moved_paths: list[tuple[str, str]] = []
            try:
                inventory = unit_of_work.project_deletions.inspect(normalized_project_id)
                queue_messages = self.queue_backend.list_tasks_by_references(
                    references=self._build_queue_references(
                        project_id=normalized_project_id,
                        task_ids=tuple(task_id for task_id, _state in inventory.tasks),
                    )
                )
                final_blockers = self._build_blockers(
                    inventory,
                    queue_messages=queue_messages,
                )
                if final_blockers:
                    raise ResourceInUseError(
                        "Project 仍有活动资源，停止或取消后才能删除",
                        details={
                            "project_id": normalized_project_id,
                            "blockers": [
                                blocker.__dict__ for blocker in final_blockers
                            ],
                        },
                    )
                resource_counts = self._build_resource_counts(
                    project_id=normalized_project_id,
                    inventory=inventory,
                    queue_messages=queue_messages,
                )
                for source_path in self._collect_storage_paths(
                    project_id=normalized_project_id,
                    inventory=inventory,
                ):
                    destination_path = (
                        f"{staging_root}/{len(moved_paths):04d}/"
                        f"{PurePosixPath(source_path).name}"
                    )
                    self.dataset_storage.move_tree(source_path, destination_path)
                    moved_paths.append((source_path, destination_path))
                unit_of_work.project_deletions.delete(normalized_project_id)
                unit_of_work.commit()
            except Exception:
                unit_of_work.rollback()
                for source_path, destination_path in reversed(moved_paths):
                    if self.dataset_storage.resolve(destination_path).exists():
                        self.dataset_storage.move_tree(destination_path, source_path)
                self.dataset_storage.delete_tree(staging_root)
                raise
            finally:
                unit_of_work.close()
            return ProjectDeletionResult(
                project_id=normalized_project_id,
                operation_id=operation_id,
                cleanup_object_key=(
                    staging_root
                    if moved_paths or queue_messages
                    else None
                ),
                task_ids=tuple(task_id for task_id, _state in inventory.tasks),
                resource_counts=resource_counts,
            )

    def cleanup(
        self,
        cleanup_object_key: str | None,
        project_id: str,
        task_ids: tuple[str, ...],
    ) -> None:
        """删除已提交项目的隔离存储数据。"""

        if cleanup_object_key:
            self.dataset_storage.delete_tree(cleanup_object_key)
        self.queue_backend.delete_tasks_by_references(
            references=self._build_queue_references(
                project_id=project_id,
                task_ids=task_ids,
            ),
            statuses=("completed", "failed"),
        )

    @staticmethod
    def _build_queue_references(
        *, project_id: str, task_ids: tuple[str, ...]
    ) -> tuple[tuple[str, object], ...]:
        """构建兼容新旧队列消息的 Project 引用集合。"""

        return (("project_id", project_id),) + tuple(
            ("task_id", task_id) for task_id in task_ids
        )

    def _collect_storage_paths(
        self,
        *,
        project_id: str,
        inventory: ProjectDatabaseInventory,
    ) -> tuple[str, ...]:
        candidates = [
            f"projects/{project_id}",
            f"workflows/projects/{project_id}",
        ]
        for task_id, _state in inventory.tasks:
            candidates.extend(
                (
                    f"task-runs/{task_id}",
                    f"task-runs/training/{task_id}",
                    f"task-runs/conversion/{task_id}",
                    f"task-runs/evaluation/{task_id}",
                    f"task-runs/inference/{task_id}",
                )
            )
        for deployment_id, _state in inventory.deployments:
            candidates.append(f"deployments/instances/{deployment_id}")
        candidates.extend(
            build_workflow_preview_run_storage_dir(resource_id)
            for resource_id, _state in inventory.preview_runs
        )
        candidates.extend(
            build_workflow_app_runtime_storage_dir(resource_id)
            for resource_id, _desired, _observed in inventory.app_runtimes
        )
        candidates.extend(
            build_workflow_run_storage_dir(resource_id)
            for resource_id, _state in inventory.workflow_runs
        )
        candidates.extend(
            build_workflow_trigger_source_storage_dir(resource_id)
            for resource_id, _enabled, _desired, _observed in inventory.trigger_sources
        )
        candidates.extend(inventory.model_file_storage_uris)
        candidates.extend(self._find_validation_session_paths(project_id))

        existing: list[str] = []
        for candidate in candidates:
            normalized = self._normalize_local_object_key(candidate)
            if normalized is None or not self.dataset_storage.resolve(normalized).exists():
                continue
            if any(
                normalized == parent or normalized.startswith(f"{parent}/")
                for parent in existing
            ):
                continue
            existing.append(normalized)
        return tuple(existing)

    def _build_resource_counts(
        self,
        *,
        project_id: str,
        inventory: ProjectDatabaseInventory,
        queue_messages: tuple[QueueMessage, ...],
    ) -> dict[str, int]:
        """合并数据库、队列和文件系统资源计数。"""

        counts = dict(inventory.counts)
        counts["queue_messages"] = len(queue_messages)
        counts["workflow_documents"] = self._count_directories(
            f"workflows/projects/{project_id}/applications"
        )
        counts["validation_sessions"] = len(
            self._find_validation_session_paths(project_id)
        )
        return counts

    def _find_validation_session_paths(self, project_id: str) -> tuple[str, ...]:
        matched: list[str] = []
        for root in _VALIDATION_SESSION_ROOTS:
            root_path = self.dataset_storage.resolve(root)
            if not root_path.is_dir():
                continue
            for session_path in root_path.iterdir():
                manifest_path = session_path / "session.json"
                if not manifest_path.is_file():
                    continue
                try:
                    payload = self.dataset_storage.read_json(
                        f"{root}/{session_path.name}/session.json"
                    )
                except (OSError, ValueError, TypeError):
                    continue
                if isinstance(payload, dict) and payload.get("project_id") == project_id:
                    matched.append(f"{root}/{session_path.name}")
                    prediction_path = f"runtime/validation/{session_path.name}"
                    if self.dataset_storage.resolve(prediction_path).exists():
                        matched.append(prediction_path)
        return tuple(matched)

    @staticmethod
    def _build_blockers(
        inventory: ProjectDatabaseInventory,
        *,
        queue_messages: tuple[QueueMessage, ...],
    ) -> tuple[ProjectDeletionBlocker, ...]:
        blockers: list[ProjectDeletionBlocker] = []
        for resource_id, state in inventory.tasks:
            if state in _ACTIVE_TASK_STATES:
                blockers.append(ProjectDeletionBlocker("task", resource_id, state))
        for resource_id, state in inventory.deployments:
            if state == "active":
                blockers.append(ProjectDeletionBlocker("deployment", resource_id, state))
        for resource_id, state in inventory.preview_runs:
            if state in _ACTIVE_PREVIEW_STATES:
                blockers.append(ProjectDeletionBlocker("workflow_preview", resource_id, state))
        for resource_id, desired, observed in inventory.app_runtimes:
            if desired in _ACTIVE_RUNTIME_STATES or observed in _ACTIVE_RUNTIME_STATES:
                blockers.append(
                    ProjectDeletionBlocker(
                        "workflow_runtime", resource_id, f"{desired}/{observed}"
                    )
                )
        for resource_id, state in inventory.workflow_runs:
            if state in _ACTIVE_RUN_STATES:
                blockers.append(ProjectDeletionBlocker("workflow_run", resource_id, state))
        for resource_id, enabled, desired, observed in inventory.trigger_sources:
            if enabled or desired in _ACTIVE_RUNTIME_STATES or observed in _ACTIVE_RUNTIME_STATES:
                blockers.append(
                    ProjectDeletionBlocker(
                        "trigger_source", resource_id, f"{desired}/{observed}"
                    )
                )
        for queue_message in queue_messages:
            if queue_message.status in _ACTIVE_QUEUE_STATES:
                blockers.append(
                    ProjectDeletionBlocker(
                        "queue_message",
                        queue_message.task_id,
                        queue_message.status,
                    )
                )
        return tuple(blockers)

    def _require_project(self, project_id: str) -> str:
        normalized = project_id.strip()
        if not normalized:
            raise InvalidRequestError("Project id 不能为空")
        project_path = self.dataset_storage.resolve(f"projects/{normalized}")
        if not project_path.is_dir() and normalized not in self.configured_project_ids:
            raise ResourceNotFoundError(
                "请求的 Project 不存在", details={"project_id": normalized}
            )
        return normalized

    def _count_directories(self, object_key: str) -> int:
        root = self.dataset_storage.resolve(object_key)
        return sum(1 for child in root.iterdir() if child.is_dir()) if root.is_dir() else 0

    def _normalize_local_object_key(self, value: object) -> str | None:
        raw = str(value or "").strip().replace("\\", "/")
        if not raw or "://" in raw or raw.startswith("/") or ":" in raw.split("/", 1)[0]:
            return None
        try:
            return self.dataset_storage.resolve(raw).relative_to(
                self.dataset_storage.root_dir
            ).as_posix()
        except (ValueError, InvalidRequestError):
            return None

    def _open_unit_of_work(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self.session_factory.create_session())

    @classmethod
    def _get_project_lock(cls, project_id: str) -> Lock:
        with cls._lock_guard:
            return cls._project_locks.setdefault(project_id, Lock())
