"""workflow trigger source 领域对象定义。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.contracts.workflows.resource_semantics import (
    WorkflowTriggerAckPolicy,
    WorkflowTriggerKind,
    WorkflowTriggerResultMode,
    WorkflowTriggerRuntimeState,
    WorkflowTriggerSubmitMode,
)


@dataclass(frozen=True)
class WorkflowTriggerSource:
    """描述一个 workflow 外部触发源资源。

    字段：
    - trigger_source_id：触发源 id。
    - project_id：所属 Project id。
    - display_name：展示名称。
    - trigger_kind：触发类型。
    - workflow_runtime_id：绑定的 WorkflowAppRuntime id。
    - submit_mode：提交模式，sync 或 async。
    - enabled：是否接收新触发。
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

    trigger_source_id: str
    project_id: str
    display_name: str
    trigger_kind: WorkflowTriggerKind
    workflow_runtime_id: str
    submit_mode: WorkflowTriggerSubmitMode = "async"
    enabled: bool = False
    desired_state: WorkflowTriggerRuntimeState = "stopped"
    observed_state: WorkflowTriggerRuntimeState = "stopped"
    transport_config: dict[str, object] = field(default_factory=dict)
    match_rule: dict[str, object] = field(default_factory=dict)
    input_binding_mapping: dict[str, object] = field(default_factory=dict)
    result_mapping: dict[str, object] = field(default_factory=dict)
    default_execution_metadata: dict[str, object] = field(default_factory=dict)
    ack_policy: WorkflowTriggerAckPolicy = "ack-after-run-created"
    result_mode: WorkflowTriggerResultMode = "accepted-then-query"
    reply_timeout_seconds: int | None = None
    debounce_window_ms: int | None = None
    idempotency_key_path: str | None = None
    last_triggered_at: str | None = None
    last_error: str | None = None
    health_summary: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    created_by: str | None = None
