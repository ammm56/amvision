"""独立模型包契约，不包含部署实例、凭据和本地文件路径。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from backend.contracts.deployments.model_package import (
    PackageFile, PackageObject, PortableBuild, PortableModel, PortableVersion, safe_package_path,
)


class ModelPackage(PackageObject):
    """通过版本和选中的构建产物声明可移植文件。"""

    format_id: Literal["amvision.model-package.v1"] = "amvision.model-package.v1"
    package_id: str
    source_version: str
    created_at: str
    model: PortableModel
    model_version: PortableVersion
    builds: list[PortableBuild] = Field(default_factory=list, max_length=100)
    files: list[PackageFile] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def validate_references(self) -> ModelPackage:
        """核对每个文件的唯一归属和选中产物的必要文件。"""
        keys = {item.key for item in self.files}
        paths = {f"{item.owner}/{item.path}".casefold() for item in self.files}
        if len(keys) != len(self.files) or len(paths) != len(self.files):
            raise ValueError("模型包文件 key 或路径重复")
        if len({row.model_build_id for row in self.builds}) != len(self.builds):
            raise ValueError("模型包产物重复")
        if any("/" not in item.path or item.path.split("/", 1)[0] not in {str(index) for index in range(len(self.builds))}
               for item in self.files if item.owner == "build"):
            raise ValueError("模型包文件没有对应的产物")
        if any(not any(item.owner == "build" and item.path.startswith(f"{index}/") for item in self.files)
               for index in range(len(self.builds))):
            raise ValueError("模型包产物缺少文件")
        if not self.builds and not any(item.owner == "version" and item.path.lower().endswith((".pt", ".pth")) for item in self.files):
            raise ValueError("模型包缺少可登记的权重或构建产物")
        return self


class ModelPackageExportOptions(PackageObject):
    """导出模型版本、原始权重及选中的产物。"""

    model_version_id: str = Field(min_length=1, max_length=128)
    include_checkpoint: bool = True
    build_ids: list[str] = Field(default_factory=list, max_length=100)
    file_name: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_selection(self) -> ModelPackageExportOptions:
        """文件名只用于下载，不能把路径写到对象存储中。"""
        if self.file_name != safe_package_path(self.file_name) or "/" in self.file_name or not self.file_name.lower().endswith(".zip"):
            raise ValueError("输出文件名必须是 ZIP 文件名")
        if len(set(self.build_ids)) != len(self.build_ids) or not (self.build_ids or self.include_checkpoint):
            raise ValueError("请选择模型产物并避免重复")
        return self


class ModelPackageImportOptions(PackageObject):
    """导入新模型或为已有模型追加独立版本。"""

    target_model_id: str | None = Field(default=None, max_length=128)
    model_name: str | None = Field(default=None, max_length=128)
    description: str = Field(default="", max_length=2000)
    analysis_revision: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)
