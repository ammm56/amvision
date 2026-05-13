"""workflow trigger source 资源合同。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


WORKFLOW_TRIGGER_SOURCE_FORMAT = "amvision.workflow-trigger-source.v1"
WORKFLOW_TRIGGER_EVENT_FORMAT = "amvision.workflow-trigger-event.v1"
WORKFLOW_TRIGGER_RESULT_FORMAT = "amvision.workflow-trigger-result.v1"

WorkflowTriggerKind = Literal[
    "plc-register",
    "mqtt-topic",
    "zeromq-topic",
    "grpc-method",
    "io-change",
    "sensor-read",
    "schedule",
    "webhook",
    "http-api",
]
WorkflowTriggerSubmitMode = Literal["sync", "async"]
WorkflowTriggerRuntimeState = Literal[
    "stopped", "starting", "running", "stopping", "failed"
]
WorkflowTriggerResultMode = Literal[
    "sync-reply", "accepted-then-query", "async-report", "event-only"
]
WorkflowTriggerAckPolicy = Literal[
    "ack-after-received", "ack-after-run-created", "ack-after-run-finished"
]
WorkflowTriggerResultState = Literal["accepted", "succeeded", "failed", "timed_out"]


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


class InputBindingMappingItemContract(BaseModel):
    """描述单个外部事件字段到 application input binding 的映射规则。

    字段：
    - source：事件 payload 中的来源路径，例如 payload.image 或 payload.value。
    - value：静态绑定值；用于固定配置或默认输入。
    - required：映射来源缺失时是否视为请求错误。
    - payload_type_id：目标 payload 类型提示。
    - metadata：附加映射元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str | None = None
    value: object | None = None
    required: bool = True
    payload_type_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> InputBindingMappingItemContract:
        """校验 input binding 映射规则。"""

        if self.source is not None:
            _require_stripped_text(self.source, "source")
        if self.payload_type_id is not None:
            _require_stripped_text(self.payload_type_id, "payload_type_id")
        if self.source is None and self.value is None:
            raise ValueError("input binding 映射必须提供 source 或 value")
        return self


class ResultMappingContract(BaseModel):
    """描述 workflow 输出到协议回执的映射规则。

    字段：
    - result_binding：优先读取的 FlowApplication 输出 binding。
    - result_mode：结果回执模式。
    - reply_timeout_seconds：同步回执等待超时秒数。
    - metadata：附加回执元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    result_binding: str = "workflow_result"
    result_mode: WorkflowTriggerResultMode = "accepted-then-query"
    reply_timeout_seconds: int | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> ResultMappingContract:
        """校验 result mapping 规则。"""

        _require_stripped_text(self.result_binding, "result_binding")
        if self.reply_timeout_seconds is not None and self.reply_timeout_seconds <= 0:
            raise ValueError("reply_timeout_seconds 必须大于 0")
        return self


class WorkflowTriggerSourceContract(BaseModel):
    """描述 WorkflowTriggerSource 的稳定 JSON 合同。

    字段：
    - format_id：当前资源格式版本。
    - trigger_source_id：触发源 id。
    - project_id：所属 Project id。
    - display_name：展示名称。
    - trigger_kind：触发类型。
    - workflow_runtime_id：绑定的 WorkflowAppRuntime id。
    - submit_mode：提交模式，sync 或 async。
    - enabled：是否启用接收新触发。
    - desired_state：期望运行状态。
    - observed_state：实际观测状态。
    - transport_config：协议连接配置。
    - match_rule：触发匹配、过滤或去抖规则。
    - input_binding_mapping：事件到 input binding 的映射。
    - result_mapping：workflow 输出到协议回执的映射。
    - default_execution_metadata：默认执行元数据。
    - ack_policy：接收确认策略。
    - result_mode：结果回执模式。
    - reply_timeout_seconds：同步回执超时秒数。
    - debounce_window_ms：去抖窗口毫秒数。
    - idempotency_key_path：幂等键来源路径。
    - last_triggered_at：最近一次触发时间。
    - last_error：最近错误消息。
    - health_summary：运行健康摘要。
    - metadata：附加元数据。
    - created_at：创建时间。
    - updated_at：更新时间。
    - created_by：创建主体 id。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_TRIGGER_SOURCE_FORMAT] = WORKFLOW_TRIGGER_SOURCE_FORMAT
    trigger_source_id: str
    project_id: str
    display_name: str
    trigger_kind: WorkflowTriggerKind
    workflow_runtime_id: str
    submit_mode: WorkflowTriggerSubmitMode = "async"
    enabled: bool = False
    desired_state: WorkflowTriggerRuntimeState = "stopped"
    observed_state: WorkflowTriggerRuntimeState = "stopped"
    transport_config: dict[str, object] = Field(default_factory=dict)
    match_rule: dict[str, object] = Field(default_factory=dict)
    input_binding_mapping: dict[str, InputBindingMappingItemContract] = Field(
        default_factory=dict
    )
    result_mapping: ResultMappingContract = Field(default_factory=ResultMappingContract)
    default_execution_metadata: dict[str, object] = Field(default_factory=dict)
    ack_policy: WorkflowTriggerAckPolicy = "ack-after-run-created"
    result_mode: WorkflowTriggerResultMode = "accepted-then-query"
    reply_timeout_seconds: int | None = None
    debounce_window_ms: int | None = None
    idempotency_key_path: str | None = None
    last_triggered_at: str | None = None
    last_error: str | None = None
    health_summary: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    created_by: str | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> WorkflowTriggerSourceContract:
        """校验 WorkflowTriggerSource 合同的关键字段。"""

        _require_stripped_text(self.trigger_source_id, "trigger_source_id")
        _require_stripped_text(self.project_id, "project_id")
        _require_stripped_text(self.display_name, "display_name")
        _require_stripped_text(self.workflow_runtime_id, "workflow_runtime_id")
        _require_stripped_text(self.created_at, "created_at")
        _require_stripped_text(self.updated_at, "updated_at")
        if self.reply_timeout_seconds is not None and self.reply_timeout_seconds <= 0:
            raise ValueError("reply_timeout_seconds 必须大于 0")
        if self.debounce_window_ms is not None and self.debounce_window_ms < 0:
            raise ValueError("debounce_window_ms 不能小于 0")
        if self.idempotency_key_path is not None:
            _require_stripped_text(self.idempotency_key_path, "idempotency_key_path")
        return self


class TriggerEventContract(BaseModel):
    """描述外部协议事件进入平台后的统一事件合同。

    字段：
    - format_id：当前事件格式版本。
    - trigger_source_id：触发源 id。
    - trigger_kind：触发类型。
    - event_id：外部或平台生成的事件 id。
    - trace_id：链路追踪 id。
    - occurred_at：事件发生时间。
    - idempotency_key：可选幂等键。
    - payload：结构化事件内容。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_TRIGGER_EVENT_FORMAT] = WORKFLOW_TRIGGER_EVENT_FORMAT
    trigger_source_id: str
    trigger_kind: WorkflowTriggerKind
    event_id: str
    trace_id: str | None = None
    occurred_at: str
    idempotency_key: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> TriggerEventContract:
        """校验 TriggerEvent 合同的关键字段。"""

        _require_stripped_text(self.trigger_source_id, "trigger_source_id")
        _require_stripped_text(self.event_id, "event_id")
        _require_stripped_text(self.occurred_at, "occurred_at")
        return self


class TriggerResultContract(BaseModel):
    """描述触发调用层返回给协议 adapter 的统一结果。

    字段：
    - format_id：当前结果格式版本。
    - trigger_source_id：触发源 id。
    - event_id：对应事件 id。
    - state：触发提交或执行结果状态。
    - workflow_run_id：创建出的 WorkflowRun id。
    - response_payload：协议中立响应内容。
    - error_message：错误消息。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_TRIGGER_RESULT_FORMAT] = WORKFLOW_TRIGGER_RESULT_FORMAT
    trigger_source_id: str
    event_id: str
    state: WorkflowTriggerResultState
    workflow_run_id: str | None = None
    response_payload: dict[str, object] = Field(default_factory=dict)
    error_message: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> TriggerResultContract:
        """校验 TriggerResult 合同的关键字段。"""

        _require_stripped_text(self.trigger_source_id, "trigger_source_id")
        _require_stripped_text(self.event_id, "event_id")
        if self.error_message is not None:
            _require_stripped_text(self.error_message, "error_message")
        return self
