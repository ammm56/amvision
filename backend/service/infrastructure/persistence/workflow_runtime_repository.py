"""workflow runtime 资源的 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.service.application.errors import PersistenceOperationError
from backend.service.domain.workflows.workflow_runtime_records import (
    WorkflowAppRuntime,
    WorkflowExecutionPolicy,
    WorkflowPreviewRun,
    WorkflowRun,
)
from backend.service.infrastructure.persistence.workflow_runtime_orm import (
    WorkflowAppRuntimeRecord,
    WorkflowExecutionPolicyRecord,
    WorkflowPreviewRunRecord,
    WorkflowRunRecord,
)


class SqlAlchemyWorkflowRuntimeRepository:
    """使用 SQLAlchemy 持久化 workflow runtime 三类资源。"""

    def __init__(self, session: Session) -> None:
        """初始化 workflow runtime 仓储。

        参数：
        - session：当前 Unit of Work 持有的 Session。
        """

        self.session = session

    def save_execution_policy(self, execution_policy: WorkflowExecutionPolicy) -> None:
        """保存一条 WorkflowExecutionPolicy。"""

        try:
            existing_record = self.session.get(WorkflowExecutionPolicyRecord, execution_policy.execution_policy_id)
            if existing_record is None:
                self.session.add(self._execution_policy_to_record(execution_policy))
                return

            existing_record.project_id = execution_policy.project_id
            existing_record.display_name = execution_policy.display_name
            existing_record.policy_kind = execution_policy.policy_kind
            existing_record.default_timeout_seconds = execution_policy.default_timeout_seconds
            existing_record.max_run_timeout_seconds = execution_policy.max_run_timeout_seconds
            existing_record.trace_level = execution_policy.trace_level
            existing_record.retain_node_records_enabled = execution_policy.retain_node_records_enabled
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

    def get_execution_policy(self, execution_policy_id: str) -> WorkflowExecutionPolicy | None:
        """按 id 读取一条 WorkflowExecutionPolicy。"""

        try:
            record = self.session.get(WorkflowExecutionPolicyRecord, execution_policy_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 WorkflowExecutionPolicy 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None
        return self._execution_policy_to_domain(record)

    def list_execution_policies(self, project_id: str) -> tuple[WorkflowExecutionPolicy, ...]:
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
            existing_record = self.session.get(WorkflowPreviewRunRecord, preview_run.preview_run_id)
            if existing_record is None:
                self.session.add(self._preview_to_record(preview_run))
                return

            existing_record.project_id = preview_run.project_id
            existing_record.application_id = preview_run.application_id
            existing_record.source_kind = preview_run.source_kind
            existing_record.application_snapshot_object_key = preview_run.application_snapshot_object_key
            existing_record.template_snapshot_object_key = preview_run.template_snapshot_object_key
            existing_record.state = preview_run.state
            existing_record.created_at = preview_run.created_at
            existing_record.started_at = preview_run.started_at
            existing_record.finished_at = preview_run.finished_at
            existing_record.created_by = preview_run.created_by
            existing_record.timeout_seconds = preview_run.timeout_seconds
            existing_record.outputs_json = dict(preview_run.outputs)
            existing_record.template_outputs_json = dict(preview_run.template_outputs)
            existing_record.node_records_json = [dict(item) for item in preview_run.node_records]
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

    def save_workflow_app_runtime(self, workflow_app_runtime: WorkflowAppRuntime) -> None:
        """保存一个 WorkflowAppRuntime。"""

        try:
            existing_record = self.session.get(
                WorkflowAppRuntimeRecord,
                workflow_app_runtime.workflow_runtime_id,
            )
            if existing_record is None:
                self.session.add(self._runtime_to_record(workflow_app_runtime))
                return

            existing_record.project_id = workflow_app_runtime.project_id
            existing_record.application_id = workflow_app_runtime.application_id
            existing_record.display_name = workflow_app_runtime.display_name
            existing_record.application_snapshot_object_key = workflow_app_runtime.application_snapshot_object_key
            existing_record.template_snapshot_object_key = workflow_app_runtime.template_snapshot_object_key
            existing_record.execution_policy_snapshot_object_key = workflow_app_runtime.execution_policy_snapshot_object_key
            existing_record.desired_state = workflow_app_runtime.desired_state
            existing_record.observed_state = workflow_app_runtime.observed_state
            existing_record.request_timeout_seconds = workflow_app_runtime.request_timeout_seconds
            existing_record.heartbeat_interval_seconds = workflow_app_runtime.heartbeat_interval_seconds
            existing_record.heartbeat_timeout_seconds = workflow_app_runtime.heartbeat_timeout_seconds
            existing_record.created_at = workflow_app_runtime.created_at
            existing_record.updated_at = workflow_app_runtime.updated_at
            existing_record.created_by = workflow_app_runtime.created_by
            existing_record.last_started_at = workflow_app_runtime.last_started_at
            existing_record.last_stopped_at = workflow_app_runtime.last_stopped_at
            existing_record.heartbeat_at = workflow_app_runtime.heartbeat_at
            existing_record.worker_process_id = workflow_app_runtime.worker_process_id
            existing_record.loaded_snapshot_fingerprint = workflow_app_runtime.loaded_snapshot_fingerprint
            existing_record.last_error = workflow_app_runtime.last_error
            existing_record.health_summary_json = dict(workflow_app_runtime.health_summary)
            existing_record.metadata_json = dict(workflow_app_runtime.metadata)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 WorkflowAppRuntime 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_workflow_app_runtime(self, workflow_runtime_id: str) -> WorkflowAppRuntime | None:
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

    def list_workflow_app_runtimes(self, project_id: str) -> tuple[WorkflowAppRuntime, ...]:
        """按 Project id 列出 WorkflowAppRuntime。"""

        statement = (
            select(WorkflowAppRuntimeRecord)
            .where(WorkflowAppRuntimeRecord.project_id == project_id)
            .order_by(
                WorkflowAppRuntimeRecord.created_at.desc(),
                WorkflowAppRuntimeRecord.workflow_runtime_id.desc(),
            )
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 WorkflowAppRuntime 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._runtime_to_domain(record) for record in records)

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
            existing_record = self.session.get(WorkflowRunRecord, workflow_run.workflow_run_id)
            if existing_record is None:
                self.session.add(self._run_to_record(workflow_run))
                return

            existing_record.workflow_runtime_id = workflow_run.workflow_runtime_id
            existing_record.project_id = workflow_run.project_id
            existing_record.application_id = workflow_run.application_id
            existing_record.state = workflow_run.state
            existing_record.created_at = workflow_run.created_at
            existing_record.started_at = workflow_run.started_at
            existing_record.finished_at = workflow_run.finished_at
            existing_record.created_by = workflow_run.created_by
            existing_record.requested_timeout_seconds = workflow_run.requested_timeout_seconds
            existing_record.assigned_process_id = workflow_run.assigned_process_id
            existing_record.input_payload_json = dict(workflow_run.input_payload)
            existing_record.outputs_json = dict(workflow_run.outputs)
            existing_record.template_outputs_json = dict(workflow_run.template_outputs)
            existing_record.node_records_json = [dict(item) for item in workflow_run.node_records]
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
    def _execution_policy_to_record(execution_policy: WorkflowExecutionPolicy) -> WorkflowExecutionPolicyRecord:
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
    def _execution_policy_to_domain(record: WorkflowExecutionPolicyRecord) -> WorkflowExecutionPolicy:
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
    def _runtime_to_record(workflow_app_runtime: WorkflowAppRuntime) -> WorkflowAppRuntimeRecord:
        """把 WorkflowAppRuntime 转换为 ORM 实体。"""

        return WorkflowAppRuntimeRecord(
            workflow_runtime_id=workflow_app_runtime.workflow_runtime_id,
            project_id=workflow_app_runtime.project_id,
            application_id=workflow_app_runtime.application_id,
            display_name=workflow_app_runtime.display_name,
            application_snapshot_object_key=workflow_app_runtime.application_snapshot_object_key,
            template_snapshot_object_key=workflow_app_runtime.template_snapshot_object_key,
            execution_policy_snapshot_object_key=workflow_app_runtime.execution_policy_snapshot_object_key,
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