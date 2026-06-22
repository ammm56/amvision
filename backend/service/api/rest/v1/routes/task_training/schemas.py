"""非 detection 训练任务通用响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


TrainingTaskActionName = Literal["save", "pause", "resume", "terminate", "delete"]
TrainingTaskControlPhase = Literal[
    "idle", "save_requested", "pause_requested", "terminate_requested"
]


class TrainingTaskControlStatusResponse(BaseModel):
    """描述非 detection 训练详情中的控制状态。"""

    status: TrainingTaskControlPhase = Field(description="当前控制阶段")
    pending_action: TrainingTaskActionName | None = Field(
        default=None, description="当前待处理的控制动作"
    )
    requested_at: str | None = Field(
        default=None,
        description="当前待处理动作的登记时间；当前非 detection 训练未记录该字段",
    )
    requested_by: str | None = Field(
        default=None,
        description="当前待处理动作的登记主体 id；当前非 detection 训练未记录该字段",
    )
    last_save_at: str | None = Field(
        default=None,
        description="最近一次 latest checkpoint 落盘时间；当前非 detection 训练未记录该字段",
    )
    last_save_epoch: int | None = Field(
        default=None,
        description="最近一次 latest checkpoint 对应 epoch；当前非 detection 训练未记录该字段",
    )
    last_save_reason: str | None = Field(
        default=None,
        description="最近一次 latest checkpoint 落盘原因；当前非 detection 训练未记录该字段",
    )
    last_save_by: str | None = Field(
        default=None,
        description="最近一次 latest checkpoint 请求主体 id；当前非 detection 训练未记录该字段",
    )
    last_resume_at: str | None = Field(
        default=None,
        description="最近一次 resume 请求时间；当前非 detection 训练未记录该字段",
    )
    last_resume_by: str | None = Field(
        default=None,
        description="最近一次 resume 请求主体 id；当前非 detection 训练未记录该字段",
    )
    resume_count: int = Field(
        default=0,
        description="当前任务累计 resume 次数；当前非 detection 训练未记录该字段",
    )
    resume_checkpoint_object_key: str | None = Field(
        default=None, description="当前 resume 将使用的 checkpoint object key"
    )


class TrainingTaskEventResponse(BaseModel):
    """描述非 detection 训练任务事件响应。"""

    event_id: str = Field(description="事件 id")
    task_id: str = Field(description="所属任务 id")
    attempt_id: str | None = Field(default=None, description="关联尝试 id")
    event_type: str = Field(description="事件类型")
    created_at: str = Field(description="事件时间")
    message: str = Field(description="事件消息")
    payload: dict[str, object] = Field(default_factory=dict, description="事件负载")


class TrainingTaskSummaryResponse(BaseModel):
    """非 detection 训练任务摘要。"""

    task_id: str = Field(description="任务 id")
    display_name: str = Field(description="展示名称")
    project_id: str = Field(description="所属 Project id")
    created_by: str | None = Field(default=None, description="提交主体")
    created_at: str = Field(description="创建时间")
    worker_pool: str | None = Field(default=None, description="worker pool 名称")
    state: str = Field(description="当前状态")
    current_attempt_no: int = Field(description="当前尝试序号")
    started_at: str | None = Field(default=None, description="开始时间")
    finished_at: str | None = Field(default=None, description="结束时间")
    progress: dict[str, object] = Field(default_factory=dict, description="进度快照")
    result: dict[str, object] = Field(default_factory=dict, description="结果快照")
    error_message: str | None = Field(default=None, description="错误信息")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")
    task_type: str = Field(
        description="任务分类（classification / segmentation / pose / obb）"
    )
    model_type: str | None = Field(default=None, description="模型分类")
    dataset_export_id: str | None = Field(
        default=None, description="训练输入使用的 DatasetExport id"
    )
    dataset_export_manifest_key: str | None = Field(
        default=None, description="训练输入使用的导出 manifest object key"
    )
    dataset_version_id: str | None = Field(
        default=None, description="训练输入使用的 DatasetVersion id"
    )
    format_id: str | None = Field(default=None, description="训练输入导出格式 id")
    recipe_id: str | None = Field(default=None, description="训练 recipe id")
    model_scale: str | None = Field(default=None, description="训练目标的模型 scale")
    evaluation_interval: int | None = Field(
        default=None, description="真实验证评估周期"
    )
    gpu_count: int | None = Field(
        default=None,
        description="请求参与训练的 GPU 数量；当前非 detection 训练未记录该字段",
    )
    precision: str | None = Field(default=None, description="请求使用的训练 precision")
    output_model_name: str | None = Field(default=None, description="训练输出模型名")
    model_version_id: str | None = Field(
        default=None, description="训练输出登记后的 ModelVersion id"
    )
    latest_checkpoint_model_version_id: str | None = Field(
        default=None,
        description="自动或手动登记 latest checkpoint 得到的 ModelVersion id；当前非 detection 训练未单独记录该字段",
    )
    output_object_prefix: str | None = Field(
        default=None, description="训练输出目录前缀"
    )
    checkpoint_object_key: str | None = Field(
        default=None, description="checkpoint 文件 object key"
    )
    latest_checkpoint_object_key: str | None = Field(
        default=None, description="最新 checkpoint 文件 object key"
    )
    labels_object_key: str | None = Field(
        default=None, description="标签文件 object key"
    )
    metrics_object_key: str | None = Field(
        default=None, description="训练指标文件 object key"
    )
    validation_metrics_object_key: str | None = Field(
        default=None, description="验证指标文件 object key"
    )
    summary_object_key: str | None = Field(
        default=None, description="训练摘要文件 object key"
    )
    best_metric_name: str | None = Field(default=None, description="最佳指标名称")
    best_metric_value: float | None = Field(default=None, description="最佳指标值")
    training_summary: dict[str, object] = Field(
        default_factory=dict, description="训练摘要"
    )


class TrainingTaskDetailResponse(TrainingTaskSummaryResponse):
    """非 detection 训练任务详情。"""

    available_actions: list[TrainingTaskActionName] = Field(
        description="当前建议展示的训练控制动作列表"
    )
    control_status: TrainingTaskControlStatusResponse = Field(
        description="训练控制状态"
    )
    task_spec: dict[str, object] = Field(default_factory=dict, description="任务规格")
    events: list[TrainingTaskEventResponse] = Field(
        default_factory=list, description="任务事件列表"
    )


class TrainingTaskSubmissionResponse(BaseModel):
    """训练任务继续（re-enqueue）响应。"""

    task_id: str = Field(description="任务 id")
    status: str = Field(description="当前状态")
    queue_name: str = Field(description="提交到的队列名称")
    queue_task_id: str = Field(description="队列任务 id")

