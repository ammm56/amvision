"""WorkflowTriggerSource health 响应构造。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WorkflowTriggerSourceHealthSummaryResponse(BaseModel):
    """描述 TriggerSource adapter 的运行健康摘要。

    字段：
    - adapter_configured：当前触发适配器配置是否完整。
    - adapter_running：当前触发适配器进程是否处于运行状态。
    - request_count：累计接收请求数。
    - request_count_rollover_count：request_count 计数回卷次数。
    - success_count：累计成功请求数。
    - success_count_rollover_count：success_count 计数回卷次数。
    - error_count：累计错误请求数。
    - error_count_rollover_count：error_count 计数回卷次数。
    - timeout_count：累计超时请求数。
    - timeout_count_rollover_count：timeout_count 计数回卷次数。
    - recent_error：最近一次错误摘要；无错误时为空。
    - supervisor：底层 supervisor 原始健康摘要；不可用时为空对象。
    """

    adapter_configured: bool = Field(description="当前触发适配器配置是否完整")
    adapter_running: bool = Field(description="当前触发适配器进程是否处于运行状态")
    request_count: int = Field(description="累计接收请求数")
    request_count_rollover_count: int = Field(description="request_count 计数回卷次数")
    success_count: int = Field(description="累计成功请求数")
    success_count_rollover_count: int = Field(description="success_count 计数回卷次数")
    error_count: int = Field(description="累计错误请求数")
    error_count_rollover_count: int = Field(description="error_count 计数回卷次数")
    timeout_count: int = Field(description="累计超时请求数")
    timeout_count_rollover_count: int = Field(description="timeout_count 计数回卷次数")
    recent_error: dict[str, object] | str | None = Field(
        default=None, description="最近一次错误摘要"
    )
    supervisor: dict[str, object] = Field(
        default_factory=dict, description="底层 supervisor 原始健康摘要"
    )


class WorkflowTriggerSourceHealthResponse(BaseModel):
    """描述 TriggerSource 健康接口的正式响应模型。

    字段：
    - trigger_source_id：触发源 id。
    - enabled：当前资源是否启用。
    - desired_state：当前期望状态。
    - observed_state：当前观测状态。
    - last_triggered_at：最近一次收到触发的时间。
    - last_error：最近一次资源级错误摘要；无错误时为空。
    - health_summary：当前适配器与 supervisor 健康摘要。
    """

    trigger_source_id: str = Field(description="触发源 id")
    enabled: bool = Field(description="当前资源是否启用")
    desired_state: str = Field(description="当前期望状态")
    observed_state: str = Field(description="当前观测状态")
    last_triggered_at: str | None = Field(
        default=None, description="最近一次收到触发的时间"
    )
    last_error: dict[str, object] | str | None = Field(
        default=None, description="最近一次资源级错误摘要"
    )
    health_summary: WorkflowTriggerSourceHealthSummaryResponse = Field(
        description="适配器与 supervisor 健康摘要"
    )


def build_trigger_source_health_response(
    payload: dict[str, object],
) -> WorkflowTriggerSourceHealthResponse:
    """把 TriggerSource 健康字典转换为正式响应模型。"""

    health_summary = payload.get("health_summary")
    if not isinstance(health_summary, dict):
        health_summary = {}
    return WorkflowTriggerSourceHealthResponse(
        trigger_source_id=str(payload.get("trigger_source_id") or ""),
        enabled=bool(payload.get("enabled") is True),
        desired_state=str(payload.get("desired_state") or "stopped"),
        observed_state=str(payload.get("observed_state") or "stopped"),
        last_triggered_at=(
            payload.get("last_triggered_at")
            if isinstance(payload.get("last_triggered_at"), str)
            else None
        ),
        last_error=normalize_health_error(payload.get("last_error")),
        health_summary=WorkflowTriggerSourceHealthSummaryResponse(
            adapter_configured=bool(health_summary.get("adapter_configured") is True),
            adapter_running=bool(health_summary.get("adapter_running") is True),
            request_count=read_health_counter(health_summary, "request_count"),
            request_count_rollover_count=read_health_counter(
                health_summary, "request_count_rollover_count"
            ),
            success_count=read_health_counter(health_summary, "success_count"),
            success_count_rollover_count=read_health_counter(
                health_summary, "success_count_rollover_count"
            ),
            error_count=read_health_counter(health_summary, "error_count"),
            error_count_rollover_count=read_health_counter(
                health_summary, "error_count_rollover_count"
            ),
            timeout_count=read_health_counter(health_summary, "timeout_count"),
            timeout_count_rollover_count=read_health_counter(
                health_summary, "timeout_count_rollover_count"
            ),
            recent_error=normalize_health_error(health_summary.get("recent_error")),
            supervisor=(
                dict(health_summary.get("supervisor"))
                if isinstance(health_summary.get("supervisor"), dict)
                else {}
            ),
        ),
    )


def normalize_health_error(value: object) -> dict[str, object] | str | None:
    """把健康错误摘要规范化为公开响应可接受的类型。"""

    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    if isinstance(value, str):
        return value
    return None


def read_health_counter(payload: dict[str, object], key: str) -> int:
    """从健康摘要中读取整数计数值。"""

    value = payload.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0

