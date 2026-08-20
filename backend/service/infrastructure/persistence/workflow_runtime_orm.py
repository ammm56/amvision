"""workflow runtime 资源 ORM 实体定义。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.service.infrastructure.persistence.base import Base


class WorkflowPreviewRunRecord(Base):
    """映射 WorkflowPreviewRun 对象。"""

    __tablename__ = "workflow_preview_runs"

    preview_run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    application_id: Mapped[str] = mapped_column(String(128), index=True)
    source_kind: Mapped[str] = mapped_column(String(64))
    application_snapshot_object_key: Mapped[str] = mapped_column(String(1024))
    template_snapshot_object_key: Mapped[str] = mapped_column(String(1024))
    state: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    outputs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    template_outputs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    node_records_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    retention_until: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class WorkflowExecutionPolicyRecord(Base):
    """映射 WorkflowExecutionPolicy 对象。"""

    __tablename__ = "workflow_execution_policies"

    execution_policy_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    policy_kind: Mapped[str] = mapped_column(String(64), index=True)
    default_timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    max_run_timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    trace_level: Mapped[str] = mapped_column(String(64), default="none")
    retain_node_records_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    retain_trace_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class WorkflowAppRuntimeRecord(Base):
    """映射 WorkflowAppRuntime 对象。"""

    __tablename__ = "workflow_app_runtimes"

    workflow_runtime_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    application_id: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    application_snapshot_object_key: Mapped[str] = mapped_column(String(1024))
    template_snapshot_object_key: Mapped[str] = mapped_column(String(1024))
    execution_policy_snapshot_object_key: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    active_revision_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    desired_revision_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revision_generation: Mapped[int] = mapped_column(Integer, default=0)
    desired_state: Mapped[str] = mapped_column(String(32), index=True)
    observed_state: Mapped[str] = mapped_column(String(32), index=True)
    request_timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)
    heartbeat_interval_seconds: Mapped[int] = mapped_column(Integer, default=5)
    heartbeat_timeout_seconds: Mapped[int] = mapped_column(Integer, default=15)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_started_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_stopped_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    heartbeat_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    worker_instance_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    worker_process_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    loaded_snapshot_fingerprint: Mapped[str | None] = mapped_column(
        String(256), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    health_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class WorkflowRunRecord(Base):
    """映射 WorkflowRun 对象。"""

    __tablename__ = "workflow_runs"

    workflow_run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workflow_runtime_id: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    application_id: Mapped[str] = mapped_column(String(128), index=True)
    workflow_runtime_revision_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    workflow_app_version_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    runtime_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_fingerprint: Mapped[str | None] = mapped_column(String(256), nullable=True)
    worker_instance_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    requested_timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)
    assigned_process_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    outputs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    template_outputs_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    node_records_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class WorkflowAppVersionRecord(Base):
    """映射不可变 WorkflowAppVersion。"""

    __tablename__ = "workflow_app_versions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "application_id",
            "version_number",
            name="uq_workflow_app_version_number",
        ),
        UniqueConstraint(
            "project_id",
            "application_id",
            "content_deduplication_key",
            name="uq_workflow_app_version_content_deduplication",
        ),
    )

    workflow_app_version_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    application_id: Mapped[str] = mapped_column(String(128), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    display_version: Mapped[str] = mapped_column(String(128))
    release_notes: Mapped[str] = mapped_column(String(4096), default="")
    application_snapshot_object_key: Mapped[str] = mapped_column(String(1024))
    template_snapshot_object_key: Mapped[str] = mapped_column(String(1024))
    contract_snapshot_object_key: Mapped[str] = mapped_column(String(1024))
    dependency_manifest_object_key: Mapped[str] = mapped_column(String(1024))
    content_fingerprint: Mapped[str] = mapped_column(String(256), index=True)
    content_deduplication_key: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
    )
    contract_fingerprint: Mapped[str] = mapped_column(String(256), index=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(String(2048), nullable=True)


class WorkflowApplicationLifecycleRecord(Base):
    """映射 Workflow Application 持久化写操作状态门。"""

    __tablename__ = "workflow_application_lifecycles"

    project_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    application_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    operation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[str] = mapped_column(String(64), index=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class WorkflowRuntimeRevisionRecord(Base):
    """映射不可变 WorkflowRuntimeRevision。"""

    __tablename__ = "workflow_runtime_revisions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_runtime_id",
            "generation",
            name="uq_workflow_runtime_revision_generation",
        ),
    )

    workflow_runtime_revision_id: Mapped[str] = mapped_column(
        String(128), primary_key=True
    )
    workflow_runtime_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey(
            "workflow_app_runtimes.workflow_runtime_id",
            name="fk_workflow_runtime_revisions_runtime",
            ondelete="CASCADE",
        ),
        index=True,
    )
    generation: Mapped[int] = mapped_column(Integer)
    workflow_app_version_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey(
            "workflow_app_versions.workflow_app_version_id",
            name="fk_workflow_runtime_revisions_app_version",
        ),
        index=True,
    )
    execution_policy_snapshot_object_key: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    expected_snapshot_fingerprint: Mapped[str] = mapped_column(String(256))
    state: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    activated_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
