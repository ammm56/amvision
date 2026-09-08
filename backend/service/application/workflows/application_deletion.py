"""Workflow Application 聚合物理删除与启动恢复服务。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from backend.contracts.workflows import (
    build_workflow_preview_run_storage_dir,
    build_workflow_run_storage_dir,
)
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.errors import (
    PersistenceOperationError,
    ResourceInUseError,
)
from backend.service.application.workflows.application_lifecycle import (
    WorkflowApplicationLifecycleService,
)
from backend.service.application.workflows.documents.storage import (
    build_application_directory_key,
    build_application_prompt_mask_root_key,
    build_template_version_directory_key,
    normalize_application_identifier,
)
from backend.service.application.workflows.lifecycle_resource_keys import (
    build_workflow_template_lifecycle_resource_key,
)
from backend.service.application.workflows.resource_deletion_staging import (
    finalize_staged_workflow_resource_storage,
    list_staged_workflow_resource_storage,
    restore_staged_workflow_resource_storage,
    stage_workflow_resource_storage,
)
from backend.service.application.workflows.workflow_service import (
    LocalWorkflowJsonService,
)
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowApplicationDeletionInventory,
    WorkflowApplicationLifecycle,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


_ACTIVE_PREVIEW_STATES = frozenset({"created", "running"})


@dataclass(frozen=True)
class WorkflowApplicationDeletionResult:
    """描述一次 Workflow Application 物理删除的实际范围。"""

    application_id: str
    deleted_preview_run_count: int
    deleted_workflow_run_count: int
    deleted_version_count: int
    deleted_template_version: bool


@dataclass(frozen=True)
class WorkflowApplicationDeletionRecoveryResult:
    """描述启动期 Application 删除暂存恢复结果。"""

    restored_deletions: int
    completed_cleanups: int


class WorkflowApplicationDeletionService:
    """同步删除 Application 文档、历史记录与独占 Template 版本。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        node_catalog_registry: NodeCatalogRegistry,
    ) -> None:
        """初始化删除服务。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.workflow_json_service = LocalWorkflowJsonService(
            dataset_storage=dataset_storage,
            node_catalog_registry=node_catalog_registry,
        )
        self.application_lifecycle = WorkflowApplicationLifecycleService(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
        )

    def delete(
        self,
        *,
        project_id: str,
        application_id: str,
    ) -> WorkflowApplicationDeletionResult:
        """在无 Runtime 且无活动 Preview 时物理删除整个 Workflow。"""

        normalized_application_id = normalize_application_identifier(
            application_id,
            "application_id",
        )
        application_claim = self.application_lifecycle.acquire(
            project_id=project_id,
            application_id=normalized_application_id,
            operation="deleting",
        )
        template_claim: WorkflowApplicationLifecycle | None = None
        staging = None
        database_committed = False
        try:
            application = self.workflow_json_service.get_application(
                project_id=project_id,
                application_id=normalized_application_id,
            ).application
            inventory = self._inspect(
                project_id=project_id,
                application_id=normalized_application_id,
            )
            self._require_deletable(inventory, application_id=normalized_application_id)

            delete_template_version = self._template_version_is_exclusive(
                project_id=project_id,
                application_id=normalized_application_id,
                template_id=application.template_ref.template_id,
                template_version=application.template_ref.template_version,
            )
            if delete_template_version:
                template_claim = self.application_lifecycle.acquire(
                    project_id=project_id,
                    application_id=build_workflow_template_lifecycle_resource_key(
                        template_id=application.template_ref.template_id,
                        template_version=application.template_ref.template_version,
                    ),
                    operation="deleting",
                    allow_deleted=True,
                )
                # Template claim 取得后重新确认，避免删除刚被其他 Workflow 引用的模板。
                delete_template_version = self._template_version_is_exclusive(
                    project_id=project_id,
                    application_id=normalized_application_id,
                    template_id=application.template_ref.template_id,
                    template_version=application.template_ref.template_version,
                )

            source_paths = [
                build_application_directory_key(
                    project_id=project_id,
                    application_id=normalized_application_id,
                ),
                build_application_prompt_mask_root_key(
                    project_id=project_id,
                    application_id=normalized_application_id,
                ),
                *(
                    build_workflow_preview_run_storage_dir(preview_run_id)
                    for preview_run_id, _state in inventory.preview_runs
                ),
                *(
                    build_workflow_run_storage_dir(workflow_run_id)
                    for workflow_run_id in inventory.workflow_run_ids
                ),
            ]
            if delete_template_version:
                source_paths.append(
                    build_template_version_directory_key(
                        project_id=project_id,
                        template_id=application.template_ref.template_id,
                        template_version=application.template_ref.template_version,
                    )
                )
            staging = stage_workflow_resource_storage(
                dataset_storage=self.dataset_storage,
                operation_id=str(application_claim.operation_id),
                resource_kind="workflow-application",
                resource_id=normalized_application_id,
                source_paths=tuple(source_paths),
                metadata={
                    "project_id": project_id,
                    "application_id": normalized_application_id,
                },
            )

            with self._open_unit_of_work() as unit_of_work:
                final_inventory = (
                    unit_of_work.workflow_runtime.inspect_workflow_application_deletion(
                        project_id,
                        normalized_application_id,
                    )
                )
                self._require_deletable(
                    final_inventory,
                    application_id=normalized_application_id,
                )
                deleted = unit_of_work.workflow_runtime.delete_claimed_workflow_application_records(
                    project_id=project_id,
                    application_id=normalized_application_id,
                    expected_generation=application_claim.generation,
                    operation_id=str(application_claim.operation_id),
                )
                if not deleted:
                    raise PersistenceOperationError(
                        "Workflow Application 删除 claim 已变化"
                    )
                unit_of_work.commit()
            database_committed = True
        except Exception:
            if staging is not None and not database_committed:
                restore_staged_workflow_resource_storage(
                    dataset_storage=self.dataset_storage,
                    staging=staging,
                )
            if not database_committed:
                try:
                    self._release_claim(application_claim)
                except Exception:  # noqa: BLE001 - 保留原始删除错误
                    pass
                if template_claim is not None:
                    try:
                        self._release_temporary_claim(template_claim)
                    except Exception:  # noqa: BLE001 - 启动恢复会释放残留 claim
                        pass
            raise

        if template_claim is not None:
            try:
                self._release_temporary_claim(template_claim)
            except Exception:  # noqa: BLE001 - 删除已提交，启动恢复会释放 claim
                pass
        if staging is not None:
            finalize_staged_workflow_resource_storage(
                dataset_storage=self.dataset_storage,
                staging=staging,
            )
        return WorkflowApplicationDeletionResult(
            application_id=normalized_application_id,
            deleted_preview_run_count=len(inventory.preview_runs),
            deleted_workflow_run_count=len(inventory.workflow_run_ids),
            deleted_version_count=len(inventory.workflow_app_version_ids),
            deleted_template_version=delete_template_version,
        )

    def recover_interrupted_deletions(
        self,
    ) -> WorkflowApplicationDeletionRecoveryResult:
        """启动期恢复未提交删除，并清理已经提交的暂存目录。"""

        restored = 0
        completed = 0
        for staging in list_staged_workflow_resource_storage(
            dataset_storage=self.dataset_storage,
            resource_kind="workflow-application",
        ):
            project_id = str(staging.metadata.get("project_id") or "").strip()
            application_id = str(
                staging.metadata.get("application_id") or staging.resource_id
            ).strip()
            if not project_id or not application_id:
                raise PersistenceOperationError(
                    "Workflow Application 删除暂存缺少资源归属"
                )
            with self._open_unit_of_work() as unit_of_work:
                lifecycle = (
                    unit_of_work.workflow_runtime.get_workflow_application_lifecycle(
                        project_id,
                        application_id,
                    )
                )
            if (
                lifecycle is not None
                and lifecycle.state == "deleting"
                and lifecycle.operation_id == staging.operation_id
            ):
                restore_staged_workflow_resource_storage(
                    dataset_storage=self.dataset_storage,
                    staging=staging,
                )
                self.application_lifecycle.complete(lifecycle, deleted=False)
                restored += 1
                continue
            pending = finalize_staged_workflow_resource_storage(
                dataset_storage=self.dataset_storage,
                staging=staging,
            )
            if pending is None:
                completed += 1
        return WorkflowApplicationDeletionRecoveryResult(
            restored_deletions=restored,
            completed_cleanups=completed,
        )

    def _inspect(
        self,
        *,
        project_id: str,
        application_id: str,
    ) -> WorkflowApplicationDeletionInventory:
        """读取删除清单并立即关闭只读事务。"""

        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.workflow_runtime.inspect_workflow_application_deletion(
                project_id,
                application_id,
            )

    @staticmethod
    def _require_deletable(
        inventory: WorkflowApplicationDeletionInventory,
        *,
        application_id: str,
    ) -> None:
        """拒绝仍有 Runtime 或活动 Preview 的 Workflow。"""

        if inventory.workflow_runtime_ids:
            raise ResourceInUseError(
                "Workflow 仍有 Runtime，删除 Runtime 后才能删除",
                details={
                    "application_id": application_id,
                    "workflow_runtime_ids": list(inventory.workflow_runtime_ids),
                },
            )
        active_previews = [
            {"preview_run_id": preview_run_id, "state": state}
            for preview_run_id, state in inventory.preview_runs
            if state in _ACTIVE_PREVIEW_STATES
        ]
        if active_previews:
            raise ResourceInUseError(
                "Workflow 仍有活动 Preview，执行结束后才能删除",
                details={
                    "application_id": application_id,
                    "preview_runs": active_previews,
                },
            )

    def _template_version_is_exclusive(
        self,
        *,
        project_id: str,
        application_id: str,
        template_id: str,
        template_version: str,
    ) -> bool:
        """判断目标 Template 版本是否只被当前 Workflow 引用。"""

        return all(
            item.application_id == application_id
            or item.template_id != template_id
            or item.template_version != template_version
            for item in self.workflow_json_service.list_applications(
                project_id=project_id
            )
        )

    def _release_claim(self, claim: WorkflowApplicationLifecycle) -> None:
        """释放失败的 Application 删除 claim，保留原 Workflow。"""

        self.application_lifecycle.complete(claim, deleted=False)

    def _release_temporary_claim(self, claim: WorkflowApplicationLifecycle) -> None:
        """释放并物理清理 Template 临时 claim。"""

        self.application_lifecycle.complete(claim, deleted=False)
        self.application_lifecycle.delete_idle_temporary_resource(claim)

    @contextmanager
    def _open_unit_of_work(self) -> Iterator[SqlAlchemyUnitOfWork]:
        """创建并关闭一个 Unit of Work。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            yield unit_of_work
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.close()
