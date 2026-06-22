"""通用任务路由请求与响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TaskCreateRequestBody(BaseModel):
    """描述公开创建任务接口的请求体。"""

    project_id: str = Field(description="所属 Project id")
    task_kind: str = Field(description="任务类型")
    display_name: str = Field(default="", description="展示名称")
    parent_task_id: str | None = Field(default=None, description="父任务 id")
    task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
    resource_profile_id: str | None = Field(default=None, description="资源画像 id")
    worker_pool: str | None = Field(default=None, description="目标 worker pool")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class TaskEventResponse(BaseModel):
    """描述任务事件响应。"""

    event_id: str = Field(description="事件 id")
    task_id: str = Field(description="所属任务 id")
    attempt_id: str | None = Field(default=None, description="关联尝试 id")
    event_type: str = Field(description="事件类型")
    created_at: str = Field(description="事件时间")
    message: str = Field(description="事件消息")
    payload: dict[str, object] = Field(default_factory=dict, description="事件负载")


class TaskSummaryResponse(BaseModel):
    """描述任务摘要响应。"""

    task_id: str = Field(description="任务 id")
    task_kind: str = Field(description="任务类型")
    display_name: str = Field(description="展示名称")
    project_id: str = Field(description="所属 Project id")
    created_by: str | None = Field(default=None, description="提交主体 id")
    created_at: str = Field(description="创建时间")
    parent_task_id: str | None = Field(default=None, description="父任务 id")
    resource_profile_id: str | None = Field(default=None, description="资源画像 id")
    worker_pool: str | None = Field(default=None, description="worker pool 名称")
    state: str = Field(description="当前状态")
    current_attempt_no: int = Field(description="当前尝试序号")
    started_at: str | None = Field(default=None, description="开始时间")
    finished_at: str | None = Field(default=None, description="结束时间")
    progress: dict[str, object] = Field(default_factory=dict, description="进度快照")
    result: dict[str, object] = Field(default_factory=dict, description="结果摘要")
    error_message: str | None = Field(default=None, description="错误消息")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


class TaskDetailResponse(TaskSummaryResponse):
    """描述任务详情响应。

    字段：
    - task_spec：任务规格。
    - events：普通详情查询默认不返回；部分操作响应只返回本次新增事件。
    """

    task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
    events: list[TaskEventResponse] = Field(
        default_factory=list,
        description="普通详情查询默认不返回；部分操作响应只返回本次新增事件",
    )
