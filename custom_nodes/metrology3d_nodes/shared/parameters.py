"""六节点的参数契约，与 Catalog 共用，不增加另一个配置来源。"""

from typing import Annotated, Literal
from pydantic import Field, model_validator
from backend.contracts.workflows.metrology import Contract, ResourceReference
from backend.contracts.workflows.point_cloud import CloudFileOptions, ShortText
from custom_nodes.metrology3d_nodes.shared.io.export_file import CloudExportOptions


class FileSource(Contract):
    """读取本次文件输入。"""

    kind: Literal["file"]


class CloudSource(Contract):
    """导出本次运行中的点云。"""

    kind: Literal["cloud"]


class AssetSource(Contract):
    """固定具体资产版本，不解析最新版本。"""

    kind: Literal["asset"]
    reference: ResourceReference

    @model_validator(mode="after")
    def check_kind(self):
        """禁止其他类型资源冒充点云。"""
        if self.reference.kind != "point-cloud":
            raise ValueError("必须选择点云资源")
        return self


class ReadCloudParameters(Contract):
    """文件和持久资产严格二选一。"""

    source: Annotated[FileSource | AssetSource, Field(discriminator="kind", json_schema_extra={
        "x-ui-widget": "cloud-source", "x-live-source-kind": "file", "x-asset-clears": ["file_options"],
    })]
    file_options: CloudFileOptions | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="after")
    def check_options(self):
        """仅文件来源携带读取参数，不覆盖资产空间声明。"""
        if (self.source.kind == "file") != (self.file_options is not None):
            raise ValueError("file_options 必须且仅用于 file 来源")
        if self.source.kind == "asset" and "file_options" in self.model_fields_set:
            raise ValueError("asset 来源不能设置 file_options")
        return self


class NewTarget(Contract):
    """显式新建资源。"""

    kind: Literal["new"]
    name: ShortText


class VersionTarget(Contract):
    """基于期望版本保存，冲突不自动重试。"""

    kind: Literal["new-version"]
    reference: ResourceReference
    name: ShortText


class SaveCloudParameters(Contract):
    """无损保存全部字段，不开放字段筛选。"""

    mode: Literal["original", "derived"]
    target: Annotated[NewTarget | VersionTarget, Field(discriminator="kind", json_schema_extra={"x-ui-widget": "cloud-target"})]


class ExportCloudParameters(CloudExportOptions):
    """交换导出沿用已经验证的选项，补充唯一输入来源。"""

    source: Annotated[CloudSource | AssetSource, Field(discriminator="kind", json_schema_extra={"x-ui-widget": "cloud-source", "x-live-source-kind": "cloud"})]
