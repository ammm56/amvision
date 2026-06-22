"""WorkflowTriggerSource REST 请求模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WorkflowTriggerSourceCreateRequestBody(BaseModel):
    """描述 WorkflowTriggerSource 创建请求体。

    字段：
    - trigger_source_id：触发源 id。
    - project_id：所属 Project id。
    - display_name：展示名称。
    - trigger_kind：触发类型。
    - workflow_runtime_id：绑定的 WorkflowAppRuntime id。
    - submit_mode：提交模式。
    - enabled：创建后是否启用。
    - transport_config：协议连接配置。
    - match_rule：触发匹配规则。
    - input_binding_mapping：输入绑定映射。
    - result_mapping：结果回执映射。
    - default_execution_metadata：默认执行元数据。
    - ack_policy：接收确认策略。
    - result_mode：结果回执模式。
    - reply_timeout_seconds：同步回执超时秒数。
    - debounce_window_ms：去抖窗口毫秒数。
    - idempotency_key_path：幂等键来源路径。
    - metadata：附加元数据。
    """

    trigger_source_id: str = Field(description="触发源 id")
    project_id: str = Field(description="所属 Project id")
    display_name: str = Field(description="展示名称")
    trigger_kind: str = Field(description="触发类型")
    workflow_runtime_id: str = Field(description="绑定的 WorkflowAppRuntime id")
    submit_mode: str = Field(default="async", description="提交模式")
    enabled: bool = Field(default=False, description="创建后是否启用")
    transport_config: dict[str, object] = Field(
        default_factory=dict, description="协议连接配置"
    )
    match_rule: dict[str, object] = Field(
        default_factory=dict, description="触发匹配规则"
    )
    input_binding_mapping: dict[str, object] = Field(
        default_factory=dict, description="输入绑定映射"
    )
    result_mapping: dict[str, object] = Field(
        default_factory=dict, description="结果回执映射"
    )
    default_execution_metadata: dict[str, object] = Field(
        default_factory=dict, description="默认执行元数据"
    )
    ack_policy: str = Field(default="ack-after-run-created", description="接收确认策略")
    result_mode: str = Field(default="accepted-then-query", description="结果回执模式")
    reply_timeout_seconds: int | None = Field(
        default=None, description="同步回执超时秒数"
    )
    debounce_window_ms: int | None = Field(default=None, description="去抖窗口毫秒数")
    idempotency_key_path: str | None = Field(default=None, description="幂等键来源路径")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")

