"""workflow trigger source ORM 实体定义。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.service.infrastructure.persistence.base import Base


class WorkflowTriggerSourceRecord(Base):
    """映射 WorkflowTriggerSource 对象。"""

    __tablename__ = "workflow_trigger_sources"

    trigger_source_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(String(256), default="")
    trigger_kind: Mapped[str] = mapped_column(String(64), index=True)
    workflow_runtime_id: Mapped[str] = mapped_column(String(128), index=True)
    submit_mode: Mapped[str] = mapped_column(String(32), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    desired_state: Mapped[str] = mapped_column(String(32), index=True)
    observed_state: Mapped[str] = mapped_column(String(32), index=True)
    transport_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    match_rule_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    input_binding_mapping_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )
    result_mapping_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    default_execution_metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )
    ack_policy: Mapped[str] = mapped_column(String(64), default="ack-after-run-created")
    result_mode: Mapped[str] = mapped_column(String(64), default="accepted-then-query")
    reply_timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    debounce_window_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_triggered_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    health_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
