"""detection 训练任务 API 请求与提交响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.service.api.rest.v1.routes.training_execution_schemas import (
    TrainingExecutionPolicyRequest,
)
from backend.service.api.rest.v1.routes.training_parameter_schemas import (
    DetectionTrainingParameters,
    build_detection_training_parameters,
)


class DetectionTrainingTaskCreateRequestBody(BaseModel):
    """描述 detection 训练任务创建请求体。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    project_id: str = Field(min_length=1, max_length=128, description="所属 Project id")
    model_type: Literal["yolox", "yolov8", "yolo11", "yolo26", "rfdetr"]
    dataset_export_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        description="训练输入 DatasetExport id",
    )
    dataset_export_manifest_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=2048,
        description="训练输入导出 manifest object key",
    )
    recipe_id: str = Field(default="default", min_length=1, max_length=128)
    model_scale: str = Field(min_length=1, max_length=64, description="模型 scale")
    output_model_name: str = Field(
        min_length=1, max_length=128, description="训练后登记的模型名"
    )
    warm_start_model_version_id: str | None = Field(
        default=None, min_length=1, max_length=256
    )
    execution: TrainingExecutionPolicyRequest = Field(
        default_factory=TrainingExecutionPolicyRequest
    )
    parameters: DetectionTrainingParameters
    display_name: str = Field(default="", max_length=256)

    @model_validator(mode="before")
    @classmethod
    def resolve_model_parameters(cls, value: object) -> object:
        """根据 model_type 选择且只选择对应的严格参数 schema。"""

        if not isinstance(value, dict):
            return value
        payload = dict(value)
        model_type = payload.get("model_type")
        if isinstance(model_type, str):
            payload["parameters"] = build_detection_training_parameters(
                model_type=model_type,
                value=payload.get("parameters"),
            )
        return payload

    @model_validator(mode="after")
    def validate_epoch_schedule(self) -> "DetectionTrainingTaskCreateRequestBody":
        """解析短训练的 YOLOX 默认调度，并拒绝无效的显式调度。"""

        if self.model_type == "yolox":
            optimization = self.parameters.optimization
            explicit_fields = optimization.model_fields_set
            available_epochs = max(0, self.execution.max_epochs - 1)
            if "warmup_epochs" in explicit_fields:
                if optimization.warmup_epochs > available_epochs:
                    raise ValueError("YOLOX warmup_epochs 必须小于 max_epochs")
            else:
                optimization.warmup_epochs = min(
                    optimization.warmup_epochs, available_epochs
                )
            remaining_epochs = max(
                0,
                self.execution.max_epochs - optimization.warmup_epochs - 1,
            )
            if "no_aug_epochs" in explicit_fields:
                if optimization.no_aug_epochs > remaining_epochs:
                    raise ValueError(
                        "YOLOX warmup_epochs + no_aug_epochs 必须小于 max_epochs"
                    )
            else:
                optimization.no_aug_epochs = min(
                    optimization.no_aug_epochs, remaining_epochs
                )
        return self


class DetectionTrainingTaskSubmissionResponse(BaseModel):
    """描述 detection 训练任务创建响应。"""

    task_id: str = Field(description="训练任务 id")
    status: str = Field(description="训练任务当前状态")
    queue_name: str = Field(description="提交到的队列名称")
    queue_task_id: str = Field(description="队列任务 id")
    model_type: str = Field(description="模型分类")
    dataset_export_id: str = Field(description="解析后的 DatasetExport id")
    dataset_export_manifest_key: str = Field(
        description="解析后的导出 manifest object key"
    )
    dataset_version_id: str = Field(description="导出来源的 DatasetVersion id")
    format_id: str = Field(description="训练使用的数据集导出格式 id")
