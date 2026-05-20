"""workflow runtime 资源领域对象定义。"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.contracts.workflows.resource_semantics import (
    WorkflowAppRuntimeState,
    WorkflowExecutionPolicyKind,
    WorkflowPreviewRunState,
    WorkflowRunState,
)


@dataclass(frozen=True)
class WorkflowPreviewRun:
    """描述一次编辑态隔离试跑记录。

    字段：
    - preview_run_id：preview run id。
    - project_id：所属 Project id。
    - application_id：所属 application id。
    - source_kind：创建来源类型。
    - application_snapshot_object_key：application snapshot object key。
    - template_snapshot_object_key：template snapshot object key。
    - state：当前运行状态。
    - created_at：创建时间。
    - started_at：开始时间。
    - finished_at：结束时间。
    - created_by：创建主体 id。
    - timeout_seconds：执行超时秒数。
    - outputs：持久化的脱敏 application 输出。
    - template_outputs：持久化的脱敏 template 输出。
    - node_records：持久化的脱敏节点执行记录。
    - preview_display_outputs：仅用于本次同步响应的即时显示输出，不写入数据库。
    - error_message：失败或超时时的错误信息。
    - retention_until：保留截止时间。
    - metadata：附加元数据。
    """

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
    preview_display_outputs: tuple[dict[str, object], ...] = ()
    error_message: str | None = None
    retention_until: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowPreviewRunEvent:
    """描述一条 preview run 执行过程事件。"""

    preview_run_id: str
    sequence: int
    event_type: str
    created_at: str
    message: str
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowAppRuntimeEvent:
    """描述一条 app runtime 生命周期或观测事件。"""

    workflow_runtime_id: str
    sequence: int
    event_type: str
    created_at: str
    message: str
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowExecutionPolicy:
    """描述一条 WorkflowExecutionPolicy 配置。

    字段：
    - execution_policy_id：策略 id。
    - project_id：所属 Project id。
    - display_name：展示名称。
    - policy_kind：策略类型。
    - default_timeout_seconds：默认执行超时秒数。
    - max_run_timeout_seconds：单次运行允许的最大超时秒数。
    - trace_level：trace 保留级别。
    - retain_node_records_enabled：是否保留 node_records。
    - retain_trace_enabled：是否保留 trace 数据。
    - created_at：创建时间。
    - updated_at：更新时间。
    - created_by：创建主体 id。
    - metadata：附加元数据。
    """

    execution_policy_id: str
    project_id: str
    display_name: str
    policy_kind: WorkflowExecutionPolicyKind
    default_timeout_seconds: int = 30
    max_run_timeout_seconds: int = 30
    trace_level: str = "node-summary"
    retain_node_records_enabled: bool = True
    retain_trace_enabled: bool = True
    created_at: str = ""
    updated_at: str = ""
    created_by: str | None = None
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
    execution_policy_snapshot_object_key: str | None = None
    desired_state: WorkflowAppRuntimeState = "stopped"
    observed_state: WorkflowAppRuntimeState = "stopped"
    request_timeout_seconds: int = 60
    heartbeat_interval_seconds: int = 5
    heartbeat_timeout_seconds: int = 15
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


@dataclass(frozen=True)
class WorkflowRunEvent:
    """描述一条 WorkflowRun 生命周期事件。"""

    workflow_run_id: str
    workflow_runtime_id: str
    sequence: int
    event_type: str
    created_at: str
    message: str
    payload: dict[str, object] = field(default_factory=dict)