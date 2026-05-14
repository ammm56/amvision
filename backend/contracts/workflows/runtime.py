"""workflow runtime 资源合同。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.contracts.workflows.resource_semantics import (
    WorkflowAppRuntimeState,
    WorkflowExecutionPolicyKind,
    WorkflowPreviewRunState,
    WorkflowRunState,
)


WORKFLOW_PREVIEW_RUN_FORMAT = "amvision.workflow-preview-run.v1"
WORKFLOW_PREVIEW_RUN_SUMMARY_FORMAT = "amvision.workflow-preview-run-summary.v1"
WORKFLOW_APP_RUNTIME_FORMAT = "amvision.workflow-app-runtime.v1"
WORKFLOW_APP_RUNTIME_INSTANCE_FORMAT = "amvision.workflow-app-runtime-instance.v1"
WORKFLOW_RUN_FORMAT = "amvision.workflow-run.v1"
WORKFLOW_EXECUTION_POLICY_FORMAT = "amvision.workflow-execution-policy.v1"


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
    state: WorkflowPreviewRunState
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


class WorkflowPreviewRunSummaryContract(BaseModel):
    """描述 WorkflowPreviewRun 列表摘要合同。

    字段：
    - format_id：合同格式 id。
    - preview_run_id：preview run id。
    - project_id：所属 Project id。
    - application_id：应用 id。
    - source_kind：执行来源类型。
    - state：当前运行状态。
    - created_at：创建时间。
    - started_at：开始时间。
    - finished_at：结束时间。
    - created_by：创建主体 id。
    - timeout_seconds：请求超时秒数。
    - error_message：失败或超时错误信息。
    - retention_until：保留截止时间。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_PREVIEW_RUN_SUMMARY_FORMAT] = WORKFLOW_PREVIEW_RUN_SUMMARY_FORMAT
    preview_run_id: str
    project_id: str
    application_id: str
    source_kind: str
    state: WorkflowPreviewRunState
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    created_by: str | None = None
    timeout_seconds: int = 30
    error_message: str | None = None
    retention_until: str | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> WorkflowPreviewRunSummaryContract:
        """校验 WorkflowPreviewRun 摘要合同的关键字段。"""

        _require_stripped_text(self.preview_run_id, "preview_run_id")
        _require_stripped_text(self.project_id, "project_id")
        _require_stripped_text(self.application_id, "application_id")
        _require_stripped_text(self.source_kind, "source_kind")
        _require_stripped_text(self.state, "state")
        _require_stripped_text(self.created_at, "created_at")
        return self


class WorkflowTemplateReferenceSummaryContract(BaseModel):
    """描述 template 资源的一跳摘要。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str
    template_id: str
    template_version: str
    display_name: str
    description: str
    created_at: str
    updated_at: str
    created_by: str | None = None
    updated_by: str | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> WorkflowTemplateReferenceSummaryContract:
        """校验 template 一跳摘要的关键字段。"""

        _require_stripped_text(self.project_id, "project_id")
        _require_stripped_text(self.template_id, "template_id")
        _require_stripped_text(self.template_version, "template_version")
        _require_stripped_text(self.created_at, "created_at")
        _require_stripped_text(self.updated_at, "updated_at")
        return self


class WorkflowApplicationReferenceSummaryContract(BaseModel):
    """描述 application 资源的一跳摘要。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str
    application_id: str
    display_name: str
    description: str
    created_at: str
    updated_at: str
    created_by: str | None = None
    updated_by: str | None = None
    template_id: str
    template_version: str

    @model_validator(mode="after")
    def validate_contract(self) -> WorkflowApplicationReferenceSummaryContract:
        """校验 application 一跳摘要的关键字段。"""

        _require_stripped_text(self.project_id, "project_id")
        _require_stripped_text(self.application_id, "application_id")
        _require_stripped_text(self.template_id, "template_id")
        _require_stripped_text(self.template_version, "template_version")
        _require_stripped_text(self.created_at, "created_at")
        _require_stripped_text(self.updated_at, "updated_at")
        return self


class WorkflowRuntimeReferenceSummaryContract(BaseModel):
    """描述 runtime 资源的一跳摘要。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_runtime_id: str
    project_id: str
    application_id: str
    display_name: str
    desired_state: WorkflowAppRuntimeState
    observed_state: WorkflowAppRuntimeState
    created_at: str
    updated_at: str
    created_by: str | None = None
    updated_by: str | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> WorkflowRuntimeReferenceSummaryContract:
        """校验 runtime 一跳摘要的关键字段。"""

        _require_stripped_text(self.workflow_runtime_id, "workflow_runtime_id")
        _require_stripped_text(self.project_id, "project_id")
        _require_stripped_text(self.application_id, "application_id")
        _require_stripped_text(self.desired_state, "desired_state")
        _require_stripped_text(self.observed_state, "observed_state")
        _require_stripped_text(self.created_at, "created_at")
        _require_stripped_text(self.updated_at, "updated_at")
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
    execution_policy_snapshot_object_key: str | None = None
    desired_state: WorkflowAppRuntimeState
    observed_state: WorkflowAppRuntimeState
    request_timeout_seconds: int = 60
    created_at: str
    updated_at: str
    created_by: str | None = None
    updated_by: str | None = None
    application_summary: WorkflowApplicationReferenceSummaryContract | None = None
    template_summary: WorkflowTemplateReferenceSummaryContract | None = None
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
    state: WorkflowAppRuntimeState
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
    state: WorkflowRunState
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


class WorkflowExecutionPolicyContract(BaseModel):
    """描述 WorkflowExecutionPolicy 的稳定 JSON 合同。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_EXECUTION_POLICY_FORMAT] = WORKFLOW_EXECUTION_POLICY_FORMAT
    execution_policy_id: str
    project_id: str
    display_name: str
    policy_kind: WorkflowExecutionPolicyKind
    default_timeout_seconds: int = 30
    max_run_timeout_seconds: int = 30
    trace_level: str = "node-summary"
    retain_node_records_enabled: bool = True
    retain_trace_enabled: bool = True
    created_at: str
    updated_at: str
    created_by: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> WorkflowExecutionPolicyContract:
        """校验 WorkflowExecutionPolicy 合同的关键字段。"""

        _require_stripped_text(self.execution_policy_id, "execution_policy_id")
        _require_stripped_text(self.project_id, "project_id")
        _require_stripped_text(self.display_name, "display_name")
        _require_stripped_text(self.policy_kind, "policy_kind")
        _require_stripped_text(self.trace_level, "trace_level")
        _require_stripped_text(self.created_at, "created_at")
        _require_stripped_text(self.updated_at, "updated_at")
        return self