"""通用任务领域对象定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# TaskRecord 允许的正式状态集合。
TaskRecordState = Literal["queued", "running", "succeeded", "failed", "cancelled"]


# TaskAttempt 允许的执行尝试状态集合。
TaskAttemptState = Literal["running", "succeeded", "failed", "cancelled"]


# TaskEvent 当前支持的事件类型集合。
TaskEventType = Literal["status", "progress", "log", "result"]


@dataclass(frozen=True)
class TaskRecord:
    """描述统一任务系统中的正式任务主记录。

    字段：
    - task_id：任务 id。
    - task_kind：任务种类，例如 training、validation、conversion、export。
    - display_name：用于界面展示的任务名。
    - project_id：所属 Project id。
    - created_by：提交任务的主体 id。
    - created_at：任务创建时间。
    - parent_task_id：父任务 id；无父任务时为空。
    - task_spec：任务规格快照。
    - resource_profile_id：关联的 ResourceProfile id。
    - worker_pool：目标 worker pool 名称。
    - metadata：附加元数据。
    - state：当前正式任务状态。
    - current_attempt_no：当前执行尝试序号。
    - started_at：开始运行时间。
    - finished_at：最终结束时间。
    - progress：当前任务进度快照。
    - result：任务结果摘要。
    - error_message：错误消息。
    """

    task_id: str
    task_kind: str
    project_id: str
    display_name: str = ""
    created_by: str | None = None
    created_at: str = ""
    parent_task_id: str | None = None
    task_spec: dict[str, object] = field(default_factory=dict)
    resource_profile_id: str | None = None
    worker_pool: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    state: TaskRecordState = "queued"
    current_attempt_no: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    progress: dict[str, object] = field(default_factory=dict)
    result: dict[str, object] = field(default_factory=dict)
    error_message: str | None = None


@dataclass(frozen=True)
class TaskAttempt:
    """描述一次具体的任务执行尝试。

    字段：
    - attempt_id：执行尝试 id。
    - task_id：所属任务 id。
    - attempt_no：任务内的第几次尝试。
    - worker_id：执行该任务的 worker id。
    - host_id：执行所在主机 id。
    - process_id：执行进程 id。
    - state：当前尝试状态。
    - started_at：执行开始时间。
    - heartbeat_at：最近一次 heartbeat 时间。
    - ended_at：执行结束时间。
    - exit_code：进程退出码。
    - result：本次尝试的结果摘要。
    - error_message：错误摘要。
    - metadata：附加元数据。
    """

    attempt_id: str
    task_id: str
    attempt_no: int
    worker_id: str | None = None
    host_id: str | None = None
    process_id: int | None = None
    state: TaskAttemptState = "running"
    started_at: str | None = None
    heartbeat_at: str | None = None
    ended_at: str | None = None
    exit_code: int | None = None
    result: dict[str, object] = field(default_factory=dict)
    error_message: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskEvent:
    """描述一次任务事件追加记录。

    字段：
    - event_id：事件 id。
    - task_id：所属任务 id。
    - attempt_id：关联的 TaskAttempt id。
    - event_type：事件类型。
    - created_at：事件发生时间。
    - message：事件消息。
    - payload：事件负载。
    """

    event_id: str
    task_id: str
    attempt_id: str | None = None
    event_type: TaskEventType = "log"
    created_at: str = ""
    message: str = ""
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ResourceProfile:
    """描述任务系统使用的最小执行画像。

    字段：
    - resource_profile_id：资源画像 id。
    - profile_name：资源画像名称。
    - worker_pool：默认进入的 worker pool。
    - executor_mode：执行模式，例如 process、thread。
    - max_concurrency：该画像建议的最大并发数。
    - metadata：附加元数据。

    说明：
    - CPU、RAM、显存这类细资源不在通用任务层定义。
    - 训练需要 1 张还是多张 GPU，应放在具体训练任务规格里定义。
    """

    resource_profile_id: str
    profile_name: str
    worker_pool: str
    executor_mode: str = "process"
    max_concurrency: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)