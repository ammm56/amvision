"""Project 删除预检与聚合删除服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath

from backend.queue import QueueBackend, QueueMessage
from backend.contracts.workflows import (
    build_workflow_app_runtime_storage_dir,
    build_workflow_preview_run_storage_dir,
    build_workflow_run_storage_dir,
    build_workflow_trigger_source_storage_dir,
)
from backend.service.application.errors import (
    InvalidRequestError,
    PersistenceOperationError,
    ResourceInUseError,
    ResourceNotFoundError,
)
from backend.service.application.workflows.application_lifecycle import (
    WorkflowApplicationLifecycleService,
)
from backend.service.application.workflows.lifecycle_resource_keys import (
    build_workflow_project_lifecycle_resource_key,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
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
_PROJECT_DELETION_STAGING_ROOT = "runtime/project-deletion-staging"
_PROJECT_DELETION_MANIFEST_NAME = "manifest.json"


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


@dataclass(frozen=True)
class ProjectDeletionRecoveryResult:
    """描述启动期 Project 删除恢复结果。"""

    rolled_back_deletions: int
    completed_cleanups: int


class ProjectDeletionService:
    """实现 Project 预检、事务删除和存储回滚。"""

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
            project_id.strip()
            for project_id in configured_project_ids
            if project_id.strip()
        )
        self.application_lifecycle = WorkflowApplicationLifecycleService(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        )

    def preview(
        self, *, project_id: str, project_source: str
    ) -> ProjectDeletionPreview:
        """预检 Project 删除边界，不改变任何状态。"""

        normalized_project_id = self._require_project(project_id)
        project_sentinel_resource_key = build_workflow_project_lifecycle_resource_key(
            project_id=normalized_project_id
        )
        unit_of_work = self._open_unit_of_work()
        try:
            inventory = unit_of_work.project_deletions.inspect(
                normalized_project_id,
                project_sentinel_resource_key=project_sentinel_resource_key,
            )
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
        """占用持久 Project sentinel 后删除数据库和本地存储。"""

        normalized_project_id = self._require_project(project_id)
        if confirmation.strip() != normalized_project_id:
            raise InvalidRequestError(
                "删除确认必须与 Project id 完全一致",
                details={"project_id": normalized_project_id},
            )
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

        sentinel_resource_key = build_workflow_project_lifecycle_resource_key(
            project_id=normalized_project_id
        )
        deletion_claim = self.application_lifecycle.acquire_project_deletion(
            project_id=normalized_project_id
        )
        operation_id = str(deletion_claim.operation_id)
        staging_root = self._build_staging_root(operation_id)
        moved_paths: list[tuple[str, str]] = []
        queue_messages: tuple[QueueMessage, ...] = ()
        try:
            # sentinel 已提交并阻止新的 Workflow mutation。最终盘点使用独立
            # 短只读 UOW，必须在任何 manifest/move 文件 I/O 前关闭。
            inventory_unit_of_work = self._open_unit_of_work()
            try:
                inventory = inventory_unit_of_work.project_deletions.inspect(
                    normalized_project_id,
                    project_sentinel_resource_key=sentinel_resource_key,
                )
            finally:
                inventory_unit_of_work.close()
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
                        "blockers": [blocker.__dict__ for blocker in final_blockers],
                    },
                )
            resource_counts = self._build_resource_counts(
                project_id=normalized_project_id,
                inventory=inventory,
                queue_messages=queue_messages,
            )
            storage_paths = self._collect_storage_paths(
                project_id=normalized_project_id,
                inventory=inventory,
            )
            planned_paths = tuple(
                (
                    source_path,
                    f"{staging_root}/{index:04d}/{PurePosixPath(source_path).name}",
                )
                for index, source_path in enumerate(storage_paths)
            )
            task_ids = tuple(task_id for task_id, _state in inventory.tasks)
            self._write_deletion_manifest(
                staging_root=staging_root,
                project_id=normalized_project_id,
                operation_id=operation_id,
                paths=planned_paths,
                task_ids=task_ids,
            )
            for source_path, destination_path in planned_paths:
                self.dataset_storage.move_tree(source_path, destination_path)
                moved_paths.append((source_path, destination_path))

            final_read_unit_of_work = self._open_unit_of_work()
            try:
                queue_inventory = final_read_unit_of_work.project_deletions.inspect(
                    normalized_project_id,
                    project_sentinel_resource_key=sentinel_resource_key,
                )
            finally:
                final_read_unit_of_work.close()
            final_queue_messages = self.queue_backend.list_tasks_by_references(
                references=self._build_queue_references(
                    project_id=normalized_project_id,
                    task_ids=tuple(
                        task_id for task_id, _state in queue_inventory.tasks
                    ),
                )
            )

            # 最终事务先以条件 UPDATE 再次确认 sentinel 所有权并取得写入
            # 顺序，随后重新盘点、聚合删除和 tombstone CAS；事务内不做 I/O。
            final_unit_of_work = self._open_unit_of_work()
            try:
                still_owned = final_unit_of_work.workflow_runtime.touch_claimed_workflow_project_deletion_sentinel(
                    project_id=normalized_project_id,
                    sentinel_resource_key=sentinel_resource_key,
                    expected_generation=deletion_claim.generation,
                    operation_id=operation_id,
                    updated_at=_now_isoformat(),
                )
                if not still_owned:
                    raise PersistenceOperationError(
                        "Project 删除 sentinel 已被其他 generation 取代",
                        details={
                            "project_id": normalized_project_id,
                            "operation_id": operation_id,
                        },
                    )
                final_inventory = final_unit_of_work.project_deletions.inspect(
                    normalized_project_id,
                    project_sentinel_resource_key=sentinel_resource_key,
                )
                final_blockers = self._build_blockers(
                    final_inventory,
                    queue_messages=final_queue_messages,
                )
                if final_blockers:
                    raise ResourceInUseError(
                        "Project 删除提交前出现新的活动资源",
                        details={
                            "project_id": normalized_project_id,
                            "blockers": [
                                blocker.__dict__ for blocker in final_blockers
                            ],
                        },
                    )
                final_unit_of_work.project_deletions.delete(
                    normalized_project_id,
                    project_sentinel_resource_key=sentinel_resource_key,
                )
                completed = final_unit_of_work.workflow_runtime.complete_workflow_application_lifecycle(
                    project_id=deletion_claim.project_id,
                    application_id=deletion_claim.application_id,
                    expected_generation=deletion_claim.generation,
                    operation_state=deletion_claim.state,
                    operation_id=operation_id,
                    updated_at=_now_isoformat(),
                    deleted=True,
                )
                if not completed:
                    raise PersistenceOperationError(
                        "Project 删除 tombstone 已被其他 generation 取代",
                        details={
                            "project_id": normalized_project_id,
                            "operation_id": operation_id,
                        },
                    )
                final_unit_of_work.commit()
            except Exception:
                final_unit_of_work.rollback()
                raise
            finally:
                final_unit_of_work.close()
        except Exception:
            self._restore_moved_paths(moved_paths)
            self.dataset_storage.delete_tree(staging_root)
            try:
                self.application_lifecycle.complete(
                    deletion_claim,
                    deleted=False,
                )
            except Exception:  # noqa: BLE001 - 保留原始删除错误供调用方处理
                pass
            raise
        return ProjectDeletionResult(
            project_id=normalized_project_id,
            operation_id=operation_id,
            cleanup_object_key=staging_root,
            task_ids=task_ids,
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

    def recover_interrupted_deletions(self) -> ProjectDeletionRecoveryResult:
        """在 API 接收请求前回滚中断删除并补做已提交清理。"""

        rolled_back = 0
        for claim in self.application_lifecycle.list_project_deletion_claims():
            if claim.operation_id is None:
                raise PersistenceOperationError(
                    "Project 删除 sentinel 缺少 operation_id",
                    details={"project_id": claim.project_id},
                )
            staging_root = self._build_staging_root(claim.operation_id)
            staging_path = self.dataset_storage.resolve(staging_root)
            manifest = self._read_deletion_manifest(staging_root)
            # manifest 在第一个 move 前原子落盘。只有临时目录而没有有效
            # manifest 说明进程中断于 manifest 写入阶段，权威路径尚未移动。
            if manifest is None and staging_path.exists():
                self.dataset_storage.delete_tree(staging_root)
            if manifest is not None:
                self._restore_moved_paths(self._manifest_paths(manifest))
                self.dataset_storage.delete_tree(staging_root)
            self.application_lifecycle.complete(claim, deleted=False)
            rolled_back += 1

        completed_cleanups = 0
        staging_parent = self.dataset_storage.resolve(_PROJECT_DELETION_STAGING_ROOT)
        if staging_parent.is_dir():
            for child in tuple(staging_parent.iterdir()):
                if not child.is_dir():
                    continue
                staging_root = f"{_PROJECT_DELETION_STAGING_ROOT}/{child.name}"
                manifest = self._read_deletion_manifest(staging_root)
                if manifest is None:
                    continue
                project_id = str(manifest.get("project_id") or "").strip()
                if not project_id:
                    raise PersistenceOperationError(
                        "Project 删除 manifest 缺少 project_id",
                        details={"staging_root": staging_root},
                    )
                sentinel_key = build_workflow_project_lifecycle_resource_key(
                    project_id=project_id
                )
                try:
                    sentinel = self.application_lifecycle.get(
                        project_id=project_id,
                        application_id=sentinel_key,
                    )
                except ResourceNotFoundError:
                    continue
                if not sentinel.deleted:
                    continue
                self.cleanup(
                    staging_root,
                    project_id,
                    self._manifest_task_ids(manifest),
                )
                completed_cleanups += 1
        return ProjectDeletionRecoveryResult(
            rolled_back_deletions=rolled_back,
            completed_cleanups=completed_cleanups,
        )

    @staticmethod
    def _build_staging_root(operation_id: str) -> str:
        """构建单次 Project 删除 staging 根路径。"""

        return f"{_PROJECT_DELETION_STAGING_ROOT}/{operation_id}"

    def _write_deletion_manifest(
        self,
        *,
        staging_root: str,
        project_id: str,
        operation_id: str,
        paths: tuple[tuple[str, str], ...],
        task_ids: tuple[str, ...],
    ) -> None:
        """在任何 move 之前原子写入可恢复删除计划。"""

        self.dataset_storage.write_json(
            f"{staging_root}/{_PROJECT_DELETION_MANIFEST_NAME}",
            {
                "format_id": "amvision.project-deletion-manifest.v1",
                "project_id": project_id,
                "operation_id": operation_id,
                "paths": [
                    {"source": source, "destination": destination}
                    for source, destination in paths
                ],
                "task_ids": list(task_ids),
            },
        )

    def _read_deletion_manifest(self, staging_root: str) -> dict[str, object] | None:
        """读取并校验 Project 删除恢复 manifest。"""

        manifest_key = f"{staging_root}/{_PROJECT_DELETION_MANIFEST_NAME}"
        if not self.dataset_storage.resolve(manifest_key).is_file():
            return None
        payload = self.dataset_storage.read_json(manifest_key)
        if not isinstance(payload, dict) or payload.get("format_id") != (
            "amvision.project-deletion-manifest.v1"
        ):
            raise PersistenceOperationError(
                "Project 删除恢复 manifest 格式无效",
                details={"manifest_key": manifest_key},
            )
        return payload

    @staticmethod
    def _manifest_paths(
        manifest: dict[str, object],
    ) -> list[tuple[str, str]]:
        """从恢复 manifest 读取已规划路径。"""

        raw_paths = manifest.get("paths")
        if not isinstance(raw_paths, list):
            raise PersistenceOperationError("Project 删除 manifest.paths 格式无效")
        paths: list[tuple[str, str]] = []
        for item in raw_paths:
            if not isinstance(item, dict):
                raise PersistenceOperationError("Project 删除 manifest 路径项格式无效")
            source = str(item.get("source") or "").strip()
            destination = str(item.get("destination") or "").strip()
            if not source or not destination:
                raise PersistenceOperationError("Project 删除 manifest 路径不能为空")
            paths.append((source, destination))
        return paths

    @staticmethod
    def _manifest_task_ids(manifest: dict[str, object]) -> tuple[str, ...]:
        """从恢复 manifest 读取队列 task id。"""

        raw_task_ids = manifest.get("task_ids", [])
        if not isinstance(raw_task_ids, list):
            raise PersistenceOperationError("Project 删除 manifest.task_ids 格式无效")
        return tuple(str(item).strip() for item in raw_task_ids if str(item).strip())

    def _restore_moved_paths(self, paths: list[tuple[str, str]]) -> None:
        """按删除计划逆序恢复已经移动的路径。"""

        for source_path, destination_path in reversed(paths):
            if not self.dataset_storage.resolve(destination_path).exists():
                continue
            if self.dataset_storage.resolve(source_path).exists():
                raise PersistenceOperationError(
                    "Project 删除恢复时源路径和 staging 路径同时存在",
                    details={
                        "source_path": source_path,
                        "destination_path": destination_path,
                    },
                )
            self.dataset_storage.move_tree(destination_path, source_path)

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
            if (
                normalized is None
                or not self.dataset_storage.resolve(normalized).exists()
            ):
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
                if (
                    isinstance(payload, dict)
                    and payload.get("project_id") == project_id
                ):
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
                blockers.append(
                    ProjectDeletionBlocker("deployment", resource_id, state)
                )
        for resource_id, state in inventory.preview_runs:
            if state in _ACTIVE_PREVIEW_STATES:
                blockers.append(
                    ProjectDeletionBlocker("workflow_preview", resource_id, state)
                )
        for resource_id, desired, observed in inventory.app_runtimes:
            if desired in _ACTIVE_RUNTIME_STATES or observed in _ACTIVE_RUNTIME_STATES:
                blockers.append(
                    ProjectDeletionBlocker(
                        "workflow_runtime", resource_id, f"{desired}/{observed}"
                    )
                )
        for resource_id, state in inventory.workflow_runs:
            if state in _ACTIVE_RUN_STATES:
                blockers.append(
                    ProjectDeletionBlocker("workflow_run", resource_id, state)
                )
        for resource_id, enabled, desired, observed in inventory.trigger_sources:
            if (
                enabled
                or desired in _ACTIVE_RUNTIME_STATES
                or observed in _ACTIVE_RUNTIME_STATES
            ):
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
        return (
            sum(1 for child in root.iterdir() if child.is_dir()) if root.is_dir() else 0
        )

    def _normalize_local_object_key(self, value: object) -> str | None:
        raw = str(value or "").strip().replace("\\", "/")
        if (
            not raw
            or "://" in raw
            or raw.startswith("/")
            or ":" in raw.split("/", 1)[0]
        ):
            return None
        try:
            return (
                self.dataset_storage.resolve(raw)
                .relative_to(self.dataset_storage.root_dir)
                .as_posix()
            )
        except (ValueError, InvalidRequestError):
            return None

    def _open_unit_of_work(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self.session_factory.create_session())


def _now_isoformat() -> str:
    """返回 UTC ISO-8601 时间。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
