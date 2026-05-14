"""本地文件系统节点包加载器实现。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from backend.contracts.nodes.node_pack_manifest import CustomNodeCatalogDocument, NodePackManifest
from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CUSTOM,
    NodeDefinition,
    WorkflowPayloadContract,
)
from backend.nodes.node_pack_loader import NodeCatalogSnapshot
from backend.service.application.errors import ServiceConfigurationError


class LocalNodePackLoader:
    """从本地 custom_nodes 目录扫描 manifest 和自定义节点目录文件。"""

    def __init__(self, custom_nodes_root_dir: str | Path) -> None:
        """初始化本地文件系统节点包加载器。

        参数：
        - custom_nodes_root_dir：自定义节点根目录。
        """

        self.custom_nodes_root_dir = Path(custom_nodes_root_dir).resolve()
        self._catalog_snapshot = NodeCatalogSnapshot()

    def refresh(self) -> None:
        """刷新当前 custom_nodes 根目录中的节点包缓存。"""

        if not self.custom_nodes_root_dir.exists():
            self._catalog_snapshot = NodeCatalogSnapshot()
            return
        if not self.custom_nodes_root_dir.is_dir():
            raise ServiceConfigurationError(
                "custom_nodes 根目录不是有效目录",
                details={"custom_nodes_root_dir": str(self.custom_nodes_root_dir)},
            )

        node_pack_manifests: list[NodePackManifest] = []
        payload_contracts: list[WorkflowPayloadContract] = []
        node_definitions: list[NodeDefinition] = []
        discovered_node_packs: list[tuple[Path, NodePackManifest]] = []

        for node_pack_dir in self._discover_node_pack_directories():
            manifest_path = self._resolve_manifest_path(node_pack_dir)
            if manifest_path is None:
                continue
            manifest = self._load_manifest(manifest_path)
            discovered_node_packs.append((node_pack_dir, manifest))
            node_pack_manifests.append(manifest)

        manifest_index = self._build_manifest_index(node_pack_manifests)
        enabled_manifest_index = {
            manifest.node_pack_id: manifest
            for manifest in node_pack_manifests
            if manifest.enabled_by_default
        }

        for manifest in enabled_manifest_index.values():
            self._validate_enabled_manifest_dependencies(
                manifest=manifest,
                manifest_index=manifest_index,
                enabled_manifest_index=enabled_manifest_index,
            )

        for node_pack_dir, manifest in discovered_node_packs:
            if not manifest.enabled_by_default:
                continue
            custom_node_catalog_path = self._resolve_custom_node_catalog_path(
                node_pack_dir=node_pack_dir,
                manifest=manifest,
            )
            if custom_node_catalog_path is None:
                continue
            custom_node_catalog = self._load_custom_node_catalog(
                manifest=manifest,
                custom_node_catalog_path=custom_node_catalog_path,
            )
            payload_contracts.extend(custom_node_catalog.payload_contracts)
            node_definitions.extend(custom_node_catalog.node_definitions)

        self._catalog_snapshot = NodeCatalogSnapshot(
            node_pack_manifests=tuple(node_pack_manifests),
            payload_contracts=tuple(payload_contracts),
            node_definitions=tuple(node_definitions),
        )

    def get_catalog_snapshot(self) -> NodeCatalogSnapshot:
        """返回当前节点目录快照。"""

        return self._catalog_snapshot

    def get_node_pack_manifests(self) -> tuple[NodePackManifest, ...]:
        """返回已发现的节点包 manifest 列表。"""

        return self._catalog_snapshot.node_pack_manifests

    def get_workflow_payload_contracts(self) -> tuple[WorkflowPayloadContract, ...]:
        """返回已注册的 workflow payload contract 列表。"""

        return self._catalog_snapshot.payload_contracts

    def get_workflow_node_definitions(self) -> tuple[NodeDefinition, ...]:
        """返回已注册的 workflow 节点定义列表。"""

        return self._catalog_snapshot.node_definitions

    def get_runtime_module_search_paths(self) -> tuple[str, ...]:
        """返回导入本地 node pack entrypoint 所需的模块搜索路径。"""

        return (str(self.custom_nodes_root_dir.parent),)

    def _build_manifest_index(
        self,
        node_pack_manifests: list[NodePackManifest],
    ) -> dict[str, NodePackManifest]:
        """按 node_pack_id 构建 manifest 索引。

        参数：
        - node_pack_manifests：当前发现的 manifest 列表。

        返回：
        - dict[str, NodePackManifest]：按 node_pack_id 建立的索引。
        """

        manifest_index: dict[str, NodePackManifest] = {}
        for manifest in node_pack_manifests:
            existing_manifest = manifest_index.get(manifest.node_pack_id)
            if existing_manifest is not None:
                raise ServiceConfigurationError(
                    "发现重复的节点包 id",
                    details={
                        "node_pack_id": manifest.node_pack_id,
                        "existing_version": existing_manifest.version,
                        "duplicated_version": manifest.version,
                    },
                )
            manifest_index[manifest.node_pack_id] = manifest
        return manifest_index

    def _validate_enabled_manifest_dependencies(
        self,
        *,
        manifest: NodePackManifest,
        manifest_index: Mapping[str, NodePackManifest],
        enabled_manifest_index: Mapping[str, NodePackManifest],
    ) -> None:
        """校验启用节点包的依赖是否已经满足。

        参数：
        - manifest：当前准备启用的节点包 manifest。
        - manifest_index：全部已发现 manifest 的索引。
        - enabled_manifest_index：全部已启用 manifest 的索引。
        """

        for dependency in manifest.dependencies:
            dependency_manifest = manifest_index.get(dependency.node_pack_id)
            if dependency_manifest is None:
                raise ServiceConfigurationError(
                    "启用节点包前校验依赖失败：缺少依赖节点包",
                    details={
                        "node_pack_id": manifest.node_pack_id,
                        "dependency_node_pack_id": dependency.node_pack_id,
                        "dependency_version_range": dependency.version_range,
                    },
                )
            if dependency.node_pack_id not in enabled_manifest_index:
                raise ServiceConfigurationError(
                    "启用节点包前校验依赖失败：依赖节点包未启用",
                    details={
                        "node_pack_id": manifest.node_pack_id,
                        "dependency_node_pack_id": dependency.node_pack_id,
                        "dependency_version": dependency_manifest.version,
                        "dependency_enabled_by_default": dependency_manifest.enabled_by_default,
                    },
                )
            if not dependency.matches_version(dependency_manifest.version):
                raise ServiceConfigurationError(
                    "启用节点包前校验依赖失败：依赖节点包版本不满足要求",
                    details={
                        "node_pack_id": manifest.node_pack_id,
                        "dependency_node_pack_id": dependency.node_pack_id,
                        "dependency_version": dependency_manifest.version,
                        "dependency_version_range": dependency.version_range,
                    },
                )

    def _discover_node_pack_directories(self) -> tuple[Path, ...]:
        """返回 custom_nodes 根目录下的一级节点包目录列表。"""

        return tuple(
            sorted(
                (path for path in self.custom_nodes_root_dir.iterdir() if path.is_dir()),
                key=lambda current_path: current_path.name,
            )
        )

    def _resolve_manifest_path(self, node_pack_dir: Path) -> Path | None:
        """解析单个节点包目录下的 manifest 文件路径。"""

        for candidate_path in (
            node_pack_dir / "manifest.json",
            node_pack_dir / "manifest.yaml",
            node_pack_dir / "manifest.yml",
        ):
            if candidate_path.is_file():
                return candidate_path
        return None

    def _load_manifest(self, manifest_path: Path) -> NodePackManifest:
        """读取并校验单个节点包 manifest。"""

        try:
            manifest_payload = self._load_structured_document(manifest_path)
            if not isinstance(manifest_payload, dict):
                raise ServiceConfigurationError(
                    "节点包 manifest 必须是对象",
                    details={"manifest_path": str(manifest_path)},
                )
            return NodePackManifest.model_validate(manifest_payload)
        except ServiceConfigurationError:
            raise
        except Exception as exc:  # pragma: no cover - 防御性异常封装
            raise ServiceConfigurationError(
                "读取节点包 manifest 失败",
                details={"manifest_path": str(manifest_path)},
            ) from exc

    def _resolve_custom_node_catalog_path(
        self,
        *,
        node_pack_dir: Path,
        manifest: NodePackManifest,
    ) -> Path | None:
        """解析节点包目录中的自定义节点目录文件路径。"""

        if manifest.custom_node_catalog_path is not None:
            custom_node_catalog_path = (node_pack_dir / manifest.custom_node_catalog_path).resolve()
            if not custom_node_catalog_path.is_file():
                raise ServiceConfigurationError(
                    "节点包声明的自定义节点目录文件不存在",
                    details={
                        "node_pack_id": manifest.node_pack_id,
                        "custom_node_catalog_path": str(custom_node_catalog_path),
                    },
                )
            return custom_node_catalog_path
        for candidate_path in (
            node_pack_dir / "workflow" / "catalog.json",
            node_pack_dir / "workflow" / "catalog.yaml",
            node_pack_dir / "workflow" / "catalog.yml",
            node_pack_dir / "schemas" / "workflow" / "catalog.json",
            node_pack_dir / "schemas" / "workflow" / "catalog.yaml",
            node_pack_dir / "schemas" / "workflow" / "catalog.yml",
        ):
            if candidate_path.is_file():
                return candidate_path
        return None

    def _load_custom_node_catalog(
        self,
        *,
        manifest: NodePackManifest,
        custom_node_catalog_path: Path,
    ) -> CustomNodeCatalogDocument:
        """读取并校验单个节点包提供的自定义节点目录文件。"""

        try:
            custom_node_catalog_payload = self._load_structured_document(custom_node_catalog_path)
            if not isinstance(custom_node_catalog_payload, dict):
                raise ServiceConfigurationError(
                    "自定义节点目录文件必须是对象",
                    details={"custom_node_catalog_path": str(custom_node_catalog_path)},
                )
            custom_node_catalog = CustomNodeCatalogDocument.model_validate(custom_node_catalog_payload)
        except ServiceConfigurationError:
            raise
        except Exception as exc:  # pragma: no cover - 防御性异常封装
            raise ServiceConfigurationError(
                "读取自定义节点目录文件失败",
                details={
                    "node_pack_id": manifest.node_pack_id,
                    "custom_node_catalog_path": str(custom_node_catalog_path),
                },
            ) from exc

        for node_definition in custom_node_catalog.node_definitions:
            if node_definition.implementation_kind != NODE_IMPLEMENTATION_CUSTOM:
                raise ServiceConfigurationError(
                    "自定义节点目录中的节点必须声明为 custom-node",
                    details={
                        "node_pack_id": manifest.node_pack_id,
                        "node_type_id": node_definition.node_type_id,
                    },
                )
            if (
                node_definition.node_pack_id != manifest.node_pack_id
                or node_definition.node_pack_version != manifest.version
            ):
                raise ServiceConfigurationError(
                    "自定义节点目录中的节点 node_pack_id 或 node_pack_version 与 manifest 不一致",
                    details={
                        "node_pack_id": manifest.node_pack_id,
                        "manifest_version": manifest.version,
                        "node_type_id": node_definition.node_type_id,
                        "node_node_pack_id": node_definition.node_pack_id,
                        "node_node_pack_version": node_definition.node_pack_version,
                    },
                )
        return custom_node_catalog

    def _load_structured_document(self, file_path: Path) -> object:
        """读取 JSON 或 YAML 结构化文档。"""

        raw_text = file_path.read_text(encoding="utf-8")
        if file_path.suffix.lower() == ".json":
            return json.loads(raw_text)
        if file_path.suffix.lower() not in {".yaml", ".yml"}:
            raise ServiceConfigurationError(
                "当前节点文件扩展名不受支持",
                details={"file_path": str(file_path)},
            )
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - 仅在环境缺少 PyYAML 时触发
            raise ServiceConfigurationError(
                "当前环境缺少 PyYAML，无法读取 YAML 节点文件",
                details={"file_path": str(file_path)},
            ) from exc
        return yaml.safe_load(raw_text)
