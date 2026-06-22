"""task-native conversion API 请求与响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TaskConversionTaskCreateRequestBody(BaseModel):
    """描述一次 task-native conversion 任务创建请求。"""

    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description="模型分类")
    source_model_version_id: str = Field(description="来源 ModelVersion id")
    target_formats: tuple[str, ...] = Field(min_length=1, description="目标 build 格式列表")
    runtime_profile_id: str | None = Field(default=None, description="可选 RuntimeProfile id")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加转换选项")
    display_name: str = Field(default="", description="可选任务展示名称")


class TaskConversionTaskSubmissionResponse(BaseModel):
    """描述一次 task-native conversion 任务提交响应。"""

    task_id: str = Field(description="转换任务 id")
    status: str = Field(description="转换任务当前状态")
    queue_name: str = Field(description="提交到的队列名称")
    queue_task_id: str = Field(description="队列任务 id")
    task_type: str = Field(description="任务类型")
    model_type: str = Field(description="模型分类")
    source_model_version_id: str = Field(description="来源 ModelVersion id")
    target_formats: list[str] = Field(description="固化后的目标格式列表")


class TaskConversionBuildSummaryResponse(BaseModel):
    """描述单个 conversion 输出登记后的 ModelBuild 摘要响应。"""

    model_build_id: str = Field(description="登记后的 ModelBuild id")
    build_format: str = Field(description="build 格式")
    build_file_id: str = Field(description="对应 ModelFile id")
    build_file_uri: str = Field(description="构建产物 object key 或本地 URI")
    metadata: dict[str, object] = Field(default_factory=dict, description="构建元数据")


class TaskConversionTaskSummaryResponse(BaseModel):
    """描述 task-native conversion 任务摘要响应。"""

    task_id: str = Field(description="转换任务 id")
    display_name: str = Field(description="展示名称")
    project_id: str = Field(description="所属 Project id")
    created_by: str | None = Field(default=None, description="提交主体 id")
    created_at: str = Field(description="创建时间")
    worker_pool: str | None = Field(default=None, description="worker pool 名称")
    state: str = Field(description="当前状态")
    current_attempt_no: int = Field(description="当前尝试序号")
    started_at: str | None = Field(default=None, description="开始时间")
    finished_at: str | None = Field(default=None, description="结束时间")
    progress: dict[str, object] = Field(default_factory=dict, description="进度快照")
    result: dict[str, object] = Field(default_factory=dict, description="结果快照")
    error_message: str | None = Field(default=None, description="错误消息")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")
    task_type: str = Field(description="任务类型")
    model_type: str = Field(description="模型分类")
    source_model_version_id: str = Field(description="来源 ModelVersion id")
    target_formats: list[str] = Field(default_factory=list, description="请求固化的目标格式列表")
    runtime_profile_id: str | None = Field(default=None, description="目标 RuntimeProfile id")
    output_object_prefix: str | None = Field(default=None, description="输出目录前缀")
    plan_object_key: str | None = Field(default=None, description="转换计划 object key")
    report_object_key: str | None = Field(default=None, description="转换结果报告 object key")
    requested_target_formats: list[str] = Field(default_factory=list, description="提交请求中的目标格式")
    produced_formats: list[str] = Field(default_factory=list, description="实际产出的格式列表")
    builds: list[TaskConversionBuildSummaryResponse] = Field(default_factory=list, description="登记成功的构建摘要列表")
    report_summary: dict[str, object] = Field(default_factory=dict, description="转换摘要")


class TaskConversionTaskEventResponse(BaseModel):
    """描述 task-native conversion 任务事件响应。"""

    event_id: str = Field(description="事件 id")
    task_id: str = Field(description="所属任务 id")
    attempt_id: str | None = Field(default=None, description="关联尝试 id")
    event_type: str = Field(description="事件类型")
    created_at: str = Field(description="事件时间")
    message: str = Field(description="事件消息")
    payload: dict[str, object] = Field(default_factory=dict, description="事件负载")


class TaskConversionTaskDetailResponse(TaskConversionTaskSummaryResponse):
    """描述 task-native conversion 任务详情响应。"""

    task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
    events: list[TaskConversionTaskEventResponse] = Field(default_factory=list, description="任务事件列表")


class TaskConversionResultResponse(BaseModel):
    """描述 task-native conversion 结果读取响应。"""

    file_status: str = Field(description="转换结果文件状态")
    task_state: str = Field(description="当前转换任务状态")
    object_key: str | None = Field(default=None, description="转换结果文件 object key")
    payload: dict[str, object] = Field(default_factory=dict, description="转换结果 JSON 内容")
