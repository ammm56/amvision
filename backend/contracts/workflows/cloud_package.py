"""可搬运的三维配方包，封装现有文档与资产，不包含发布或运行态。"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from backend.contracts.workflows.metrology import Contract, ResourceReference
from backend.contracts.workflows.point_cloud import Sha256
from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    WorkflowGraphTemplate,
)


class WorkflowAppDocument(Contract):
    """与编辑器 JSON 导入导出使用相同的三字段文档。"""

    format_id: Literal["amvision.workflow-app-document.v1"]
    application: FlowApplication
    template: WorkflowGraphTemplate

    @model_validator(mode="after")
    def check_reference(self) -> Self:
        """嵌入模板必须与应用引用一致。"""
        if (
            self.application.template_ref.template_id,
            self.application.template_ref.template_version,
        ) != (
            self.template.template_id,
            self.template.template_version,
        ):
            raise ValueError("配方 App 与 Template 引用不一致")
        return self


class CloudPackageResource(Contract):
    """源资产身份和嵌套 ZIP 摘要，成员路径仅由序号生成。"""

    reference: ResourceReference
    name: Annotated[str, Field(min_length=1, max_length=128)]
    byte_length: Annotated[int, Field(strict=True, gt=0)]
    sha256: Sha256


class WorkflowCloudPackage(Contract):
    """资源父项在子项之前，最多 64 个版本（包含间接依赖）。"""

    format_id: Literal["amvision.workflow-cloud-package.v1"]
    document: WorkflowAppDocument
    resources: Annotated[tuple[CloudPackageResource, ...], Field(max_length=64)]


class CloudPackageReferenceMapping(Contract):
    """源引用到目标引用的一对一映射，包含间接父依赖。"""

    source: ResourceReference
    target: ResourceReference


class CloudPackageImportResult(Contract):
    """只创建草稿，返回新身份与完整映射供编辑器导航和审计。"""

    application_id: str
    template_id: str
    resource_mapping: tuple[CloudPackageReferenceMapping, ...]
