"""本地文件系统节点包加载器实现。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

from backend.contracts.nodes.node_pack_manifest import CustomNodeCatalogDocument, NodePackManifest
from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CUSTOM,
    NodeDefinition,
    WorkflowPayloadContract,
)
from backend.nodes.node_pack_loader import NodeCatalogSnapshot
from backend.nodes.node_pack_loader import (
    NodePackDependencyStatus,
    NodePackStatusIssue,
    NodePackStatusItem,
    NodePackStatusLog,
    NodePackStatusSnapshot,
)
from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError


class LocalNodePackLoader:
    """从本地 custom_nodes 目录扫描 manifest 和自定义节点目录文件。"""

    def __init__(self, custom_nodes_root_dir: str | Path) -> None:
        """初始化本地文件系统节点包加载器。

        参数：
        - custom_nodes_root_dir：自定义节点根目录。
        """

        self.custom_nodes_root_dir = Path(custom_nodes_root_dir).resolve()
        self._catalog_snapshot = NodeCatalogSnapshot()
        self._last_refresh_at: str | None = None
        self._last_status_snapshot = self.inspect_node_pack_status()

    def refresh(self) -> None:
        """刷新当前 custom_nodes 根目录中的节点包缓存。"""

        if not self.custom_nodes_root_dir.exists():
            self._catalog_snapshot = NodeCatalogSnapshot()
            self._last_refresh_at = _utc_now()
            self._last_status_snapshot = self.inspect_node_pack_status()
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
            try:
                manifest = self._load_manifest(manifest_path)
            except ServiceConfigurationError:
                continue
            discovered_node_packs.append((node_pack_dir, manifest))
            node_pack_manifests.append(manifest)

        manifest_index, duplicated_manifest_ids = self._build_non_throwing_manifest_index(node_pack_manifests)
        enabled_manifest_index = {
            manifest.node_pack_id: manifest
            for manifest in node_pack_manifests
            if manifest.enabled_by_default and manifest.node_pack_id not in duplicated_manifest_ids
        }

        for node_pack_dir, manifest in discovered_node_packs:
            if not manifest.enabled_by_default or manifest.node_pack_id in duplicated_manifest_ids:
                continue
            dependency_statuses = self._build_dependency_statuses(
                manifest=manifest,
                manifest_index=manifest_index,
                enabled_manifest_index=enabled_manifest_index,
            )
            if any(not dependency.satisfied for dependency in dependency_statuses):
                continue
            try:
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
            except ServiceConfigurationError:
                continue
            payload_contracts.extend(custom_node_catalog.payload_contracts)
            node_definitions.extend(custom_node_catalog.node_definitions)

        self._catalog_snapshot = NodeCatalogSnapshot(
            node_pack_manifests=tuple(node_pack_manifests),
            payload_contracts=_merge_payload_contracts(payload_contracts),
            node_definitions=tuple(node_definitions),
        )
        self._last_refresh_at = _utc_now()
        self._last_status_snapshot = self.inspect_node_pack_status()

    def reload(self) -> NodePackStatusSnapshot:
        """重新加载本地 node pack，并返回最新状态快照。"""

        self.refresh()
        return self.get_node_pack_status_snapshot()

    def validate(self, node_pack_id: str | None = None) -> NodePackStatusSnapshot:
        """只读校验当前 node pack 状态。

        参数：
        - node_pack_id：可选 node pack id；提供时只返回该节点包状态。

        返回：
        - NodePackStatusSnapshot：校验后的状态快照。
        """

        snapshot = self.inspect_node_pack_status()
        if node_pack_id is None:
            return snapshot
        matched_items = tuple(item for item in snapshot.items if item.node_pack_id == node_pack_id)
        if not matched_items:
            raise InvalidRequestError(
                "节点包不存在",
                details={"node_pack_id": node_pack_id},
            )
        return NodePackStatusSnapshot(
            generated_at=snapshot.generated_at,
            custom_nodes_root_dir=snapshot.custom_nodes_root_dir,
            items=matched_items,
            logs=tuple(log for item in matched_items for log in item.logs),
        )

    def get_node_pack_status_snapshot(self) -> NodePackStatusSnapshot:
        """返回最近一次可用的 node pack 状态快照。"""

        self._last_status_snapshot = self.inspect_node_pack_status()
        return self._last_status_snapshot

    def get_node_pack_logs(self, node_pack_id: str) -> tuple[NodePackStatusLog, ...]:
        """返回指定 node pack 的状态日志。"""

        snapshot = self.validate(node_pack_id)
        return snapshot.items[0].logs

    def set_node_pack_enabled(self, node_pack_id: str, enabled: bool) -> NodePackStatusSnapshot:
        """启用或禁用本地 JSON manifest 中的 node pack。

        参数：
        - node_pack_id：目标 node pack id。
        - enabled：是否启用。

        返回：
        - NodePackStatusSnapshot：操作后的状态快照。
        """

        snapshot = self.inspect_node_pack_status()
        target = next((item for item in snapshot.items if item.node_pack_id == node_pack_id), None)
        if target is None:
            raise InvalidRequestError("节点包不存在", details={"node_pack_id": node_pack_id})
        if target.manifest_path is None:
            raise InvalidRequestError("节点包缺少 manifest，无法修改启用状态", details={"node_pack_id": node_pack_id})
        manifest_path = Path(target.manifest_path)
        if manifest_path.suffix.lower() != ".json":
            raise InvalidRequestError(
                "当前只支持修改 JSON manifest 的启用状态",
                details={"node_pack_id": node_pack_id, "manifest_path": str(manifest_path)},
            )
        if not enabled:
            blocking_dependents = [
                item.node_pack_id
                for item in snapshot.items
                if item.enabled
                and item.node_pack_id != node_pack_id
                and any(dependency.node_pack_id == node_pack_id for dependency in item.dependencies)
            ]
            if blocking_dependents:
                raise InvalidRequestError(
                    "存在已启用节点包依赖当前节点包，无法禁用",
                    details={"node_pack_id": node_pack_id, "dependent_node_pack_ids": blocking_dependents},
                )
        else:
            for dependency in target.dependencies:
                if not dependency.satisfied:
                    raise InvalidRequestError(
                        "节点包依赖未满足，无法启用",
                        details={
                            "node_pack_id": node_pack_id,
                            "dependency_node_pack_id": dependency.node_pack_id,
                            "dependency_version_range": dependency.version_range,
                        },
                    )

        original_text = manifest_path.read_text(encoding="utf-8")
        payload = json.loads(original_text)
        if not isinstance(payload, dict):
            raise InvalidRequestError("节点包 manifest 必须是对象", details={"manifest_path": str(manifest_path)})
        payload["enabledByDefault"] = enabled
        NodePackManifest.model_validate(payload)
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            return self.reload()
        except Exception:
            manifest_path.write_text(original_text, encoding="utf-8")
            self.refresh()
            raise

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

    def inspect_node_pack_status(self) -> NodePackStatusSnapshot:
        """扫描 custom_nodes 根目录并返回 node pack 状态快照。"""

        generated_at = _utc_now()
        if not self.custom_nodes_root_dir.exists() or not self.custom_nodes_root_dir.is_dir():
            log = NodePackStatusLog(
                level="warning",
                message="custom_nodes 根目录不存在或不是目录",
                created_at=generated_at,
                details={"custom_nodes_root_dir": str(self.custom_nodes_root_dir)},
            )
            return NodePackStatusSnapshot(
                generated_at=generated_at,
                custom_nodes_root_dir=str(self.custom_nodes_root_dir),
                logs=(log,),
            )

        raw_items: list[tuple[Path, Path | None, NodePackManifest | None, NodePackStatusIssue | None]] = []
        for node_pack_dir in self._discover_node_pack_directories():
            manifest_path = self._resolve_manifest_path(node_pack_dir)
            if manifest_path is None:
                raw_items.append(
                    (
                        node_pack_dir,
                        None,
                        None,
                        NodePackStatusIssue(
                            severity="error",
                            code="manifest_missing",
                            message="节点包缺少 manifest 文件",
                            details={"source_dir": str(node_pack_dir)},
                        ),
                    )
                )
                continue
            try:
                manifest = self._load_manifest(manifest_path)
            except Exception as error:
                raw_items.append(
                    (
                        node_pack_dir,
                        manifest_path,
                        None,
                        self._build_issue_from_error(
                            error=error,
                            code="manifest_invalid",
                            fallback_message="节点包 manifest 校验失败",
                            details={"manifest_path": str(manifest_path)},
                        ),
                    )
                )
                continue
            raw_items.append((node_pack_dir, manifest_path, manifest, None))

        valid_manifests = [manifest for _, _, manifest, _ in raw_items if manifest is not None]
        manifest_index: dict[str, NodePackManifest] = {}
        duplicated_manifest_ids: set[str] = set()
        for manifest in valid_manifests:
            if manifest.node_pack_id in manifest_index:
                duplicated_manifest_ids.add(manifest.node_pack_id)
            else:
                manifest_index[manifest.node_pack_id] = manifest
        enabled_manifest_index = {
            manifest.node_pack_id: manifest
            for manifest in valid_manifests
            if manifest.enabled_by_default and manifest.node_pack_id not in duplicated_manifest_ids
        }
        items = tuple(
            self._build_node_pack_status_item(
                node_pack_dir=node_pack_dir,
                manifest_path=manifest_path,
                manifest=manifest,
                manifest_issue=manifest_issue,
                manifest_index=manifest_index,
                enabled_manifest_index=enabled_manifest_index,
                duplicated_manifest_ids=duplicated_manifest_ids,
                generated_at=generated_at,
            )
            for node_pack_dir, manifest_path, manifest, manifest_issue in raw_items
        )
        logs = tuple(log for item in items for log in item.logs)
        return NodePackStatusSnapshot(
            generated_at=generated_at,
            custom_nodes_root_dir=str(self.custom_nodes_root_dir),
            items=items,
            logs=logs,
        )

    def _build_node_pack_status_item(
        self,
        *,
        node_pack_dir: Path,
        manifest_path: Path | None,
        manifest: NodePackManifest | None,
        manifest_issue: NodePackStatusIssue | None,
        manifest_index: Mapping[str, NodePackManifest],
        enabled_manifest_index: Mapping[str, NodePackManifest],
        duplicated_manifest_ids: set[str],
        generated_at: str,
    ) -> NodePackStatusItem:
        """构造单个 node pack 的状态项。"""

        if manifest is None:
            issue = manifest_issue or NodePackStatusIssue(
                severity="error",
                code="manifest_invalid",
                message="节点包 manifest 校验失败",
                details={"manifest_path": str(manifest_path) if manifest_path is not None else None},
            )
            log = self._build_log_from_issue(issue=issue, created_at=generated_at)
            return NodePackStatusItem(
                node_pack_id=node_pack_dir.name,
                display_name=node_pack_dir.name,
                version=None,
                state="failed",
                enabled=False,
                source_dir=str(node_pack_dir),
                manifest_path=str(manifest_path) if manifest_path is not None else None,
                loaded_at=generated_at,
                issues=(issue,),
                logs=(log,),
            )

        dependencies = self._build_dependency_statuses(
            manifest=manifest,
            manifest_index=manifest_index,
            enabled_manifest_index=enabled_manifest_index,
        )
        issues: list[NodePackStatusIssue] = []
        custom_node_catalog_path: Path | None = None
        node_count = 0
        state = "loaded"
        if manifest.node_pack_id in duplicated_manifest_ids:
            issues.append(
                NodePackStatusIssue(
                    severity="error",
                    code="duplicate_node_pack_id",
                    message="发现重复的节点包 id",
                    details={"node_pack_id": manifest.node_pack_id},
                )
            )
            state = "failed"
        elif not manifest.enabled_by_default:
            state = "disabled"
        else:
            missing_dependency = next((dependency for dependency in dependencies if not dependency.satisfied), None)
            if missing_dependency is not None:
                issues.append(
                    NodePackStatusIssue(
                        severity="error",
                        code="dependency_unsatisfied",
                        message="节点包依赖未满足",
                        details={
                            "node_pack_id": manifest.node_pack_id,
                            "dependency_node_pack_id": missing_dependency.node_pack_id,
                            "dependency_version_range": missing_dependency.version_range,
                            "dependency_version": missing_dependency.version,
                            "dependency_enabled": missing_dependency.enabled,
                        },
                    )
                )
                state = "failed"
            else:
                try:
                    custom_node_catalog_path = self._resolve_custom_node_catalog_path(
                        node_pack_dir=node_pack_dir,
                        manifest=manifest,
                    )
                    if custom_node_catalog_path is None:
                        issues.append(
                            NodePackStatusIssue(
                                severity="warning",
                                code="catalog_missing",
                                message="节点包未提供自定义节点目录文件",
                                details={"node_pack_id": manifest.node_pack_id},
                            )
                        )
                    else:
                        custom_node_catalog = self._load_custom_node_catalog(
                            manifest=manifest,
                            custom_node_catalog_path=custom_node_catalog_path,
                        )
                        node_count = len(custom_node_catalog.node_definitions)
                        if node_count == 0:
                            issues.append(
                                NodePackStatusIssue(
                                    severity="warning",
                                    code="no_node_definitions",
                                    message="节点包没有节点定义",
                                    details={"node_pack_id": manifest.node_pack_id},
                                )
                            )
                except Exception as error:
                    issues.append(
                        self._build_issue_from_error(
                            error=error,
                            code="catalog_invalid",
                            fallback_message="节点包目录文件校验失败",
                            details={"node_pack_id": manifest.node_pack_id},
                        )
                    )
                    state = "failed"

        logs = tuple(self._build_log_from_issue(issue=issue, created_at=generated_at) for issue in issues)
        if not logs:
            logs = (
                NodePackStatusLog(
                    level="info",
                    message="节点包状态正常" if state == "loaded" else "节点包已禁用",
                    created_at=generated_at,
                    details={"node_pack_id": manifest.node_pack_id, "state": state},
                ),
            )
        return NodePackStatusItem(
            node_pack_id=manifest.node_pack_id,
            display_name=manifest.display_name,
            version=manifest.version,
            state=state,
            enabled=manifest.enabled_by_default,
            source_dir=str(node_pack_dir),
            manifest_path=str(manifest_path) if manifest_path is not None else None,
            custom_node_catalog_path=str(custom_node_catalog_path) if custom_node_catalog_path is not None else None,
            loaded_at=self._last_refresh_at or generated_at,
            node_count=node_count,
            capabilities=manifest.capabilities,
            permission_scopes=manifest.permission_scopes,
            dependencies=dependencies,
            issues=tuple(issues),
            logs=logs,
            manifest=manifest.model_dump(mode="json", by_alias=True),
        )

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

    def _build_non_throwing_manifest_index(
        self,
        node_pack_manifests: list[NodePackManifest],
    ) -> tuple[dict[str, NodePackManifest], set[str]]:
        """按 node_pack_id 构建索引，并返回重复 id 集合。

        参数：
        - node_pack_manifests：当前发现的 manifest 列表。

        返回：
        - tuple[dict[str, NodePackManifest], set[str]]：manifest 索引和重复 node_pack_id 集合。
        """

        manifest_index: dict[str, NodePackManifest] = {}
        duplicated_manifest_ids: set[str] = set()
        for manifest in node_pack_manifests:
            if manifest.node_pack_id in manifest_index:
                duplicated_manifest_ids.add(manifest.node_pack_id)
                continue
            manifest_index[manifest.node_pack_id] = manifest
        return manifest_index, duplicated_manifest_ids

    def _build_dependency_statuses(
        self,
        *,
        manifest: NodePackManifest,
        manifest_index: Mapping[str, NodePackManifest],
        enabled_manifest_index: Mapping[str, NodePackManifest],
    ) -> tuple[NodePackDependencyStatus, ...]:
        """构造当前 node pack 的依赖状态列表。"""

        dependency_statuses: list[NodePackDependencyStatus] = []
        for dependency in manifest.dependencies:
            dependency_manifest = manifest_index.get(dependency.node_pack_id)
            enabled = dependency.node_pack_id in enabled_manifest_index
            version = dependency_manifest.version if dependency_manifest is not None else None
            dependency_statuses.append(
                NodePackDependencyStatus(
                    node_pack_id=dependency.node_pack_id,
                    version_range=dependency.version_range,
                    installed=dependency_manifest is not None,
                    enabled=enabled,
                    version=version,
                    satisfied=dependency_manifest is not None and enabled and dependency.matches_version(dependency_manifest.version),
                )
            )
        return tuple(dependency_statuses)

    def _build_issue_from_error(
        self,
        *,
        error: Exception,
        code: str,
        fallback_message: str,
        details: dict[str, object],
    ) -> NodePackStatusIssue:
        """把异常转换为状态问题。"""

        if isinstance(error, ServiceConfigurationError):
            merged_details = dict(details)
            merged_details.update(error.details)
            return NodePackStatusIssue(
                severity="error",
                code=code,
                message=error.message,
                details=merged_details,
            )
        return NodePackStatusIssue(
            severity="error",
            code=code,
            message=fallback_message,
            details={**details, "error": str(error)},
        )

    def _build_log_from_issue(
        self,
        *,
        issue: NodePackStatusIssue,
        created_at: str,
    ) -> NodePackStatusLog:
        """把状态问题转换为页面可读日志。"""

        return NodePackStatusLog(
            level=issue.severity,
            message=issue.message,
            created_at=created_at,
            details={"code": issue.code, **issue.details},
        )

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
                (path for path in self.custom_nodes_root_dir.iterdir() if path.is_dir() and self._is_node_pack_candidate_dir(path)),
                key=lambda current_path: current_path.name,
            )
        )

    def _is_node_pack_candidate_dir(self, path: Path) -> bool:
        """判断目录是否应作为 node pack 候选目录扫描。

        参数：
        - path：待判断的一级目录。

        返回：
        - bool：是否作为 node pack 候选目录。
        """

        directory_name = path.name
        return not (
            directory_name == "__pycache__"
            or directory_name.startswith(".")
            or directory_name.startswith("_")
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


def _utc_now() -> str:
    """返回 ISO 8601 UTC 时间字符串。"""

    return datetime.now(UTC).isoformat()


def _merge_payload_contracts(
    payload_contracts: list[WorkflowPayloadContract],
) -> tuple[WorkflowPayloadContract, ...]:
    """合并多个节点包收集到的 payload contract。"""

    merged_contracts: list[WorkflowPayloadContract] = []
    contract_index: dict[str, WorkflowPayloadContract] = {}
    for contract in payload_contracts:
        existing_contract = contract_index.get(contract.payload_type_id)
        if existing_contract is None:
            contract_index[contract.payload_type_id] = contract
            merged_contracts.append(contract)
            continue
        if existing_contract.model_dump(mode="json") != contract.model_dump(mode="json"):
            raise ServiceConfigurationError(
                "发现重复且定义不一致的 payload contract",
                details={"payload_type_id": contract.payload_type_id},
            )
    return tuple(merged_contracts)
