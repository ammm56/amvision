"""obb inference 响应 schema。"""

from __future__ import annotations

from pydantic import BaseModel


class ObbInferenceTaskSubmissionResponse(BaseModel):
    """描述 obb 推理任务创建响应。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
    deployment_instance_id: str
    input_uri: str
    input_source_kind: str
