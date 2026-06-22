"""detection evaluation 请求模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.service.domain.models.model_task_types import DETECTION_TASK_TYPE
from backend.service.domain.models.platform_model_support import build_platform_model_type_field_description


class DetectionEvaluationTaskCreateRequestBody(BaseModel):
    """描述 detection 数据集级评估任务创建请求体。"""

    project_id: str = Field(description="所属 Project id")
    model_type: str = Field(description=build_platform_model_type_field_description(DETECTION_TASK_TYPE))
    model_version_id: str = Field(description="待评估 ModelVersion id")
    dataset_export_id: str | None = Field(default=None, description="评估输入使用的 DatasetExport id")
    dataset_export_manifest_key: str | None = Field(default=None, description="评估输入使用的导出 manifest object key")
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="评估 score threshold")
    nms_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="评估 NMS threshold")
    save_result_package: bool = Field(default=True, description="是否输出结果包")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加评估选项")
    display_name: str = Field(default="", description="可选的任务展示名称")
