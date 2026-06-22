"""segmentation 训练任务请求和响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.service.domain.models.model_task_types import SEGMENTATION_TASK_TYPE
from backend.service.domain.models.platform_model_support import (
    build_platform_model_type_field_description,
)


class SegmentationTrainingTaskCreateRequestBody(BaseModel):
    """segmentation 训练任务创建请求。"""

    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(
        description=build_platform_model_type_field_description(SEGMENTATION_TASK_TYPE)
    )
    dataset_export_id: str | None = Field(default=None, description="DatasetExport id")
    dataset_export_manifest_key: str | None = Field(
        default=None, description="导出 manifest key"
    )
    recipe_id: str = Field(default="default", description="训练 recipe id")
    model_scale: str = Field(description="模型 scale")
    output_model_name: str = Field(description="训练后登记的模型名")
    max_epochs: int | None = Field(default=None, ge=1, description="最大训练轮数")
    batch_size: int | None = Field(default=None, ge=1, description="batch size")
    input_size: tuple[int, int] | None = Field(default=None, description="训练输入尺寸")
    precision: str | None = Field(default=None, description="训练 precision")
    extra_options: dict[str, object] = Field(
        default_factory=dict, description="附加训练选项"
    )
    display_name: str = Field(default="", description="可选展示名称")


class SegmentationTrainingTaskSubmissionResponse(BaseModel):
    """segmentation 训练任务提交响应。"""

    task_id: str = Field(description="任务 id")
    status: str = Field(description="当前状态")
    queue_name: str = Field(description="提交到的队列名称")
    queue_task_id: str = Field(description="队列任务 id")

