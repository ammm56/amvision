"""workflow runtime 路由请求体。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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

    model_config = ConfigDict(extra="allow")

    input_bindings: dict[str, object] | None = Field(default=None, description="输入绑定 payload")
    execution_metadata: dict[str, object] = Field(default_factory=dict, description="执行元数据")
    timeout_seconds: int | None = Field(default=None, description="可选同步等待超时秒数")

    def resolve_input_bindings(self) -> dict[str, object]:
        """返回最终输入绑定。

        app runtime 的公开 HTTP 调用应能直接用公开输入 id 作为顶层字段；平台内部调用也可以继续
        使用 input_bindings 包装字段。两个形态不能混用，避免同一个请求里出现两套输入来源。
        """

        direct_bindings = dict(self.model_extra or {})
        if self.input_bindings is not None:
            if direct_bindings:
                direct_names = ", ".join(sorted(direct_bindings))
                raise ValueError(
                    "不能同时使用 input_bindings 包装字段和顶层公开输入字段："
                    f"{direct_names}"
                )
            return dict(self.input_bindings)
        return direct_bindings
