"""workflow runtime 资源合同。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


WORKFLOW_PREVIEW_RUN_FORMAT = "amvision.workflow-preview-run.v1"
WORKFLOW_APP_RUNTIME_FORMAT = "amvision.workflow-app-runtime.v1"
WORKFLOW_APP_RUNTIME_INSTANCE_FORMAT = "amvision.workflow-app-runtime-instance.v1"
WORKFLOW_RUN_FORMAT = "amvision.workflow-run.v1"


def _require_stripped_text(value: str, field_name: str) -> str:
    """校验字符串字段非空。

    参数：
    - value：待校验的字符串值。
    - field_name：字段名称。

    返回：
    - str：去除两端空白后的结果。
    """

    normalized_value = value.strip()
    if not normalized_value:
        raise ValueError(f"{field_name} 不能为空")
    return normalized_value


class WorkflowPreviewRunContract(BaseModel):
    """描述 WorkflowPreviewRun 的稳定 JSON 合同。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_PREVIEW_RUN_FORMAT] = WORKFLOW_PREVIEW_RUN_FORMAT
    preview_run_id: str
    project_id: str
    application_id: str
    source_kind: str
    application_snapshot_object_key: str
    template_snapshot_object_key: str
    state: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    created_by: str | None = None
    timeout_seconds: int = 30
    outputs: dict[str, object] = Field(default_factory=dict)
    template_outputs: dict[str, object] = Field(default_factory=dict)
    node_records: list[dict[str, object]] = Field(default_factory=list)
    error_message: str | None = None
    retention_until: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> WorkflowPreviewRunContract:
        """校验 WorkflowPreviewRun 合同的关键字段。"""

        _require_stripped_text(self.preview_run_id, "preview_run_id")
        _require_stripped_text(self.project_id, "project_id")
        _require_stripped_text(self.application_id, "application_id")
        _require_stripped_text(self.source_kind, "source_kind")
        _require_stripped_text(self.application_snapshot_object_key, "application_snapshot_object_key")
        _require_stripped_text(self.template_snapshot_object_key, "template_snapshot_object_key")
        _require_stripped_text(self.state, "state")
        _require_stripped_text(self.created_at, "created_at")
        return self


class WorkflowAppRuntimeContract(BaseModel):
    """描述 WorkflowAppRuntime 的稳定 JSON 合同。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_APP_RUNTIME_FORMAT] = WORKFLOW_APP_RUNTIME_FORMAT
    workflow_runtime_id: str
    project_id: str
    application_id: str
    display_name: str
    application_snapshot_object_key: str
    template_snapshot_object_key: str
    desired_state: str
    observed_state: str
    request_timeout_seconds: int = 60
    created_at: str
    updated_at: str
    created_by: str | None = None
    last_started_at: str | None = None
    last_stopped_at: str | None = None
    heartbeat_at: str | None = None
    worker_process_id: int | None = None
    loaded_snapshot_fingerprint: str | None = None
    last_error: str | None = None
    health_summary: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> WorkflowAppRuntimeContract:
        """校验 WorkflowAppRuntime 合同的关键字段。"""

        _require_stripped_text(self.workflow_runtime_id, "workflow_runtime_id")
        _require_stripped_text(self.project_id, "project_id")
        _require_stripped_text(self.application_id, "application_id")
        _require_stripped_text(self.application_snapshot_object_key, "application_snapshot_object_key")
        _require_stripped_text(self.template_snapshot_object_key, "template_snapshot_object_key")
        _require_stripped_text(self.desired_state, "desired_state")
        _require_stripped_text(self.observed_state, "observed_state")
        _require_stripped_text(self.created_at, "created_at")
        _require_stripped_text(self.updated_at, "updated_at")
        return self


class WorkflowAppRuntimeInstanceContract(BaseModel):
    """描述 WorkflowAppRuntime 单实例观测结果的稳定 JSON 合同。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_APP_RUNTIME_INSTANCE_FORMAT] = WORKFLOW_APP_RUNTIME_INSTANCE_FORMAT
    instance_id: str
    workflow_runtime_id: str
    state: str
    process_id: int | None = None
    current_run_id: str | None = None
    started_at: str | None = None
    heartbeat_at: str | None = None
    loaded_snapshot_fingerprint: str | None = None
    last_error: str | None = None
    health_summary: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> WorkflowAppRuntimeInstanceContract:
        """校验 WorkflowAppRuntime instance 合同的关键字段。"""

        _require_stripped_text(self.instance_id, "instance_id")
        _require_stripped_text(self.workflow_runtime_id, "workflow_runtime_id")
        _require_stripped_text(self.state, "state")
        return self


class WorkflowRunContract(BaseModel):
    """描述 WorkflowRun 的稳定 JSON 合同。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_RUN_FORMAT] = WORKFLOW_RUN_FORMAT
    workflow_run_id: str
    workflow_runtime_id: str
    project_id: str
    application_id: str
    state: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    created_by: str | None = None
    requested_timeout_seconds: int = 60
    assigned_process_id: int | None = None
    input_payload: dict[str, object] = Field(default_factory=dict)
    outputs: dict[str, object] = Field(default_factory=dict)
    template_outputs: dict[str, object] = Field(default_factory=dict)
    node_records: list[dict[str, object]] = Field(default_factory=list)
    error_message: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> WorkflowRunContract:
        """校验 WorkflowRun 合同的关键字段。"""

        _require_stripped_text(self.workflow_run_id, "workflow_run_id")
        _require_stripped_text(self.workflow_runtime_id, "workflow_runtime_id")
        _require_stripped_text(self.project_id, "project_id")
        _require_stripped_text(self.application_id, "application_id")
        _require_stripped_text(self.state, "state")
        _require_stripped_text(self.created_at, "created_at")
        return self