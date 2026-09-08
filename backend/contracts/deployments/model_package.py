"""单个模型部署的离线包及导入选项契约，不包含运行中的进程状态。"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PackageObject(BaseModel):
    """拒绝未知控制字段；运行参数中的扩展对象由原运行时校验。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)


def safe_package_path(value: str) -> str:
    """校验可在 Windows/Linux 中一致解释的相对文件路径。"""
    if not value or "\\" in value or ":" in value or value.startswith("/"):
        raise ValueError("包内路径必须为相对 POSIX 路径")
    parts = value.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if any(p in {"", ".", ".."} or p.endswith((".", " ")) or p.split(".")[0].upper() in reserved or re.search(r'[<>"|?*\x00-\x1f]', p) for p in parts):
        raise ValueError("包内路径含不安全的目录或文件名")
    return PurePosixPath(value).as_posix()


class PackageFile(PackageObject):
    """一个版本或 Build 拥有的文件及完整性信息。"""

    key: str = Field(min_length=1, max_length=128)
    owner: Literal["version", "build"]
    path: str
    logical_name: str
    file_type: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    byte_size: int = Field(ge=0)

    _path = field_validator("path")(safe_package_path)


class PortableModel(PackageObject):
    """目标模型的必要分类字段，源项目不成为目标身份。"""

    model_id: str
    model_name: str
    model_type: str
    task_type: Literal["detection", "classification", "segmentation", "pose", "obb"]
    model_scale: str


class PortableVersion(PackageObject):
    """模型版本的运行信息和仅用于追溯的来源摘要。"""

    model_version_id: str
    metadata: dict[str, object] = Field(default_factory=dict)
    provenance: dict[str, str | None] = Field(default_factory=dict)


class PortableBuild(PackageObject):
    """所选转换产物的运行格式和能力。"""

    model_build_id: str
    build_format: Literal["onnx", "onnx-optimized", "openvino-ir", "tensorrt-engine", "rknn"]
    runtime_backend: str
    runtime_precision: str
    runtime_profile_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    provenance: dict[str, str | None] = Field(default_factory=dict)


class PortableDeployment(PackageObject):
    """部署配置；不允许传入 desired_state 或 PID。"""

    deployment_instance_id: str
    display_name: str
    runtime_backend: Literal["pytorch", "onnxruntime", "openvino", "tensorrt", "rknn"]
    device_name: str
    runtime_profile_id: str | None = None
    runtime_configuration: dict[str, object]


class PortableInference(PackageObject):
    """固定推理语义；文件使用包内 key 引用，不接受本机 URI。"""

    runtime_precision: str
    input_size: dict[str, int]
    model_input_spec: dict[str, object] | None = None
    labels: list[str] = Field(min_length=1)
    model_options: dict[str, object] = Field(default_factory=dict, alias="model_config")
    model_build_metadata: dict[str, object] = Field(default_factory=dict)
    runtime_file: str
    checkpoint_file: str | None = None
    labels_file: str | None = None

    @field_validator("input_size")
    @classmethod
    def validate_size(cls, value: dict[str, int]) -> dict[str, int]:
        """宽高必须显式命名且为正数，避免元组顺序歧义。"""
        if set(value) != {"width", "height"} or min(value.values()) <= 0:
            raise ValueError("input_size 必须包含正数 width 和 height")
        return value


class ModelDeploymentPackage(PackageObject):
    """一个可重建模型部署的文件清单。"""

    format_id: Literal["amvision.model-deployment.v1"] = "amvision.model-deployment.v1"
    package_id: str
    source_version: str
    created_at: str
    deployment: PortableDeployment
    model: PortableModel
    model_version: PortableVersion
    model_build: PortableBuild | None = None
    inference: PortableInference
    files: list[PackageFile] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def validate_references(self) -> ModelDeploymentPackage:
        """验证唯一文件、单版本/Build 归属及运行文件引用。"""
        keys = {f.key: f for f in self.files}
        paths = {f"{f.owner}/{f.path}".casefold() for f in self.files}
        if len(keys) != len(self.files) or len(paths) != len(self.files):
            raise ValueError("文件 key 或规范化路径重复")
        if self.model_build is None and any(f.owner == "build" for f in self.files):
            raise ValueError("没有 Build 却包含 Build 文件")
        for key in (self.inference.runtime_file, self.inference.checkpoint_file, self.inference.labels_file):
            if key is not None and key not in keys:
                raise ValueError(f"推理引用了不存在的文件 {key}")
        expected_owner = "build" if self.model_build else "version"
        if keys[self.inference.runtime_file].owner != expected_owner:
            raise ValueError("运行文件归属不正确")
        if self.model_build and (self.model_build.runtime_backend != self.deployment.runtime_backend or self.model_build.runtime_precision != self.inference.runtime_precision):
            raise ValueError("Build 与部署后端/精度不一致")
        return self


class ImportOptions(PackageObject):
    """目标设置；项目由授权后的 URL 指定，禁止传入磁盘路径。"""

    display_name: str | None = Field(default=None, max_length=128)
    device_name: str | None = None
    instance_count: int | None = Field(default=None, ge=1, le=1024)
    runtime_configuration: dict[str, object] | None = None
    create_copy: bool = False
    analysis_revision: str | None = None
    idempotency_key: str | None = Field(default=None, max_length=128)


class TransferLimits(PackageObject):
    """服务侧资源限制和短期文件保留策略。"""

    max_package_bytes: int = Field(default=32 * 1024**3, ge=1)
    max_unpacked_bytes: int = Field(default=64 * 1024**3, ge=1)
    max_manifest_bytes: int = Field(default=8 * 1024**2, ge=1)
    max_entries: int = Field(default=10001, ge=2)
    temporary_retention_hours: int = Field(default=24, ge=1)
    receipt_retention_days: int = Field(default=7, ge=1)
