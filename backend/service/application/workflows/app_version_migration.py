"""旧 WorkflowAppRuntime 快照到不可变版本模型的幂等迁移。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import logging
from typing import Iterator

from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.workflows.app_version_service import (
    WorkflowAppVersionService,
)
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntime,
    WorkflowRuntimeRevision,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkflowAppVersionMigrationResult:
    """描述一次启动期旧 Runtime 迁移结果。"""

    scanned_runtimes: int
    migrated_runtimes: int
    migrated_runs: int
    skipped_runtimes: int
    failed_runtime_ids: tuple[str, ...]


class WorkflowAppVersionMigrationService:
    """把历史 Runtime 自有快照转换为 version + revision 资源。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        dataset_storage: LocalDatasetStorage,
        node_catalog_registry: NodeCatalogRegistry,
    ) -> None:
        """初始化迁移服务。"""

        self.session_factory = session_factory
        self.dataset_storage = dataset_storage
        self.version_service = WorkflowAppVersionService(
            session_factory=session_factory,
            dataset_storage=dataset_storage,
            node_catalog_registry=node_catalog_registry,
        )

    def migrate(self) -> WorkflowAppVersionMigrationResult:
        """幂等迁移全部 generation=0 的历史 Runtime。"""

        with self._open_unit_of_work() as unit_of_work:
            runtimes = unit_of_work.workflow_runtime.list_all_workflow_app_runtimes()
        migrated_runtimes = 0
        migrated_runs = 0
        skipped_runtimes = 0
        failed_runtime_ids: list[str] = []
        for workflow_app_runtime in runtimes:
            if self._is_migrated(workflow_app_runtime):
                skipped_runtimes += 1
                continue
            try:
                migrated_runs += self._migrate_runtime(workflow_app_runtime)
                migrated_runtimes += 1
            except Exception as error:  # noqa: BLE001 - 单个旧 Runtime 不能阻断服务启动
                failed_runtime_ids.append(workflow_app_runtime.workflow_runtime_id)
                LOGGER.exception(
                    "迁移旧 WorkflowAppRuntime 版本来源失败: %s",
                    workflow_app_runtime.workflow_runtime_id,
                )
                self._mark_migration_failed(workflow_app_runtime, error)
        return WorkflowAppVersionMigrationResult(
            scanned_runtimes=len(runtimes),
            migrated_runtimes=migrated_runtimes,
            migrated_runs=migrated_runs,
            skipped_runtimes=skipped_runtimes,
            failed_runtime_ids=tuple(failed_runtime_ids),
        )

    def normalize_interrupted_staged_starts(self) -> int:
        """把服务重启前未完成激活的 staged start 收敛为显式可重试状态。"""

        with self._open_unit_of_work() as unit_of_work:
            runtimes = (
                unit_of_work.workflow_runtime.list_workflow_app_runtimes_by_desired_state(
                    "running"
                )
            )
        normalized_count = 0
        for workflow_app_runtime in runtimes:
            if workflow_app_runtime.desired_revision_id is None:
                continue
            with self._open_unit_of_work() as unit_of_work:
                current = unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_app_runtime.workflow_runtime_id
                )
                if current is None or current.desired_state != "running":
                    continue
                revision = unit_of_work.workflow_runtime.get_workflow_runtime_revision(
                    current.desired_revision_id or ""
                )
                if (
                    revision is not None
                    and revision.state == "active"
                    and current.active_revision_id
                    == revision.workflow_runtime_revision_id
                    and current.revision_generation == revision.generation
                ):
                    continue
                unit_of_work.workflow_runtime.replace_workflow_app_runtime_for_migration(
                    replace(
                        current,
                        desired_state="stopped",
                        observed_state="failed",
                        updated_at=_now_isoformat(),
                        worker_process_id=None,
                        loaded_snapshot_fingerprint=None,
                        last_error=(
                            "服务重启前的目标 revision 启动未完成，"
                            "已停止自动恢复，请显式重新启动"
                        ),
                    )
                )
                unit_of_work.commit()
            normalized_count += 1
        return normalized_count

    @staticmethod
    def _is_migrated(workflow_app_runtime: WorkflowAppRuntime) -> bool:
        """判断 Runtime 是否已经进入新的 generation 状态机。"""

        # generation 1 的新 Runtime 在首次 start 前允许 active 为空；选版失败后
        # active/desired 也可能不同。迁移只能接管 generation=0 的历史记录，不能
        # 把这些合法中间态误判成旧数据并覆盖。
        return workflow_app_runtime.revision_generation > 0

    def _migrate_runtime(self, workflow_app_runtime: WorkflowAppRuntime) -> int:
        """迁移一条 Runtime，并回填可确定来源的全部历史运行。"""

        app_version = self.version_service.import_runtime_snapshot_version(
            project_id=workflow_app_runtime.project_id,
            application_id=workflow_app_runtime.application_id,
            application_snapshot_object_key=(
                workflow_app_runtime.application_snapshot_object_key
            ),
            template_snapshot_object_key=(
                workflow_app_runtime.template_snapshot_object_key
            ),
            created_by=workflow_app_runtime.created_by,
        )
        expected_fingerprint = app_version.content_fingerprint
        now = _now_isoformat()
        with self._open_unit_of_work() as unit_of_work:
            historical_run_snapshot = (
                unit_of_work.workflow_runtime.list_workflow_runs_by_runtime(
                    workflow_app_runtime.workflow_runtime_id
                )
            )
        was_activated = bool(
            workflow_app_runtime.last_started_at
            or workflow_app_runtime.loaded_snapshot_fingerprint
            or workflow_app_runtime.observed_state == "running"
            or historical_run_snapshot
        )
        known_activated_at = workflow_app_runtime.last_started_at or next(
            (
                workflow_run.started_at or workflow_run.created_at
                for workflow_run in historical_run_snapshot
                if workflow_run.started_at or workflow_run.created_at
            ),
            None,
        )
        revision_id = _build_migrated_revision_id(
            workflow_app_runtime.workflow_runtime_id
        )
        revision = WorkflowRuntimeRevision(
            workflow_runtime_revision_id=revision_id,
            workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
            generation=1,
            workflow_app_version_id=app_version.workflow_app_version_id,
            execution_policy_snapshot_object_key=(
                workflow_app_runtime.execution_policy_snapshot_object_key
            ),
            expected_snapshot_fingerprint=expected_fingerprint,
            state="active" if was_activated else "staged",
            created_at=workflow_app_runtime.created_at or now,
            activated_at=known_activated_at if was_activated else None,
            created_by=workflow_app_runtime.created_by,
        )
        migrated_runtime = replace(
            workflow_app_runtime,
            application_snapshot_object_key=(
                app_version.application_snapshot_object_key
            ),
            template_snapshot_object_key=app_version.template_snapshot_object_key,
            active_revision_id=revision_id if was_activated else None,
            desired_revision_id=revision_id,
            revision_generation=1,
            updated_at=now,
            worker_process_id=None,
            loaded_snapshot_fingerprint=None,
            metadata={
                **dict(workflow_app_runtime.metadata),
                "workflow_app_version_id": app_version.workflow_app_version_id,
                "contract_snapshot_object_key": (
                    app_version.contract_snapshot_object_key
                ),
                "dependency_manifest_object_key": (
                    app_version.dependency_manifest_object_key
                ),
                "legacy_runtime_snapshot_migrated": True,
                "legacy_application_snapshot_object_key": (
                    workflow_app_runtime.application_snapshot_object_key
                ),
                "legacy_template_snapshot_object_key": (
                    workflow_app_runtime.template_snapshot_object_key
                ),
            },
        )
        with self._open_unit_of_work() as unit_of_work:
            current = unit_of_work.workflow_runtime.get_workflow_app_runtime(
                workflow_app_runtime.workflow_runtime_id
            )
            if current is None:
                return 0
            if self._is_migrated(current):
                return 0
            existing_revision = (
                unit_of_work.workflow_runtime.get_workflow_runtime_revision(
                    revision_id
                )
            )
            if existing_revision is None:
                unit_of_work.workflow_runtime.add_workflow_runtime_revision(revision)
            historical_runs = (
                unit_of_work.workflow_runtime.list_workflow_runs_by_runtime(
                    workflow_app_runtime.workflow_runtime_id
                )
            )
            backfilled_run_count = 0
            for workflow_run in historical_runs:
                if workflow_run.workflow_runtime_revision_id is not None:
                    continue
                unit_of_work.workflow_runtime.save_workflow_run(
                    replace(
                        workflow_run,
                        workflow_runtime_revision_id=revision_id,
                        workflow_app_version_id=app_version.workflow_app_version_id,
                        runtime_generation=1,
                        snapshot_fingerprint=expected_fingerprint,
                        metadata={
                            **dict(workflow_run.metadata),
                            "legacy_snapshot_source_migrated": True,
                        },
                    )
                )
                backfilled_run_count += 1
            unit_of_work.workflow_runtime.replace_workflow_app_runtime_for_migration(
                migrated_runtime
            )
            unit_of_work.commit()
        return backfilled_run_count

    def _mark_migration_failed(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
        error: Exception,
    ) -> None:
        """阻止迁移失败的历史 Runtime 被后台恢复为可调用状态。"""

        failed_runtime = replace(
            workflow_app_runtime,
            desired_state="stopped",
            observed_state="failed",
            updated_at=_now_isoformat(),
            worker_process_id=None,
            loaded_snapshot_fingerprint=None,
            last_error=f"Workflow App 版本迁移失败: {error}"[:2048],
            metadata={
                **dict(workflow_app_runtime.metadata),
                "workflow_app_version_migration_failed": True,
            },
        )
        try:
            with self._open_unit_of_work() as unit_of_work:
                current = unit_of_work.workflow_runtime.get_workflow_app_runtime(
                    workflow_app_runtime.workflow_runtime_id
                )
                if current is None or self._is_migrated(current):
                    return
                unit_of_work.workflow_runtime.replace_workflow_app_runtime_for_migration(
                    failed_runtime
                )
                unit_of_work.commit()
        except Exception:  # noqa: BLE001 - 保留原始迁移错误，避免二次错误终止启动
            LOGGER.exception(
                "记录 WorkflowAppRuntime 版本迁移失败状态时发生异常: %s",
                workflow_app_runtime.workflow_runtime_id,
            )

    @contextmanager
    def _open_unit_of_work(self) -> Iterator[SqlAlchemyUnitOfWork]:
        """打开一次短事务。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            yield unit_of_work
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.close()


def _build_migrated_revision_id(workflow_runtime_id: str) -> str:
    """从稳定 Runtime id 生成确定性的迁移 revision id。"""

    digest = hashlib.sha256(workflow_runtime_id.encode("utf-8")).hexdigest()[:32]
    return f"workflow-runtime-revision-migrated-{digest}"


def _now_isoformat() -> str:
    """返回 UTC ISO-8601 时间。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
