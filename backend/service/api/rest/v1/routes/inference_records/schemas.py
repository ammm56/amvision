"""同步推理显式保存记录 API 请求与响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.service.infrastructure.persistence.direct_inference_record_orm import (
    DirectInferenceRecord,
)


class DirectInferenceRecordSaveRequestBody(BaseModel):
    """独立显式保存同步推理结果的 JSON 请求体（支持手动作保存与失败仅重试保存）。"""

    project_id: str = Field(description="所属 Project id")
    request_id: str = Field(description="客户端或网关同步推理 request_id")
    task_type: str = Field(description="模型任务类型")
    deployment_instance_id: str = Field(description="执行推理的 DeploymentInstance id")
    result_payload: dict[str, object] = Field(description="已获取到的同步推理结果 JSON")
    input_label: str = Field(default="", description="输入文件显示名")
    input_image_base64: str | None = Field(default=None, description="可选输入图 Base64，用于无引用来源的本地落盘预览")
    parameters: dict[str, object] = Field(default_factory=dict, description="当次推理参数快照")


class DirectInferenceRecordSummaryResponse(BaseModel):
    """同步推理显式保存记录摘要响应。"""

    record_id: str = Field(description="保存记录主键 id")
    project_id: str = Field(description="所属 Project id")
    request_id: str = Field(description="关联同步请求 id")
    task_type: str = Field(description="任务类型")
    deployment_instance_id: str = Field(description="部署实例 id")
    deployment_display_name: str = Field(default="", description="部署实例展示名称")
    model_version_id: str | None = Field(default=None, description="模型版本 id")
    model_build_id: str | None = Field(default=None, description="模型构建版本 id")
    input_source_kind: str = Field(description="输入来源类型")
    input_label: str = Field(default="", description="输入展示名称")
    input_uri: str | None = Field(default=None, description="输入 URI")
    input_file_id: str | None = Field(default=None, description="Project 公开文件 id")
    has_input_image: bool = Field(description="是否具备可回看输入图片")
    has_preview_image: bool = Field(description="是否具备服务端渲染预览图")
    result_object_key: str = Field(description="结果 JSON 文件 object key")
    preview_image_object_key: str | None = Field(default=None, description="预览图 object key")
    item_count: int = Field(description="结果对象或分类项数量")
    latency_ms: float | None = Field(default=None, description="推理耗时（毫秒）")
    image_width: int | None = Field(default=None, description="输入图像宽度")
    image_height: int | None = Field(default=None, description="输入图像高度")
    parameters: dict[str, object] = Field(default_factory=dict, description="参数快照")
    result_summary: dict[str, object] = Field(default_factory=dict, description="结果摘要")
    created_by: str | None = Field(default=None, description="创建主体 id")
    created_at: str = Field(description="创建时间")


class DirectInferenceRecordDetailResponse(DirectInferenceRecordSummaryResponse):
    """同步推理显式保存记录详情响应（含完整推理载荷）。"""

    file_status: Literal["ready", "missing"] = Field(description="结果文件状态")
    result_payload: dict[str, object] = Field(default_factory=dict, description="完整推理结果 JSON")


def build_direct_inference_record_summary_response(
    record: DirectInferenceRecord,
) -> DirectInferenceRecordSummaryResponse:
    """将 ORM 记录转换为公开摘要响应。"""

    return DirectInferenceRecordSummaryResponse(
        record_id=record.record_id,
        project_id=record.project_id,
        request_id=record.request_id,
        task_type=record.task_type,
        deployment_instance_id=record.deployment_instance_id,
        deployment_display_name=record.deployment_display_name,
        model_version_id=record.model_version_id,
        model_build_id=record.model_build_id,
        input_source_kind=record.input_source_kind,
        input_label=record.input_label,
        input_uri=record.input_uri,
        input_file_id=record.input_file_id,
        has_input_image=bool(record.input_image_object_key or record.input_file_id),
        has_preview_image=bool(record.preview_image_object_key),
        result_object_key=record.result_object_key,
        preview_image_object_key=record.preview_image_object_key,
        item_count=record.item_count,
        latency_ms=record.latency_ms,
        image_width=record.image_width,
        image_height=record.image_height,
        parameters=dict(record.parameters_json or {}),
        result_summary=dict(record.result_summary_json or {}),
        created_by=record.created_by,
        created_at=record.created_at,
    )
