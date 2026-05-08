"""workflow runtime 资源 ORM 实体定义。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Integer, String
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


class WorkflowAppRuntimeRecord(Base):
    """映射 WorkflowAppRuntime 对象。"""

    __tablename__ = "workflow_app_runtimes"

    workflow_runtime_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    application_id: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    application_snapshot_object_key: Mapped[str] = mapped_column(String(1024))
    template_snapshot_object_key: Mapped[str] = mapped_column(String(1024))
    desired_state: Mapped[str] = mapped_column(String(32), index=True)
    observed_state: Mapped[str] = mapped_column(String(32), index=True)
    request_timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_started_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_stopped_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    heartbeat_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    worker_process_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    loaded_snapshot_fingerprint: Mapped[str | None] = mapped_column(String(256), nullable=True)
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