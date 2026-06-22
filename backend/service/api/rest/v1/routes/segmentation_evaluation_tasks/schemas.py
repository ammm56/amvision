"""segmentation evaluation 请求模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SegmentationEvaluationCreateBody(BaseModel):
    """描述 segmentation evaluation 创建请求。"""

    project_id: str = Field(description="所属 Project id")
    model_version_id: str = Field(description="待评估 ModelVersion id")
    dataset_export_id: str | None = Field(default=None, description="DatasetExport id")
    dataset_export_manifest_key: str | None = Field(default=None, description="导出 manifest key")
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="score threshold")
    mask_threshold: float | None = Field(default=None, ge=0.0, le=1.0, description="mask threshold")
    save_result_package: bool = Field(default=True, description="是否输出结果包")
    extra_options: dict[str, object] = Field(default_factory=dict, description="附加选项")
    display_name: str = Field(default="", description="展示名称")
