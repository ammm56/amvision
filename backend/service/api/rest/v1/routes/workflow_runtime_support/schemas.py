"""workflow runtime 路由请求体。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.contracts.workflows import FlowApplication, WorkflowGraphTemplate


class WorkflowApplicationRefRequestBody(BaseModel):
    """描述 preview run 请求体里的 application 引用。"""

    application_id: str = Field(description="已保存 FlowApplication id")


class WorkflowPreviewRunCreateRequestBody(BaseModel):
    """描述 preview run 创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    execution_policy_id: str | None = Field(default=None, description="可选的 WorkflowExecutionPolicy id")
    application_ref: WorkflowApplicationRefRequestBody | None = Field(
        default=None,
        description="可选的已保存 application 引用",
    )
    application: FlowApplication | None = Field(default=None, description="可选 inline application snapshot")
    template: WorkflowGraphTemplate | None = Field(default=None, description="可选 inline template snapshot")
    input_bindings: dict[str, object] = Field(default_factory=dict, description="输入绑定 payload")
    execution_metadata: dict[str, object] = Field(default_factory=dict, description="执行元数据")
    timeout_seconds: int | None = Field(default=None, description="可选同步等待超时秒数")
    wait_mode: Literal["sync", "async"] = Field(default="sync", description="创建后是否同步等待 preview 完成")


class WorkflowExecutionPolicyCreateRequestBody(BaseModel):
    """描述 WorkflowExecutionPolicy 创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    execution_policy_id: str = Field(description="策略 id")
    display_name: str = Field(description="展示名称")
    policy_kind: str = Field(description="策略类型")
    default_timeout_seconds: int = Field(default=30, description="默认执行超时秒数")
    max_run_timeout_seconds: int = Field(default=30, description="最大执行超时秒数")
    trace_level: str = Field(default="none", description="trace 保留级别")
    retain_node_records_enabled: bool = Field(default=False, description="是否保留 node_records")
    retain_trace_enabled: bool = Field(default=False, description="是否保留 trace 数据")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class WorkflowAppRuntimeCreateRequestBody(BaseModel):
    """描述 app runtime 创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    application_id: str = Field(description="已保存 FlowApplication id")
    execution_policy_id: str | None = Field(default=None, description="可选的 WorkflowExecutionPolicy id")
    display_name: str = Field(default="", description="可选展示名称")
    request_timeout_seconds: int | None = Field(default=None, description="可选默认同步调用超时秒数")
    heartbeat_interval_seconds: int | None = Field(default=None, description="可选 worker 主动 heartbeat 周期秒数")
    heartbeat_timeout_seconds: int | None = Field(default=None, description="可选 heartbeat 判定超时秒数")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class WorkflowRuntimeInvokeRequestBody(BaseModel):
    """描述 runtime 同步调用请求体。"""

    input_bindings: dict[str, object] = Field(default_factory=dict, description="输入绑定 payload")
    execution_metadata: dict[str, object] = Field(default_factory=dict, description="执行元数据")
    timeout_seconds: int | None = Field(default=None, description="可选同步等待超时秒数")
