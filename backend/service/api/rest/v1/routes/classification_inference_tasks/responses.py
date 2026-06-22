"""classification inference 响应 schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ClassificationInferenceTaskSubmissionResponse(BaseModel):
    """描述 classification 推理任务创建响应。"""

    task_id: str = Field(description="任务 id")
    status: str = Field(description="当前状态")
    queue_name: str = Field(description="队列名称")
    queue_task_id: str = Field(description="队列任务 id")
    deployment_instance_id: str = Field(description="DeploymentInstance id")
    input_uri: str = Field(description="标准化输入 URI")
    input_source_kind: str = Field(description="输入来源类型")
