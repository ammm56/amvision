"""workflow runtime 资源的 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.service.application.errors import PersistenceOperationError
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowApplicationLifecycle,
    WorkflowAppRuntime,
    WorkflowAppVersion,
    WorkflowExecutionPolicy,
    WorkflowPreviewRun,
    WorkflowRuntimeRevision,
    WorkflowRun,
)
from backend.service.infrastructure.persistence.workflow_runtime_orm import (
    WorkflowApplicationLifecycleRecord,
    WorkflowAppRuntimeRecord,
    WorkflowAppVersionRecord,
    WorkflowExecutionPolicyRecord,
    WorkflowPreviewRunRecord,
    WorkflowRuntimeRevisionRecord,
    WorkflowRunRecord,
)


class SqlAlchemyWorkflowRuntimeRepository:
    """使用 SQLAlchemy 持久化 workflow 版本、Application 和 runtime 状态。"""

    def __init__(self, session: Session) -> None:
        """初始化 workflow runtime 仓储。

        参数：
        - session：当前 Unit of Work 持有的 Session。
        """

        self.session = session

    def add_workflow_app_version(
        self,
        workflow_app_version: WorkflowAppVersion,
        *,
        reserve_content_fingerprint: bool = True,
    ) -> None:
        """新增版本；默认由数据库唯一键原子占用内容指纹。"""

        try:
            if (
                self.session.get(
                    WorkflowAppVersionRecord,
                    workflow_app_version.workflow_app_version_id,
                )
                is not None
            ):
                raise PersistenceOperationError(
                    "WorkflowAppVersion 已存在，不能覆盖",
                    details={
                        "workflow_app_version_id": workflow_app_version.workflow_app_version_id
                    },
                )
            self.session.add(
                self._app_version_to_record(
                    workflow_app_version,
                    reserve_content_fingerprint=reserve_content_fingerprint,
                )
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "新增 WorkflowAppVersion 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def update_workflow_app_version_state(
        self,
        workflow_app_version_id: str,
        *,
        state: str,
        completed_at: str | None,
        error: str | None,
    ) -> None:
        """只更新版本发布状态，保持发布内容不可变。"""

        try:
            record = self.session.get(WorkflowAppVersionRecord, workflow_app_version_id)
            if record is None:
                return
            record.state = state
            record.completed_at = completed_at
            record.error = error
            if state == "failed":
                # failed 版本不能永久阻塞相同内容的后续显式重试。
                record.content_deduplication_key = None
        except SQLAlchemyError as exc:
            raise PersistenceOperationError(
                "更新 WorkflowAppVersion 状态失败",
                details={"error_type": exc.__class__.__name__},
            ) from exc

    def compare_and_set_workflow_app_version_state(
        self,
        workflow_app_version_id: str,
        *,
        expected_state: str,
        target_state: str,
    ) -> bool:
        """按预期状态原子切换版本生命周期状态。"""

        try:
            result = self.session.execute(
                update(WorkflowAppVersionRecord)
                .where(
                    WorkflowAppVersionRecord.workflow_app_version_id
                    == workflow_app_version_id,
                    WorkflowAppVersionRecord.state == expected_state,
                )
                .values(state=target_state)
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "切换 WorkflowAppVersion 状态失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return bool(result.rowcount)

    def fence_published_workflow_app_version(
        self,
        workflow_app_version_id: str,
    ) -> bool:
        """条件更新 published 版本行，在当前事务内建立引用写 fence。"""

        try:
            result = self.session.execute(
                update(WorkflowAppVersionRecord)
                .where(
                    WorkflowAppVersionRecord.workflow_app_version_id
                    == workflow_app_version_id,
                    WorkflowAppVersionRecord.state == "published",
                )
                # 这是有意的 no-op UPDATE：数据库会为命中的版本行建立写入
                # 顺序，随后 Runtime/revision 写入与 archive CAS 不能交错越过。
                .values(state="published")
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "占用已发布 WorkflowAppVersion 引用 fence 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return bool(result.rowcount == 1)

    def add_workflow_application_lifecycle(
        self, lifecycle: WorkflowApplicationLifecycle
    ) -> None:
        """新增 lifecycle 行；复合主键负责跨进程并发仲裁。"""

        try:
            self.session.add(
                WorkflowApplicationLifecycleRecord(
                    project_id=lifecycle.project_id,
                    application_id=lifecycle.application_id,
                    state=lifecycle.state,
                    generation=lifecycle.generation,
                    operation_id=lifecycle.operation_id,
                    updated_at=lifecycle.updated_at,
                    deleted=lifecycle.deleted,
                )
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "新增 Workflow Application lifecycle 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_workflow_application_lifecycle(
        self, project_id: str, application_id: str
    ) -> WorkflowApplicationLifecycle | None:
        """读取 lifecycle 行。"""

        try:
            record = self.session.get(
                WorkflowApplicationLifecycleRecord,
                (project_id, application_id),
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 Workflow Application lifecycle 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return None if record is None else self._application_lifecycle_to_domain(record)

    def touch_workflow_project_lifecycle_sentinel(
        self,
        *,
        project_id: str,
        sentinel_resource_key: str,
        updated_at: str,
    ) -> bool:
        """在普通 mutation admission 中原子 touch Project sentinel。

        generation 使用数据库表达式自增，不依赖调用方预读值。并发普通
        mutation 只在这个短 UPDATE 上建立顺序，真实业务操作不持有行锁。
        """

        try:
            result = self.session.execute(
                update(WorkflowApplicationLifecycleRecord)
                .where(
                    WorkflowApplicationLifecycleRecord.project_id == project_id,
                    WorkflowApplicationLifecycleRecord.application_id
                    == sentinel_resource_key,
                    WorkflowApplicationLifecycleRecord.state == "idle",
                    WorkflowApplicationLifecycleRecord.operation_id.is_(None),
                    WorkflowApplicationLifecycleRecord.deleted.is_(False),
                )
                .values(
                    generation=WorkflowApplicationLifecycleRecord.generation + 1,
                    updated_at=updated_at,
                )
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "占用 Project mutation sentinel 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return bool(result.rowcount == 1)

    def try_claim_workflow_project_deletion_sentinel(
        self,
        *,
        project_id: str,
        sentinel_resource_key: str,
        operation_id: str,
        updated_at: str,
    ) -> bool:
        """原子把空闲 Project sentinel 切换为 deleting。"""

        try:
            result = self.session.execute(
                update(WorkflowApplicationLifecycleRecord)
                .where(
                    WorkflowApplicationLifecycleRecord.project_id == project_id,
                    WorkflowApplicationLifecycleRecord.application_id
                    == sentinel_resource_key,
                    WorkflowApplicationLifecycleRecord.state == "idle",
                    WorkflowApplicationLifecycleRecord.operation_id.is_(None),
                    WorkflowApplicationLifecycleRecord.deleted.is_(False),
                )
                .values(
                    state="deleting",
                    generation=WorkflowApplicationLifecycleRecord.generation + 1,
                    operation_id=operation_id,
                    updated_at=updated_at,
                )
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "占用 Project 删除 sentinel 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return bool(result.rowcount == 1)

    def touch_claimed_workflow_project_deletion_sentinel(
        self,
        *,
        project_id: str,
        sentinel_resource_key: str,
        expected_generation: int,
        operation_id: str,
        updated_at: str,
    ) -> bool:
        """在 Project 最终删除短事务开头确认并锁定 sentinel 所有权。"""

        try:
            result = self.session.execute(
                update(WorkflowApplicationLifecycleRecord)
                .where(
                    WorkflowApplicationLifecycleRecord.project_id == project_id,
                    WorkflowApplicationLifecycleRecord.application_id
                    == sentinel_resource_key,
                    WorkflowApplicationLifecycleRecord.state == "deleting",
                    WorkflowApplicationLifecycleRecord.generation
                    == expected_generation,
                    WorkflowApplicationLifecycleRecord.operation_id == operation_id,
                    WorkflowApplicationLifecycleRecord.deleted.is_(False),
                )
                .values(updated_at=updated_at)
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "确认 Project 删除 sentinel 所有权失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return bool(result.rowcount == 1)

    def list_claimed_workflow_project_resources(
        self,
        *,
        project_id: str,
        sentinel_resource_key: str,
    ) -> tuple[WorkflowApplicationLifecycle, ...]:
        """列出指定 Project 中除 sentinel 外尚未完成的 mutation claim。"""

        try:
            records = (
                self.session.execute(
                    select(WorkflowApplicationLifecycleRecord)
                    .where(
                        WorkflowApplicationLifecycleRecord.project_id == project_id,
                        WorkflowApplicationLifecycleRecord.application_id
                        != sentinel_resource_key,
                        WorkflowApplicationLifecycleRecord.state != "idle",
                    )
                    .order_by(
                        WorkflowApplicationLifecycleRecord.updated_at.asc(),
                        WorkflowApplicationLifecycleRecord.application_id.asc(),
                    )
                )
                .scalars()
                .all()
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 Project 活动 mutation claim 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._application_lifecycle_to_domain(item) for item in records)

    def try_claim_workflow_application_lifecycle(
        self,
        *,
        project_id: str,
        application_id: str,
        expected_generation: int,
        operation_state: str,
        operation_id: str,
        updated_at: str,
        allow_deleted: bool,
    ) -> bool:
        """用单条条件 UPDATE 占用 lifecycle，事务内不执行文件 I/O。"""

        conditions = [
            WorkflowApplicationLifecycleRecord.project_id == project_id,
            WorkflowApplicationLifecycleRecord.application_id == application_id,
            WorkflowApplicationLifecycleRecord.state == "idle",
            WorkflowApplicationLifecycleRecord.operation_id.is_(None),
            WorkflowApplicationLifecycleRecord.generation == expected_generation,
        ]
        if not allow_deleted:
            conditions.append(WorkflowApplicationLifecycleRecord.deleted.is_(False))
        try:
            result = self.session.execute(
                update(WorkflowApplicationLifecycleRecord)
                .where(*conditions)
                .values(
                    state=operation_state,
                    generation=expected_generation + 1,
                    operation_id=operation_id,
                    updated_at=updated_at,
                )
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "占用 Workflow Application lifecycle 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return bool(result.rowcount == 1)

    def complete_workflow_application_lifecycle(
        self,
        *,
        project_id: str,
        application_id: str,
        expected_generation: int,
        operation_state: str,
        operation_id: str,
        updated_at: str,
        deleted: bool,
    ) -> bool:
        """由当前 generation/operation 完成 lifecycle，拒绝过期写回。"""

        try:
            result = self.session.execute(
                update(WorkflowApplicationLifecycleRecord)
                .where(
                    WorkflowApplicationLifecycleRecord.project_id == project_id,
                    WorkflowApplicationLifecycleRecord.application_id == application_id,
                    WorkflowApplicationLifecycleRecord.state == operation_state,
                    WorkflowApplicationLifecycleRecord.generation
                    == expected_generation,
                    WorkflowApplicationLifecycleRecord.operation_id == operation_id,
                )
                .values(
                    state="idle",
                    operation_id=None,
                    updated_at=updated_at,
                    deleted=deleted,
                )
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "完成 Workflow Application lifecycle 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return bool(result.rowcount == 1)

    def delete_idle_workflow_application_lifecycle(
        self,
        *,
        project_id: str,
        application_id: str,
        expected_generation: int,
    ) -> bool:
        """以 idle/generation 条件删除一次性 lifecycle。"""

        try:
            result = self.session.execute(
                delete(WorkflowApplicationLifecycleRecord).where(
                    WorkflowApplicationLifecycleRecord.project_id == project_id,
                    WorkflowApplicationLifecycleRecord.application_id == application_id,
                    WorkflowApplicationLifecycleRecord.state == "idle",
                    WorkflowApplicationLifecycleRecord.operation_id.is_(None),
                    WorkflowApplicationLifecycleRecord.generation
                    == expected_generation,
                    WorkflowApplicationLifecycleRecord.deleted.is_(False),
                )
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "删除临时 Workflow Application lifecycle 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return bool(result.rowcount == 1)

    def list_claimed_workflow_application_lifecycles(
        self,
    ) -> tuple[WorkflowApplicationLifecycle, ...]:
        """列出所有非 idle lifecycle。"""

        try:
            records = (
                self.session.execute(
                    select(WorkflowApplicationLifecycleRecord)
                    .where(WorkflowApplicationLifecycleRecord.state != "idle")
                    .order_by(
                        WorkflowApplicationLifecycleRecord.updated_at.asc(),
                        WorkflowApplicationLifecycleRecord.project_id.asc(),
                        WorkflowApplicationLifecycleRecord.application_id.asc(),
                    )
                )
                .scalars()
                .all()
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出未完成 Workflow Application lifecycle 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._application_lifecycle_to_domain(item) for item in records)

    def get_workflow_app_version(
        self, workflow_app_version_id: str
    ) -> WorkflowAppVersion | None:
        """按 id 读取 WorkflowAppVersion。"""

        try:
            record = self.session.get(WorkflowAppVersionRecord, workflow_app_version_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 WorkflowAppVersion 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return None if record is None else self._app_version_to_domain(record)

    def list_workflow_app_versions(
        self,
        project_id: str,
        application_id: str,
        *,
        include_incomplete: bool = False,
    ) -> tuple[WorkflowAppVersion, ...]:
        """按 Application 列出发布版本。"""

        statement = select(WorkflowAppVersionRecord).where(
            WorkflowAppVersionRecord.project_id == project_id,
            WorkflowAppVersionRecord.application_id == application_id,
        )
        if not include_incomplete:
            statement = statement.where(
                WorkflowAppVersionRecord.state.in_(("published", "archived"))
            )
        statement = statement.order_by(
            WorkflowAppVersionRecord.version_number.desc(),
            WorkflowAppVersionRecord.workflow_app_version_id.desc(),
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 WorkflowAppVersion 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._app_version_to_domain(record) for record in records)

    def list_incomplete_workflow_app_versions(self) -> tuple[WorkflowAppVersion, ...]:
        """列出需要在启动阶段恢复或失败收敛的 publishing 版本。"""

        statement = (
            select(WorkflowAppVersionRecord)
            .where(WorkflowAppVersionRecord.state == "publishing")
            .order_by(
                WorkflowAppVersionRecord.created_at.asc(),
                WorkflowAppVersionRecord.workflow_app_version_id.asc(),
            )
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出未完成 WorkflowAppVersion 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._app_version_to_domain(record) for record in records)

    def get_latest_workflow_app_version_number(
        self, project_id: str, application_id: str
    ) -> int:
        """读取当前最大内部版本号。"""

        statement = select(func.max(WorkflowAppVersionRecord.version_number)).where(
            WorkflowAppVersionRecord.project_id == project_id,
            WorkflowAppVersionRecord.application_id == application_id,
        )
        try:
            value = self.session.execute(statement).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 WorkflowAppVersion 最大版本号失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return int(value or 0)

    def get_published_workflow_app_version_by_fingerprint(
        self,
        project_id: str,
        application_id: str,
        content_fingerprint: str,
    ) -> WorkflowAppVersion | None:
        """按内容指纹查找已发布版本。"""

        statement = (
            select(WorkflowAppVersionRecord)
            .where(
                WorkflowAppVersionRecord.project_id == project_id,
                WorkflowAppVersionRecord.application_id == application_id,
                WorkflowAppVersionRecord.content_fingerprint == content_fingerprint,
                WorkflowAppVersionRecord.state == "published",
            )
            .order_by(WorkflowAppVersionRecord.version_number.desc())
            .limit(1)
        )
        try:
            record = self.session.execute(statement).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "按指纹读取 WorkflowAppVersion 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return None if record is None else self._app_version_to_domain(record)

    def get_claimed_workflow_app_version_by_fingerprint(
        self,
        project_id: str,
        application_id: str,
        content_fingerprint: str,
    ) -> WorkflowAppVersion | None:
        """读取当前持有默认内容去重键的版本。"""

        statement = (
            select(WorkflowAppVersionRecord)
            .where(
                WorkflowAppVersionRecord.project_id == project_id,
                WorkflowAppVersionRecord.application_id == application_id,
                WorkflowAppVersionRecord.content_deduplication_key
                == content_fingerprint,
            )
            .order_by(WorkflowAppVersionRecord.version_number.desc())
            .limit(1)
        )
        try:
            record = self.session.execute(statement).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 WorkflowAppVersion 内容去重占位失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return None if record is None else self._app_version_to_domain(record)

    def add_workflow_runtime_revision(
        self, workflow_runtime_revision: WorkflowRuntimeRevision
    ) -> None:
        """新增不可变 Runtime revision。"""

        try:
            if (
                self.session.get(
                    WorkflowRuntimeRevisionRecord,
                    workflow_runtime_revision.workflow_runtime_revision_id,
                )
                is not None
            ):
                raise PersistenceOperationError(
                    "WorkflowRuntimeRevision 已存在，不能覆盖",
                    details={
                        "workflow_runtime_revision_id": (
                            workflow_runtime_revision.workflow_runtime_revision_id
                        )
                    },
                )
            self.session.add(self._revision_to_record(workflow_runtime_revision))
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "新增 WorkflowRuntimeRevision 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_workflow_runtime_revision(
        self, workflow_runtime_revision_id: str
    ) -> WorkflowRuntimeRevision | None:
        """按 id 读取 Runtime revision。"""

        try:
            record = self.session.get(
                WorkflowRuntimeRevisionRecord, workflow_runtime_revision_id
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 WorkflowRuntimeRevision 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return None if record is None else self._revision_to_domain(record)

    def update_workflow_runtime_revision_state(
        self,
        workflow_runtime_revision_id: str,
        *,
        state: str,
        activated_at: str | None,
        failed_at: str | None,
        error: str | None,
    ) -> None:
        """只更新 Runtime revision 生命周期状态。"""

        try:
            record = self.session.get(
                WorkflowRuntimeRevisionRecord, workflow_runtime_revision_id
            )
            if record is None:
                return
            record.state = state
            record.activated_at = activated_at
            record.failed_at = failed_at
            record.error = error
        except SQLAlchemyError as exc:
            raise PersistenceOperationError(
                "更新 WorkflowRuntimeRevision 状态失败",
                details={"error_type": exc.__class__.__name__},
            ) from exc

    def list_workflow_runtime_revisions(
        self, workflow_runtime_id: str
    ) -> tuple[WorkflowRuntimeRevision, ...]:
        """按 Runtime 列出 revision。"""

        statement = (
            select(WorkflowRuntimeRevisionRecord)
            .where(
                WorkflowRuntimeRevisionRecord.workflow_runtime_id == workflow_runtime_id
            )
            .order_by(WorkflowRuntimeRevisionRecord.generation.desc())
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 WorkflowRuntimeRevision 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._revision_to_domain(record) for record in records)

    def save_execution_policy(self, execution_policy: WorkflowExecutionPolicy) -> None:
        """保存一条 WorkflowExecutionPolicy。"""

        try:
            existing_record = self.session.get(
                WorkflowExecutionPolicyRecord, execution_policy.execution_policy_id
            )
            if existing_record is None:
                self.session.add(self._execution_policy_to_record(execution_policy))
                return

            existing_record.project_id = execution_policy.project_id
            existing_record.display_name = execution_policy.display_name
            existing_record.policy_kind = execution_policy.policy_kind
            existing_record.default_timeout_seconds = (
                execution_policy.default_timeout_seconds
            )
            existing_record.max_run_timeout_seconds = (
                execution_policy.max_run_timeout_seconds
            )
            existing_record.trace_level = execution_policy.trace_level
            existing_record.retain_node_records_enabled = (
                execution_policy.retain_node_records_enabled
            )
            existing_record.retain_trace_enabled = execution_policy.retain_trace_enabled
            existing_record.created_at = execution_policy.created_at
            existing_record.updated_at = execution_policy.updated_at
            existing_record.created_by = execution_policy.created_by
            existing_record.metadata_json = dict(execution_policy.metadata)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 WorkflowExecutionPolicy 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_execution_policy(
        self, execution_policy_id: str
    ) -> WorkflowExecutionPolicy | None:
        """按 id 读取一条 WorkflowExecutionPolicy。"""

        try:
            record = self.session.get(
                WorkflowExecutionPolicyRecord, execution_policy_id
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 WorkflowExecutionPolicy 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None
        return self._execution_policy_to_domain(record)

    def list_execution_policies(
        self, project_id: str
    ) -> tuple[WorkflowExecutionPolicy, ...]:
        """按 Project id 列出 WorkflowExecutionPolicy。"""

        statement = (
            select(WorkflowExecutionPolicyRecord)
            .where(WorkflowExecutionPolicyRecord.project_id == project_id)
            .order_by(
                WorkflowExecutionPolicyRecord.created_at.desc(),
                WorkflowExecutionPolicyRecord.execution_policy_id.desc(),
            )
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 WorkflowExecutionPolicy 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._execution_policy_to_domain(record) for record in records)

    def save_preview_run(self, preview_run: WorkflowPreviewRun) -> None:
        """保存一个 WorkflowPreviewRun。"""

        try:
            existing_record = self.session.get(
                WorkflowPreviewRunRecord, preview_run.preview_run_id
            )
            if existing_record is None:
                self.session.add(self._preview_to_record(preview_run))
                return

            existing_record.project_id = preview_run.project_id
            existing_record.application_id = preview_run.application_id
            existing_record.source_kind = preview_run.source_kind
            existing_record.application_snapshot_object_key = (
                preview_run.application_snapshot_object_key
            )
            existing_record.template_snapshot_object_key = (
                preview_run.template_snapshot_object_key
            )
            existing_record.state = preview_run.state
            existing_record.created_at = preview_run.created_at
            existing_record.started_at = preview_run.started_at
            existing_record.finished_at = preview_run.finished_at
            existing_record.created_by = preview_run.created_by
            existing_record.timeout_seconds = preview_run.timeout_seconds
            existing_record.outputs_json = dict(preview_run.outputs)
            existing_record.template_outputs_json = dict(preview_run.template_outputs)
            existing_record.node_records_json = [
                dict(item) for item in preview_run.node_records
            ]
            existing_record.error_message = preview_run.error_message
            existing_record.retention_until = preview_run.retention_until
            existing_record.metadata_json = dict(preview_run.metadata)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 WorkflowPreviewRun 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_preview_run(self, preview_run_id: str) -> WorkflowPreviewRun | None:
        """按 id 读取一个 WorkflowPreviewRun。"""

        try:
            record = self.session.get(WorkflowPreviewRunRecord, preview_run_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 WorkflowPreviewRun 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None
        return self._preview_to_domain(record)

    def list_preview_runs(self, project_id: str) -> tuple[WorkflowPreviewRun, ...]:
        """按 Project id 列出 WorkflowPreviewRun。

        参数：
        - project_id：所属 Project id。

        返回：
        - tuple[WorkflowPreviewRun, ...]：按创建时间倒序排列的 preview run 列表。
        """

        statement = (
            select(WorkflowPreviewRunRecord)
            .where(WorkflowPreviewRunRecord.project_id == project_id)
            .order_by(
                WorkflowPreviewRunRecord.created_at.desc(),
                WorkflowPreviewRunRecord.preview_run_id.desc(),
            )
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 WorkflowPreviewRun 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._preview_to_domain(record) for record in records)

    def count_preview_run_states_by_project(self, project_id: str) -> dict[str, int]:
        """按 Project id 聚合 WorkflowPreviewRun 状态数量。

        这个查询只读取 state 和 count，避免项目首页 summary 为了计数加载
        outputs_json、node_records_json 等大字段。
        """

        statement = (
            select(
                WorkflowPreviewRunRecord.state,
                func.count(WorkflowPreviewRunRecord.preview_run_id),
            )
            .where(WorkflowPreviewRunRecord.project_id == project_id)
            .group_by(WorkflowPreviewRunRecord.state)
        )
        try:
            rows = self.session.execute(statement).all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "聚合 WorkflowPreviewRun 状态失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return {str(state): int(count) for state, count in rows}

    def delete_preview_run(self, preview_run_id: str) -> None:
        """按 id 删除一个 WorkflowPreviewRun。

        参数：
        - preview_run_id：要删除的 preview run id。

        返回：
        - None。
        """

        try:
            record = self.session.get(WorkflowPreviewRunRecord, preview_run_id)
            if record is None:
                return
            self.session.delete(record)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "删除 WorkflowPreviewRun 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def list_expired_preview_runs(
        self,
        retention_until: str,
    ) -> tuple[WorkflowPreviewRun, ...]:
        """列出 retention_until 已到期的 preview run。"""

        statement = (
            select(WorkflowPreviewRunRecord)
            .where(
                WorkflowPreviewRunRecord.retention_until.is_not(None),
                WorkflowPreviewRunRecord.retention_until <= retention_until,
            )
            .order_by(
                WorkflowPreviewRunRecord.retention_until.asc(),
                WorkflowPreviewRunRecord.preview_run_id.asc(),
            )
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出已过期 WorkflowPreviewRun 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._preview_to_domain(record) for record in records)

    def save_workflow_app_runtime(
        self, workflow_app_runtime: WorkflowAppRuntime
    ) -> None:
        """创建一个 WorkflowAppRuntime；既有正式记录禁止整行覆盖。"""

        try:
            existing_record = self.session.get(
                WorkflowAppRuntimeRecord,
                workflow_app_runtime.workflow_runtime_id,
            )
            if existing_record is None:
                self.session.add(self._runtime_to_record(workflow_app_runtime))
                return
            raise PersistenceOperationError(
                "既有 WorkflowAppRuntime 不能使用整对象 save，必须使用字段级 CAS",
                details={
                    "workflow_runtime_id": workflow_app_runtime.workflow_runtime_id,
                },
            )
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 WorkflowAppRuntime 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_workflow_app_runtime(
        self, workflow_runtime_id: str
    ) -> WorkflowAppRuntime | None:
        """按 id 读取一个 WorkflowAppRuntime。"""

        try:
            record = self.session.get(WorkflowAppRuntimeRecord, workflow_runtime_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 WorkflowAppRuntime 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None
        return self._runtime_to_domain(record)

    def list_workflow_app_runtimes(
        self,
        project_id: str,
        *,
        application_id: str | None = None,
        application_ids: tuple[str, ...] | None = None,
    ) -> tuple[WorkflowAppRuntime, ...]:
        """按 Project id 和可选 Application 过滤条件列出 Runtime。"""

        statement = select(WorkflowAppRuntimeRecord).where(
            WorkflowAppRuntimeRecord.project_id == project_id
        )
        if application_id is not None:
            statement = statement.where(
                WorkflowAppRuntimeRecord.application_id == application_id
            )
        if application_ids is not None:
            statement = statement.where(
                WorkflowAppRuntimeRecord.application_id.in_(application_ids)
            )
        statement = statement.order_by(
            WorkflowAppRuntimeRecord.created_at.desc(),
            WorkflowAppRuntimeRecord.workflow_runtime_id.desc(),
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 WorkflowAppRuntime 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._runtime_to_domain(record) for record in records)

    def list_all_workflow_app_runtimes(self) -> tuple[WorkflowAppRuntime, ...]:
        """跨 Project 列出全部 Runtime，供一次性幂等迁移使用。"""

        statement = select(WorkflowAppRuntimeRecord).order_by(
            WorkflowAppRuntimeRecord.created_at.asc(),
            WorkflowAppRuntimeRecord.workflow_runtime_id.asc(),
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出全部 WorkflowAppRuntime 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._runtime_to_domain(record) for record in records)

    def replace_workflow_app_runtime_for_migration(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
    ) -> None:
        """仅供启动迁移完整替换一个既有 WorkflowAppRuntime。"""

        try:
            existing_record = self.session.get(
                WorkflowAppRuntimeRecord,
                workflow_app_runtime.workflow_runtime_id,
            )
            if existing_record is None:
                raise PersistenceOperationError(
                    "迁移目标 WorkflowAppRuntime 不存在",
                    details={
                        "workflow_runtime_id": (
                            workflow_app_runtime.workflow_runtime_id
                        ),
                    },
                )
            self._apply_runtime_record_values(existing_record, workflow_app_runtime)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "迁移替换 WorkflowAppRuntime 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    @staticmethod
    def _apply_runtime_record_values(
        existing_record: WorkflowAppRuntimeRecord,
        workflow_app_runtime: WorkflowAppRuntime,
    ) -> None:
        """把迁移后的完整 Runtime 值写入既有 ORM 记录。"""

        existing_record.project_id = workflow_app_runtime.project_id
        existing_record.application_id = workflow_app_runtime.application_id
        existing_record.display_name = workflow_app_runtime.display_name
        existing_record.application_snapshot_object_key = (
            workflow_app_runtime.application_snapshot_object_key
        )
        existing_record.template_snapshot_object_key = (
            workflow_app_runtime.template_snapshot_object_key
        )
        existing_record.execution_policy_snapshot_object_key = (
            workflow_app_runtime.execution_policy_snapshot_object_key
        )
        existing_record.active_revision_id = workflow_app_runtime.active_revision_id
        existing_record.desired_revision_id = workflow_app_runtime.desired_revision_id
        existing_record.revision_generation = workflow_app_runtime.revision_generation
        existing_record.desired_state = workflow_app_runtime.desired_state
        existing_record.observed_state = workflow_app_runtime.observed_state
        existing_record.request_timeout_seconds = (
            workflow_app_runtime.request_timeout_seconds
        )
        existing_record.heartbeat_interval_seconds = (
            workflow_app_runtime.heartbeat_interval_seconds
        )
        existing_record.heartbeat_timeout_seconds = (
            workflow_app_runtime.heartbeat_timeout_seconds
        )
        existing_record.created_at = workflow_app_runtime.created_at
        existing_record.updated_at = workflow_app_runtime.updated_at
        existing_record.created_by = workflow_app_runtime.created_by
        existing_record.last_started_at = workflow_app_runtime.last_started_at
        existing_record.last_stopped_at = workflow_app_runtime.last_stopped_at
        existing_record.heartbeat_at = workflow_app_runtime.heartbeat_at
        existing_record.worker_instance_id = workflow_app_runtime.worker_instance_id
        existing_record.worker_process_id = workflow_app_runtime.worker_process_id
        existing_record.loaded_snapshot_fingerprint = (
            workflow_app_runtime.loaded_snapshot_fingerprint
        )
        existing_record.last_error = workflow_app_runtime.last_error
        existing_record.health_summary_json = dict(workflow_app_runtime.health_summary)
        existing_record.metadata_json = dict(workflow_app_runtime.metadata)

    def list_workflow_app_runtimes_by_desired_state(
        self,
        desired_state: str,
    ) -> tuple[WorkflowAppRuntime, ...]:
        """跨 Project 列出指定期望状态的 WorkflowAppRuntime。"""

        statement = (
            select(WorkflowAppRuntimeRecord)
            .where(WorkflowAppRuntimeRecord.desired_state == desired_state)
            .order_by(
                WorkflowAppRuntimeRecord.updated_at.asc(),
                WorkflowAppRuntimeRecord.workflow_runtime_id.asc(),
            )
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "按期望状态列出 WorkflowAppRuntime 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._runtime_to_domain(record) for record in records)

    def compare_and_set_workflow_app_runtime_revision(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
        *,
        expected_generation: int,
    ) -> bool:
        """按 generation 与 stopped 状态原子更新 Runtime 版本指针。"""

        statement = (
            update(WorkflowAppRuntimeRecord)
            .where(
                WorkflowAppRuntimeRecord.workflow_runtime_id
                == workflow_app_runtime.workflow_runtime_id,
                WorkflowAppRuntimeRecord.revision_generation == expected_generation,
                WorkflowAppRuntimeRecord.desired_state == "stopped",
                WorkflowAppRuntimeRecord.observed_state == "stopped",
            )
            .values(
                application_snapshot_object_key=(
                    workflow_app_runtime.application_snapshot_object_key
                ),
                template_snapshot_object_key=(
                    workflow_app_runtime.template_snapshot_object_key
                ),
                desired_revision_id=workflow_app_runtime.desired_revision_id,
                revision_generation=workflow_app_runtime.revision_generation,
                updated_at=workflow_app_runtime.updated_at,
                worker_instance_id=None,
                worker_process_id=None,
                heartbeat_at=None,
                loaded_snapshot_fingerprint=None,
                last_error=None,
                health_summary_json={},
                metadata_json=dict(workflow_app_runtime.metadata),
            )
        )
        try:
            result = self.session.execute(statement)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "CAS 更新 WorkflowAppRuntime revision 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return bool(result.rowcount == 1)

    def update_workflow_app_runtime_state_if_current(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
        *,
        expected_generation: int,
        expected_revision_id: str | None,
        expected_worker_instance_id: str | None,
        expected_desired_state: str | None = None,
        expected_observed_state: str | None = None,
    ) -> bool:
        """按版本与 worker epoch fence 更新可变运行状态，不触碰版本指针。"""

        conditions = [
            WorkflowAppRuntimeRecord.workflow_runtime_id
            == workflow_app_runtime.workflow_runtime_id,
            WorkflowAppRuntimeRecord.revision_generation == expected_generation,
            WorkflowAppRuntimeRecord.desired_revision_id == expected_revision_id,
            WorkflowAppRuntimeRecord.worker_instance_id == expected_worker_instance_id,
        ]
        if expected_desired_state is not None:
            conditions.append(
                WorkflowAppRuntimeRecord.desired_state == expected_desired_state
            )
        if expected_observed_state is not None:
            conditions.append(
                WorkflowAppRuntimeRecord.observed_state == expected_observed_state
            )
        statement = (
            update(WorkflowAppRuntimeRecord)
            .where(*conditions)
            .values(**self._runtime_state_values(workflow_app_runtime))
        )
        try:
            result = self.session.execute(statement)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "CAS 更新 WorkflowAppRuntime 运行状态失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return bool(result.rowcount == 1)

    def activate_workflow_app_runtime_revision_if_current(
        self,
        workflow_app_runtime: WorkflowAppRuntime,
        *,
        expected_generation: int,
        expected_revision_id: str,
        expected_worker_instance_id: str | None,
    ) -> bool:
        """按目标版本和 worker epoch CAS 激活 revision。"""

        values = self._runtime_state_values(workflow_app_runtime)
        values["active_revision_id"] = workflow_app_runtime.active_revision_id
        statement = (
            update(WorkflowAppRuntimeRecord)
            .where(
                WorkflowAppRuntimeRecord.workflow_runtime_id
                == workflow_app_runtime.workflow_runtime_id,
                WorkflowAppRuntimeRecord.revision_generation == expected_generation,
                WorkflowAppRuntimeRecord.desired_revision_id == expected_revision_id,
                WorkflowAppRuntimeRecord.worker_instance_id
                == expected_worker_instance_id,
                WorkflowAppRuntimeRecord.desired_state == "running",
                WorkflowAppRuntimeRecord.observed_state == "starting",
            )
            .values(**values)
        )
        try:
            result = self.session.execute(statement)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "CAS 激活 WorkflowAppRuntime revision 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return bool(result.rowcount == 1)

    @staticmethod
    def _runtime_state_values(
        workflow_app_runtime: WorkflowAppRuntime,
    ) -> dict[str, object]:
        """构造不包含版本指针和 snapshot key 的运行状态更新字段。"""

        return {
            "desired_state": workflow_app_runtime.desired_state,
            "observed_state": workflow_app_runtime.observed_state,
            "updated_at": workflow_app_runtime.updated_at,
            "last_started_at": workflow_app_runtime.last_started_at,
            "last_stopped_at": workflow_app_runtime.last_stopped_at,
            "heartbeat_at": workflow_app_runtime.heartbeat_at,
            "worker_instance_id": workflow_app_runtime.worker_instance_id,
            "worker_process_id": workflow_app_runtime.worker_process_id,
            "loaded_snapshot_fingerprint": (
                workflow_app_runtime.loaded_snapshot_fingerprint
            ),
            "last_error": workflow_app_runtime.last_error,
            "health_summary_json": dict(workflow_app_runtime.health_summary),
            "metadata_json": dict(workflow_app_runtime.metadata),
        }

    def delete_workflow_app_runtime(self, workflow_runtime_id: str) -> None:
        """按 id 删除一个 WorkflowAppRuntime。"""

        try:
            record = self.session.get(WorkflowAppRuntimeRecord, workflow_runtime_id)
            if record is None:
                return
            self.session.delete(record)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "删除 WorkflowAppRuntime 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def save_workflow_run(self, workflow_run: WorkflowRun) -> None:
        """保存一个 WorkflowRun。"""

        try:
            existing_record = self.session.get(
                WorkflowRunRecord, workflow_run.workflow_run_id
            )
            if existing_record is None:
                self.session.add(self._run_to_record(workflow_run))
                return
            if existing_record.worker_instance_id != workflow_run.worker_instance_id:
                raise PersistenceOperationError(
                    "WorkflowRun worker epoch 来源不可变",
                    details={
                        "workflow_run_id": workflow_run.workflow_run_id,
                        "persisted_worker_instance_id": (
                            existing_record.worker_instance_id
                        ),
                        "requested_worker_instance_id": (
                            workflow_run.worker_instance_id
                        ),
                    },
                )

            existing_record.workflow_runtime_id = workflow_run.workflow_runtime_id
            existing_record.project_id = workflow_run.project_id
            existing_record.application_id = workflow_run.application_id
            existing_record.workflow_runtime_revision_id = (
                workflow_run.workflow_runtime_revision_id
            )
            existing_record.workflow_app_version_id = (
                workflow_run.workflow_app_version_id
            )
            existing_record.runtime_generation = workflow_run.runtime_generation
            existing_record.snapshot_fingerprint = workflow_run.snapshot_fingerprint
            existing_record.state = workflow_run.state
            existing_record.created_at = workflow_run.created_at
            existing_record.started_at = workflow_run.started_at
            existing_record.finished_at = workflow_run.finished_at
            existing_record.created_by = workflow_run.created_by
            existing_record.requested_timeout_seconds = (
                workflow_run.requested_timeout_seconds
            )
            existing_record.assigned_process_id = workflow_run.assigned_process_id
            existing_record.input_payload_json = dict(workflow_run.input_payload)
            existing_record.outputs_json = dict(workflow_run.outputs)
            existing_record.template_outputs_json = dict(workflow_run.template_outputs)
            existing_record.node_records_json = [
                dict(item) for item in workflow_run.node_records
            ]
            existing_record.error_message = workflow_run.error_message
            existing_record.metadata_json = dict(workflow_run.metadata)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 WorkflowRun 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_workflow_run(self, workflow_run_id: str) -> WorkflowRun | None:
        """按 id 读取一个 WorkflowRun。"""

        try:
            record = self.session.get(WorkflowRunRecord, workflow_run_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 WorkflowRun 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None
        return self._run_to_domain(record)

    def list_workflow_runs(self, project_id: str) -> tuple[WorkflowRun, ...]:
        """按 Project id 列出 WorkflowRun。"""

        statement = (
            select(WorkflowRunRecord)
            .where(WorkflowRunRecord.project_id == project_id)
            .order_by(
                WorkflowRunRecord.created_at.desc(),
                WorkflowRunRecord.workflow_run_id.desc(),
            )
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 WorkflowRun 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._run_to_domain(record) for record in records)

    def list_workflow_runs_by_runtime(
        self, workflow_runtime_id: str
    ) -> tuple[WorkflowRun, ...]:
        """按稳定 Runtime id 列出历史运行，供来源迁移使用。"""

        statement = (
            select(WorkflowRunRecord)
            .where(WorkflowRunRecord.workflow_runtime_id == workflow_runtime_id)
            .order_by(
                WorkflowRunRecord.created_at.asc(),
                WorkflowRunRecord.workflow_run_id.asc(),
            )
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "按 Runtime 列出 WorkflowRun 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._run_to_domain(record) for record in records)

    def count_workflow_run_states_by_project(self, project_id: str) -> dict[str, int]:
        """按 Project id 聚合 WorkflowRun 状态数量。

        这个查询只读取 state 和 count，避免 summary 路径加载每条 run 的
        input_payload_json、outputs_json 和 node_records_json。
        """

        statement = (
            select(
                WorkflowRunRecord.state, func.count(WorkflowRunRecord.workflow_run_id)
            )
            .where(WorkflowRunRecord.project_id == project_id)
            .group_by(WorkflowRunRecord.state)
        )
        try:
            rows = self.session.execute(statement).all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "聚合 WorkflowRun 状态失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return {str(state): int(count) for state, count in rows}

    def list_active_workflow_runs_for_runtime(
        self, workflow_runtime_id: str
    ) -> tuple[WorkflowRun, ...]:
        """列出 Runtime 当前未结束的正式运行。"""

        statement = (
            select(WorkflowRunRecord)
            .where(
                WorkflowRunRecord.workflow_runtime_id == workflow_runtime_id,
                WorkflowRunRecord.state.in_(("queued", "dispatching", "running")),
            )
            .order_by(WorkflowRunRecord.created_at.asc())
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 Runtime 活动 WorkflowRun 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._run_to_domain(record) for record in records)

    @staticmethod
    def _app_version_to_record(
        version: WorkflowAppVersion,
        *,
        reserve_content_fingerprint: bool = True,
    ) -> WorkflowAppVersionRecord:
        """把 WorkflowAppVersion 转换为 ORM 实体。"""

        return WorkflowAppVersionRecord(
            workflow_app_version_id=version.workflow_app_version_id,
            project_id=version.project_id,
            application_id=version.application_id,
            version_number=version.version_number,
            display_version=version.display_version,
            release_notes=version.release_notes,
            application_snapshot_object_key=version.application_snapshot_object_key,
            template_snapshot_object_key=version.template_snapshot_object_key,
            contract_snapshot_object_key=version.contract_snapshot_object_key,
            dependency_manifest_object_key=version.dependency_manifest_object_key,
            content_fingerprint=version.content_fingerprint,
            content_deduplication_key=(
                version.content_fingerprint if reserve_content_fingerprint else None
            ),
            contract_fingerprint=version.contract_fingerprint,
            state=version.state,
            created_at=version.created_at,
            created_by=version.created_by,
            completed_at=version.completed_at,
            error=version.error,
        )

    @staticmethod
    def _application_lifecycle_to_domain(
        record: WorkflowApplicationLifecycleRecord,
    ) -> WorkflowApplicationLifecycle:
        """把 Application lifecycle ORM 实体转换为领域对象。"""

        return WorkflowApplicationLifecycle(
            project_id=record.project_id,
            application_id=record.application_id,
            state=record.state,
            generation=record.generation,
            operation_id=record.operation_id,
            updated_at=record.updated_at,
            deleted=record.deleted,
        )

    @staticmethod
    def _app_version_to_domain(record: WorkflowAppVersionRecord) -> WorkflowAppVersion:
        """把 WorkflowAppVersion ORM 实体转换为领域对象。"""

        return WorkflowAppVersion(
            workflow_app_version_id=record.workflow_app_version_id,
            project_id=record.project_id,
            application_id=record.application_id,
            version_number=record.version_number,
            display_version=record.display_version,
            release_notes=record.release_notes,
            application_snapshot_object_key=record.application_snapshot_object_key,
            template_snapshot_object_key=record.template_snapshot_object_key,
            contract_snapshot_object_key=record.contract_snapshot_object_key,
            dependency_manifest_object_key=record.dependency_manifest_object_key,
            content_fingerprint=record.content_fingerprint,
            contract_fingerprint=record.contract_fingerprint,
            state=record.state,
            created_at=record.created_at,
            created_by=record.created_by,
            completed_at=record.completed_at,
            error=record.error,
        )

    @staticmethod
    def _revision_to_record(
        revision: WorkflowRuntimeRevision,
    ) -> WorkflowRuntimeRevisionRecord:
        """把 WorkflowRuntimeRevision 转换为 ORM 实体。"""

        return WorkflowRuntimeRevisionRecord(
            workflow_runtime_revision_id=revision.workflow_runtime_revision_id,
            workflow_runtime_id=revision.workflow_runtime_id,
            generation=revision.generation,
            workflow_app_version_id=revision.workflow_app_version_id,
            execution_policy_snapshot_object_key=(
                revision.execution_policy_snapshot_object_key
            ),
            expected_snapshot_fingerprint=revision.expected_snapshot_fingerprint,
            state=revision.state,
            created_at=revision.created_at,
            activated_at=revision.activated_at,
            failed_at=revision.failed_at,
            error=revision.error,
            created_by=revision.created_by,
        )

    @staticmethod
    def _revision_to_domain(
        record: WorkflowRuntimeRevisionRecord,
    ) -> WorkflowRuntimeRevision:
        """把 WorkflowRuntimeRevision ORM 实体转换为领域对象。"""

        return WorkflowRuntimeRevision(
            workflow_runtime_revision_id=record.workflow_runtime_revision_id,
            workflow_runtime_id=record.workflow_runtime_id,
            generation=record.generation,
            workflow_app_version_id=record.workflow_app_version_id,
            execution_policy_snapshot_object_key=(
                record.execution_policy_snapshot_object_key
            ),
            expected_snapshot_fingerprint=record.expected_snapshot_fingerprint,
            state=record.state,
            created_at=record.created_at,
            activated_at=record.activated_at,
            failed_at=record.failed_at,
            error=record.error,
            created_by=record.created_by,
        )

    @staticmethod
    def _preview_to_record(preview_run: WorkflowPreviewRun) -> WorkflowPreviewRunRecord:
        """把 WorkflowPreviewRun 转换为 ORM 实体。"""

        return WorkflowPreviewRunRecord(
            preview_run_id=preview_run.preview_run_id,
            project_id=preview_run.project_id,
            application_id=preview_run.application_id,
            source_kind=preview_run.source_kind,
            application_snapshot_object_key=preview_run.application_snapshot_object_key,
            template_snapshot_object_key=preview_run.template_snapshot_object_key,
            state=preview_run.state,
            created_at=preview_run.created_at,
            started_at=preview_run.started_at,
            finished_at=preview_run.finished_at,
            created_by=preview_run.created_by,
            timeout_seconds=preview_run.timeout_seconds,
            outputs_json=dict(preview_run.outputs),
            template_outputs_json=dict(preview_run.template_outputs),
            node_records_json=[dict(item) for item in preview_run.node_records],
            error_message=preview_run.error_message,
            retention_until=preview_run.retention_until,
            metadata_json=dict(preview_run.metadata),
        )

    @staticmethod
    def _preview_to_domain(record: WorkflowPreviewRunRecord) -> WorkflowPreviewRun:
        """把 WorkflowPreviewRun ORM 实体转换为领域对象。"""

        return WorkflowPreviewRun(
            preview_run_id=record.preview_run_id,
            project_id=record.project_id,
            application_id=record.application_id,
            source_kind=record.source_kind,
            application_snapshot_object_key=record.application_snapshot_object_key,
            template_snapshot_object_key=record.template_snapshot_object_key,
            state=record.state,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            created_by=record.created_by,
            timeout_seconds=record.timeout_seconds,
            outputs=dict(record.outputs_json or {}),
            template_outputs=dict(record.template_outputs_json or {}),
            node_records=tuple(dict(item) for item in (record.node_records_json or [])),
            error_message=record.error_message,
            retention_until=record.retention_until,
            metadata=dict(record.metadata_json or {}),
        )

    @staticmethod
    def _execution_policy_to_record(
        execution_policy: WorkflowExecutionPolicy,
    ) -> WorkflowExecutionPolicyRecord:
        """把 WorkflowExecutionPolicy 转换为 ORM 实体。"""

        return WorkflowExecutionPolicyRecord(
            execution_policy_id=execution_policy.execution_policy_id,
            project_id=execution_policy.project_id,
            display_name=execution_policy.display_name,
            policy_kind=execution_policy.policy_kind,
            default_timeout_seconds=execution_policy.default_timeout_seconds,
            max_run_timeout_seconds=execution_policy.max_run_timeout_seconds,
            trace_level=execution_policy.trace_level,
            retain_node_records_enabled=execution_policy.retain_node_records_enabled,
            retain_trace_enabled=execution_policy.retain_trace_enabled,
            created_at=execution_policy.created_at,
            updated_at=execution_policy.updated_at,
            created_by=execution_policy.created_by,
            metadata_json=dict(execution_policy.metadata),
        )

    @staticmethod
    def _execution_policy_to_domain(
        record: WorkflowExecutionPolicyRecord,
    ) -> WorkflowExecutionPolicy:
        """把 WorkflowExecutionPolicy ORM 实体转换为领域对象。"""

        return WorkflowExecutionPolicy(
            execution_policy_id=record.execution_policy_id,
            project_id=record.project_id,
            display_name=record.display_name,
            policy_kind=record.policy_kind,
            default_timeout_seconds=record.default_timeout_seconds,
            max_run_timeout_seconds=record.max_run_timeout_seconds,
            trace_level=record.trace_level,
            retain_node_records_enabled=record.retain_node_records_enabled,
            retain_trace_enabled=record.retain_trace_enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
            created_by=record.created_by,
            metadata=dict(record.metadata_json or {}),
        )

    @staticmethod
    def _runtime_to_record(
        workflow_app_runtime: WorkflowAppRuntime,
    ) -> WorkflowAppRuntimeRecord:
        """把 WorkflowAppRuntime 转换为 ORM 实体。"""

        return WorkflowAppRuntimeRecord(
            workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
            project_id=workflow_app_runtime.project_id,
            application_id=workflow_app_runtime.application_id,
            display_name=workflow_app_runtime.display_name,
            application_snapshot_object_key=workflow_app_runtime.application_snapshot_object_key,
            template_snapshot_object_key=workflow_app_runtime.template_snapshot_object_key,
            execution_policy_snapshot_object_key=workflow_app_runtime.execution_policy_snapshot_object_key,
            active_revision_id=workflow_app_runtime.active_revision_id,
            desired_revision_id=workflow_app_runtime.desired_revision_id,
            revision_generation=workflow_app_runtime.revision_generation,
            desired_state=workflow_app_runtime.desired_state,
            observed_state=workflow_app_runtime.observed_state,
            request_timeout_seconds=workflow_app_runtime.request_timeout_seconds,
            heartbeat_interval_seconds=workflow_app_runtime.heartbeat_interval_seconds,
            heartbeat_timeout_seconds=workflow_app_runtime.heartbeat_timeout_seconds,
            created_at=workflow_app_runtime.created_at,
            updated_at=workflow_app_runtime.updated_at,
            created_by=workflow_app_runtime.created_by,
            last_started_at=workflow_app_runtime.last_started_at,
            last_stopped_at=workflow_app_runtime.last_stopped_at,
            heartbeat_at=workflow_app_runtime.heartbeat_at,
            worker_instance_id=workflow_app_runtime.worker_instance_id,
            worker_process_id=workflow_app_runtime.worker_process_id,
            loaded_snapshot_fingerprint=workflow_app_runtime.loaded_snapshot_fingerprint,
            last_error=workflow_app_runtime.last_error,
            health_summary_json=dict(workflow_app_runtime.health_summary),
            metadata_json=dict(workflow_app_runtime.metadata),
        )

    @staticmethod
    def _runtime_to_domain(record: WorkflowAppRuntimeRecord) -> WorkflowAppRuntime:
        """把 WorkflowAppRuntime ORM 实体转换为领域对象。"""

        return WorkflowAppRuntime(
            workflow_runtime_id=record.workflow_runtime_id,
            project_id=record.project_id,
            application_id=record.application_id,
            display_name=record.display_name,
            application_snapshot_object_key=record.application_snapshot_object_key,
            template_snapshot_object_key=record.template_snapshot_object_key,
            execution_policy_snapshot_object_key=record.execution_policy_snapshot_object_key,
            active_revision_id=record.active_revision_id,
            desired_revision_id=record.desired_revision_id,
            revision_generation=record.revision_generation,
            desired_state=record.desired_state,
            observed_state=record.observed_state,
            request_timeout_seconds=record.request_timeout_seconds,
            heartbeat_interval_seconds=record.heartbeat_interval_seconds,
            heartbeat_timeout_seconds=record.heartbeat_timeout_seconds,
            created_at=record.created_at,
            updated_at=record.updated_at,
            created_by=record.created_by,
            last_started_at=record.last_started_at,
            last_stopped_at=record.last_stopped_at,
            heartbeat_at=record.heartbeat_at,
            worker_instance_id=record.worker_instance_id,
            worker_process_id=record.worker_process_id,
            loaded_snapshot_fingerprint=record.loaded_snapshot_fingerprint,
            last_error=record.last_error,
            health_summary=dict(record.health_summary_json or {}),
            metadata=dict(record.metadata_json or {}),
        )

    @staticmethod
    def _run_to_record(workflow_run: WorkflowRun) -> WorkflowRunRecord:
        """把 WorkflowRun 转换为 ORM 实体。"""

        return WorkflowRunRecord(
            workflow_run_id=workflow_run.workflow_run_id,
            workflow_runtime_id=workflow_run.workflow_runtime_id,
            project_id=workflow_run.project_id,
            application_id=workflow_run.application_id,
            workflow_runtime_revision_id=workflow_run.workflow_runtime_revision_id,
            workflow_app_version_id=workflow_run.workflow_app_version_id,
            runtime_generation=workflow_run.runtime_generation,
            snapshot_fingerprint=workflow_run.snapshot_fingerprint,
            worker_instance_id=workflow_run.worker_instance_id,
            state=workflow_run.state,
            created_at=workflow_run.created_at,
            started_at=workflow_run.started_at,
            finished_at=workflow_run.finished_at,
            created_by=workflow_run.created_by,
            requested_timeout_seconds=workflow_run.requested_timeout_seconds,
            assigned_process_id=workflow_run.assigned_process_id,
            input_payload_json=dict(workflow_run.input_payload),
            outputs_json=dict(workflow_run.outputs),
            template_outputs_json=dict(workflow_run.template_outputs),
            node_records_json=[dict(item) for item in workflow_run.node_records],
            error_message=workflow_run.error_message,
            metadata_json=dict(workflow_run.metadata),
        )

    @staticmethod
    def _run_to_domain(record: WorkflowRunRecord) -> WorkflowRun:
        """把 WorkflowRun ORM 实体转换为领域对象。"""

        return WorkflowRun(
            workflow_run_id=record.workflow_run_id,
            workflow_runtime_id=record.workflow_runtime_id,
            project_id=record.project_id,
            application_id=record.application_id,
            workflow_runtime_revision_id=record.workflow_runtime_revision_id,
            workflow_app_version_id=record.workflow_app_version_id,
            runtime_generation=record.runtime_generation,
            snapshot_fingerprint=record.snapshot_fingerprint,
            worker_instance_id=record.worker_instance_id,
            state=record.state,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            created_by=record.created_by,
            requested_timeout_seconds=record.requested_timeout_seconds,
            assigned_process_id=record.assigned_process_id,
            input_payload=dict(record.input_payload_json or {}),
            outputs=dict(record.outputs_json or {}),
            template_outputs=dict(record.template_outputs_json or {}),
            node_records=tuple(dict(item) for item in (record.node_records_json or [])),
            error_message=record.error_message,
            metadata=dict(record.metadata_json or {}),
        )
