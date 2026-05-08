"""workflow runtime 资源领域对象定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


WorkflowPreviewRunState = Literal["created", "running", "succeeded", "failed", "timed_out"]
WorkflowAppRuntimeState = Literal["stopped", "starting", "running", "stopping", "failed"]
WorkflowRunState = Literal["created", "queued", "dispatching", "running", "succeeded", "failed", "cancelled", "timed_out"]


@dataclass(frozen=True)
class WorkflowPreviewRun:
    """描述一次编辑态隔离试跑记录。"""

    preview_run_id: str
    project_id: str
    application_id: str
    source_kind: str
    application_snapshot_object_key: str
    template_snapshot_object_key: str
    state: WorkflowPreviewRunState = "created"
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    created_by: str | None = None
    timeout_seconds: int = 30
    outputs: dict[str, object] = field(default_factory=dict)
    template_outputs: dict[str, object] = field(default_factory=dict)
    node_records: tuple[dict[str, object], ...] = ()
    error_message: str | None = None
    retention_until: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowAppRuntime:
    """描述一份已发布应用的最小长期运行记录。"""

    workflow_runtime_id: str
    project_id: str
    application_id: str
    display_name: str
    application_snapshot_object_key: str
    template_snapshot_object_key: str
    desired_state: WorkflowAppRuntimeState = "stopped"
    observed_state: WorkflowAppRuntimeState = "stopped"
    request_timeout_seconds: int = 60
    created_at: str = ""
    updated_at: str = ""
    created_by: str | None = None
    last_started_at: str | None = None
    last_stopped_at: str | None = None
    heartbeat_at: str | None = None
    worker_process_id: int | None = None
    loaded_snapshot_fingerprint: str | None = None
    last_error: str | None = None
    health_summary: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowRun:
    """描述一次正式调用记录。"""

    workflow_run_id: str
    workflow_runtime_id: str
    project_id: str
    application_id: str
    state: WorkflowRunState = "created"
    created_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    created_by: str | None = None
    requested_timeout_seconds: int = 60
    assigned_process_id: int | None = None
    input_payload: dict[str, object] = field(default_factory=dict)
    outputs: dict[str, object] = field(default_factory=dict)
    template_outputs: dict[str, object] = field(default_factory=dict)
    node_records: tuple[dict[str, object], ...] = ()
    error_message: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)