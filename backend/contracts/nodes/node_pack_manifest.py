"""节点包 manifest 与自定义节点目录文件合同。"""

from __future__ import annotations

from typing import Literal

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.contracts.workflows.workflow_graph import NodeDefinition, WorkflowPayloadContract


NODE_PACK_MANIFEST_FORMAT = "amvision.node-pack-manifest.v1"
CUSTOM_NODE_CATALOG_FORMAT = "amvision.custom-node-catalog.v1"


def _require_stripped_text(value: str, field_name: str) -> str:
    """校验字符串字段非空且去除两端空白后仍然有效。

    参数：
    - value：待校验的字符串值。
    - field_name：字段名称。

    返回：
    - str：去除两端空白后的结果。
    """

    normalized_value = value.strip()
    if not normalized_value:
        raise ValueError(f"{field_name} 不能为空")
    return normalized_value


def _normalize_version_range(value: str) -> str:
    """把版本范围文本规范化为 packaging 可解析的 specifier 字符串。

    参数：
    - value：原始版本范围文本。

    返回：
    - str：规范化后的版本范围字符串。
    """

    normalized_value = _require_stripped_text(value, "version_range")
    return ",".join(segment.strip() for segment in normalized_value.replace(",", " ").split() if segment.strip())


class NodePackDependency(BaseModel):
    """描述单个 node pack 对其他节点包的依赖声明。

    字段：
    - node_pack_id：依赖的目标节点包 id。
    - version_range：可选版本范围；未提供时表示接受任意版本。
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    node_pack_id: str = Field(alias="nodePackId")
    version_range: str | None = Field(default=None, alias="versionRange")

    @model_validator(mode="after")
    def validate_dependency(self) -> NodePackDependency:
        """校验依赖声明字段。"""

        _require_stripped_text(self.node_pack_id, "node_pack_id")
        if self.version_range is not None:
            try:
                SpecifierSet(_normalize_version_range(self.version_range))
            except InvalidSpecifier as exc:
                raise ValueError("version_range 不是有效的版本范围") from exc
        return self

    def matches_version(self, version: str) -> bool:
        """判断给定版本是否满足当前依赖声明。

        参数：
        - version：待匹配的节点包版本。

        返回：
        - bool：是否满足版本范围。
        """

        try:
            resolved_version = Version(_require_stripped_text(version, "version"))
        except InvalidVersion:
            return False
        if self.version_range is None:
            return True
        return resolved_version in SpecifierSet(_normalize_version_range(self.version_range))


class NodePackManifest(BaseModel):
    """描述单个节点包的稳定 manifest。

    字段：
    - format_id：当前节点包 manifest 的格式版本。
    - node_pack_id：节点包稳定唯一标识。
    - version：节点包版本。
    - display_name：节点包显示名称。
    - description：节点包说明。
    - category：节点包主类别。
    - capabilities：节点包能力声明列表。
    - dependencies：当前节点包依赖的其他节点包列表。
    - permission_scopes：节点包声明的权限范围。
    - entrypoints：节点包入口点映射。
    - compatibility：节点包兼容性声明。
    - timeout：节点包默认超时配置。
    - enabled_by_default：当前节点包是否默认启用。
    - custom_node_catalog_path：可选的自定义节点目录文件相对路径。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    format_id: Literal[NODE_PACK_MANIFEST_FORMAT] = NODE_PACK_MANIFEST_FORMAT
    node_pack_id: str = Field(alias="id")
    version: str
    display_name: str = Field(alias="displayName")
    description: str = ""
    category: str
    capabilities: tuple[str, ...] = ()
    dependencies: tuple[NodePackDependency, ...] = ()
    permission_scopes: tuple[str, ...] = Field(default=(), alias="permissionScopes")
    entrypoints: dict[str, str] = Field(default_factory=dict)
    compatibility: dict[str, str] = Field(default_factory=dict)
    timeout: dict[str, object] = Field(default_factory=dict)
    enabled_by_default: bool = Field(default=False, alias="enabledByDefault")
    custom_node_catalog_path: str | None = Field(default=None, alias="customNodeCatalogPath")
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_manifest(self) -> NodePackManifest:
        """校验节点包 manifest 的关键字段。"""

        _require_stripped_text(self.node_pack_id, "node_pack_id")
        normalized_version = _require_stripped_text(self.version, "version")
        try:
            Version(normalized_version)
        except InvalidVersion as exc:
            raise ValueError("version 不是有效的版本字符串") from exc
        _require_stripped_text(self.display_name, "display_name")
        _require_stripped_text(self.category, "category")
        if not self.capabilities:
            raise ValueError("capabilities 不能为空")
        if self.custom_node_catalog_path is not None:
            _require_stripped_text(self.custom_node_catalog_path, "custom_node_catalog_path")
        duplicated_dependency_ids: set[str] = set()
        seen_dependency_ids: set[str] = set()
        for dependency in self.dependencies:
            if dependency.node_pack_id == self.node_pack_id:
                raise ValueError("dependencies 不能依赖自身")
            if dependency.node_pack_id in seen_dependency_ids:
                duplicated_dependency_ids.add(dependency.node_pack_id)
            seen_dependency_ids.add(dependency.node_pack_id)
        if duplicated_dependency_ids:
            duplicated_text = ", ".join(sorted(duplicated_dependency_ids))
            raise ValueError(f"dependencies 存在重复 node_pack_id: {duplicated_text}")
        return self


class CustomNodeCatalogDocument(BaseModel):
    """描述节点包提供的自定义节点目录文件。

    字段：
    - format_id：当前自定义节点目录文件的格式版本。
    - payload_contracts：节点包声明的 payload contract 列表。
    - node_definitions：节点包声明的 NodeDefinition 列表。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[CUSTOM_NODE_CATALOG_FORMAT] = CUSTOM_NODE_CATALOG_FORMAT
    payload_contracts: tuple[WorkflowPayloadContract, ...] = ()
    node_definitions: tuple[NodeDefinition, ...] = ()
    metadata: dict[str, object] = Field(default_factory=dict)
