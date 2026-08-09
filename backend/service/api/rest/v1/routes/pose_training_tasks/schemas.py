"""pose 训练任务请求和响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.service.api.rest.v1.routes.model_input_schemas import SpatialSizeRequest
from backend.service.api.rest.v1.routes.training_parameter_schemas import (
    PoseTrainingParameters,
    build_pose_training_parameters,
)


class PoseTrainingTaskCreateRequestBody(BaseModel):
    """pose 训练任务创建请求。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    project_id: str = Field(min_length=1, max_length=128)
    model_type: Literal["yolov8", "yolo11", "yolo26"]
    dataset_export_id: str | None = Field(default=None, min_length=1, max_length=256)
    dataset_export_manifest_key: str | None = Field(
        default=None, min_length=1, max_length=2048
    )
    warm_start_model_version_id: str | None = Field(
        default=None, min_length=1, max_length=256
    )
    recipe_id: str = Field(default="default", min_length=1, max_length=128)
    model_scale: str = Field(min_length=1, max_length=64)
    output_model_name: str = Field(min_length=1, max_length=128)
    evaluation_interval: int = Field(default=5, ge=1, le=10_000)
    max_epochs: int | None = Field(default=None, ge=1, le=10_000)
    batch_size: int | None = Field(default=None, ge=1, le=4096)
    input_size: SpatialSizeRequest | None = None
    precision: Literal["fp16", "fp32"] | None = None
    parameters: PoseTrainingParameters
    display_name: str = Field(default="", max_length=256)

    @model_validator(mode="before")
    @classmethod
    def resolve_model_parameters(cls, value: object) -> object:
        """根据 model_type 选择唯一 pose 参数 schema。"""

        if not isinstance(value, dict):
            return value
        payload = dict(value)
        model_type = payload.get("model_type")
        if isinstance(model_type, str):
            payload["parameters"] = build_pose_training_parameters(
                model_type=model_type,
                value=payload.get("parameters"),
            )
        return payload


class PoseTrainingTaskSubmissionResponse(BaseModel):
    """pose 训练任务提交响应。"""

    task_id: str
    status: str
    queue_name: str
    queue_task_id: str
