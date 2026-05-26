"""节点包加载器抽象定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from backend.contracts.nodes.node_pack_manifest import NodePackManifest
from backend.contracts.workflows.workflow_graph import NodeDefinition, WorkflowPayloadContract


@dataclass(frozen=True)
class NodeCatalogSnapshot:
    """描述当前节点系统暴露的节点目录快照。

    字段：
    - node_pack_manifests：已发现的节点包 manifest 列表。
    - payload_contracts：已注册的 payload contract 列表。
    - node_definitions：已注册的 NodeDefinition 列表。
    """

    node_pack_manifests: tuple[NodePackManifest, ...] = ()
    payload_contracts: tuple[WorkflowPayloadContract, ...] = ()
    node_definitions: tuple[NodeDefinition, ...] = ()


@dataclass(frozen=True)
class NodePackStatusIssue:
    """描述一个 node pack 的状态问题。

    字段：
    - severity：问题级别，常用 info、warning、error。
    - code：稳定问题码。
    - message：面向界面的简短消息。
    - details：附加问题细节。
    """

    severity: str
    code: str
    message: str
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class NodePackStatusLog:
    """描述 node pack loader 产生的一条状态日志。

    字段：
    - level：日志级别。
    - message：日志消息。
    - created_at：日志生成时间。
    - details：附加日志细节。
    """

    level: str
    message: str
    created_at: str
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class NodePackDependencyStatus:
    """描述 node pack 依赖状态。

    字段：
    - node_pack_id：依赖的 node pack id。
    - version_range：依赖版本范围。
    - installed：依赖包是否存在。
    - enabled：依赖包是否启用。
    - version：当前发现的依赖包版本。
    - satisfied：依赖是否满足。
    """

    node_pack_id: str
    version_range: str | None = None
    installed: bool = False
    enabled: bool = False
    version: str | None = None
    satisfied: bool = False


@dataclass(frozen=True)
class NodePackStatusItem:
    """描述一个本地 node pack 的只读状态。

    字段：
    - node_pack_id：node pack id；manifest 无法读取时使用目录名。
    - display_name：显示名称。
    - version：版本号。
    - state：loaded、disabled 或 failed。
    - enabled：manifest 当前是否启用。
    - source_dir：node pack 来源目录。
    - manifest_path：manifest 文件路径。
    - custom_node_catalog_path：节点目录文件路径。
    - loaded_at：最近一次 loader 扫描时间。
    - node_count：当前成功加载的节点数量。
    - capabilities：能力标签。
    - permission_scopes：权限 scope。
    - dependencies：依赖状态列表。
    - issues：问题列表。
    - logs：状态日志列表。
    - manifest：manifest JSON 摘要。
    """

    node_pack_id: str
    display_name: str
    version: str | None
    state: str
    enabled: bool
    source_dir: str
    manifest_path: str | None = None
    custom_node_catalog_path: str | None = None
    loaded_at: str | None = None
    node_count: int = 0
    capabilities: tuple[str, ...] = ()
    permission_scopes: tuple[str, ...] = ()
    dependencies: tuple[NodePackDependencyStatus, ...] = ()
    issues: tuple[NodePackStatusIssue, ...] = ()
    logs: tuple[NodePackStatusLog, ...] = ()
    manifest: dict[str, object] | None = None


@dataclass(frozen=True)
class NodePackStatusSnapshot:
    """描述本地 node pack loader 的状态快照。

    字段：
    - generated_at：快照生成时间。
    - custom_nodes_root_dir：当前 custom_nodes 根目录。
    - items：node pack 状态列表。
    - logs：聚合状态日志。
    """

    generated_at: str
    custom_nodes_root_dir: str
    items: tuple[NodePackStatusItem, ...] = ()
    logs: tuple[NodePackStatusLog, ...] = ()


@runtime_checkable
class NodePackLoader(Protocol):
    """描述 backend 当前使用的节点包加载器。"""

    def refresh(self) -> None:
        """刷新当前节点包目录缓存。"""

        ...

    def get_catalog_snapshot(self) -> NodeCatalogSnapshot:
        """返回当前节点目录快照。"""

        ...

    def get_node_pack_manifests(self) -> tuple[NodePackManifest, ...]:
        """返回已发现的节点包 manifest 列表。"""

        ...

    def get_workflow_payload_contracts(self) -> tuple[WorkflowPayloadContract, ...]:
        """返回已注册的 workflow payload contract 列表。"""

        ...

    def get_workflow_node_definitions(self) -> tuple[NodeDefinition, ...]:
        """返回已注册的 workflow 节点定义列表。"""

        ...

    def get_runtime_module_search_paths(self) -> tuple[str, ...]:
        """返回导入 node pack entrypoint 时需要加入的模块搜索路径。"""

        ...
