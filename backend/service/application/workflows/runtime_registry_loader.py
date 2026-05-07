"""workflow 节点运行时注册表加载器。"""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, Mapping, Protocol, cast

from backend.contracts.nodes.node_pack_manifest import NodePackManifest
from backend.contracts.workflows.workflow_graph import NodeDefinition
from backend.nodes.core_runtime_handlers import register_core_node_handlers
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.nodes.node_pack_loader import NodePackLoader
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
    WorkflowNodeRuntimeRegistry,
)


SUPPORTED_EXECUTABLE_RUNTIME_KINDS = frozenset({"python-callable", "worker-task"})
BACKEND_ENTRYPOINT_NAME = "backend"

WorkflowNodeHandler = Callable[[WorkflowNodeExecutionRequest], dict[str, object]]


@dataclass(frozen=True)
class NodePackEntrypointRegistrationContext:
    """描述单个 node pack backend entrypoint 接收到的注册上下文。

    字段：
    - manifest：当前 node pack manifest。
    - runtime_registry：要写入 handler 的 workflow 节点运行时注册表。
    - node_definitions_by_type_id：当前 node pack 提供的节点定义索引。
    """

    manifest: NodePackManifest
    runtime_registry: WorkflowNodeRuntimeRegistry
    node_definitions_by_type_id: Mapping[str, NodeDefinition]

    def list_node_definitions(self) -> tuple[NodeDefinition, ...]:
        """返回当前 node pack 提供的全部节点定义。

        返回：
        - tuple[NodeDefinition, ...]：当前 node pack 的节点定义元组。
        """

        return tuple(self.node_definitions_by_type_id.values())

    def get_node_definition(self, node_type_id: str) -> NodeDefinition:
        """按节点类型 id 返回当前 node pack 的节点定义。

        参数：
        - node_type_id：节点类型 id。

        返回：
        - NodeDefinition：对应的节点定义。
        """

        node_definition = self.node_definitions_by_type_id.get(node_type_id)
        if node_definition is None:
            raise ServiceConfigurationError(
                "node pack entrypoint 引用了未声明的节点定义",
                details={
                    "node_pack_id": self.manifest.node_pack_id,
                    "node_type_id": node_type_id,
                },
            )
        return node_definition

    def register_python_callable(
        self,
        node_type_id: str,
        handler: WorkflowNodeHandler,
    ) -> None:
        """为当前 node pack 的 python-callable 节点注册 handler。

        参数：
        - node_type_id：节点类型 id。
        - handler：节点执行 handler。
        """

        node_definition = self.get_node_definition(node_type_id)
        self.runtime_registry.register_python_callable(node_definition, handler)

    def register_worker_task(
        self,
        node_type_id: str,
        handler: WorkflowNodeHandler,
    ) -> None:
        """为当前 node pack 的 worker-task 节点注册 handler。

        参数：
        - node_type_id：节点类型 id。
        - handler：节点执行 handler。
        """

        node_definition = self.get_node_definition(node_type_id)
        self.runtime_registry.register_worker_task(node_definition, handler)


class NodePackBackendEntrypoint(Protocol):
    """描述 node pack backend entrypoint 的注册函数签名。"""

    def __call__(self, context: NodePackEntrypointRegistrationContext) -> None:
        """把当前 node pack 的 handler 注册到 workflow 运行时注册表。"""

        ...


class WorkflowNodeRuntimeRegistryLoader:
    """根据统一节点目录与 node pack entrypoint 刷新 workflow 运行时注册表。"""

    def __init__(
        self,
        *,
        node_catalog_registry: NodeCatalogRegistry,
        node_pack_loader: NodePackLoader,
    ) -> None:
        """初始化 workflow 节点运行时注册表加载器。

        参数：
        - node_catalog_registry：统一节点目录注册表。
        - node_pack_loader：node pack 目录加载器。
        """

        self.node_catalog_registry = node_catalog_registry
        self.node_pack_loader = node_pack_loader
        self._runtime_registry = WorkflowNodeRuntimeRegistry()

    def refresh(self) -> None:
        """刷新当前 workflow 节点运行时注册表。"""

        self._runtime_registry.clear()
        for node_definition in self.node_catalog_registry.get_workflow_node_definitions():
            self._runtime_registry.register_node_definition(node_definition)
        register_core_node_handlers(self._runtime_registry)

        node_definitions_by_pack_key = self._build_node_pack_definition_index()
        for manifest in self.node_pack_loader.get_node_pack_manifests():
            node_definitions = node_definitions_by_pack_key.get((manifest.node_pack_id, manifest.version), ())
            if not node_definitions:
                continue
            self._register_node_pack_handlers(
                manifest=manifest,
                node_definitions=node_definitions,
            )

    def get_runtime_registry(self) -> WorkflowNodeRuntimeRegistry:
        """返回当前 workflow 节点运行时注册表。"""

        return self._runtime_registry

    def _build_node_pack_definition_index(self) -> dict[tuple[str, str], tuple[NodeDefinition, ...]]:
        """按 node pack 键构建当前启用节点定义索引。"""

        grouped_node_definitions: dict[tuple[str, str], list[NodeDefinition]] = {}
        for node_definition in self.node_pack_loader.get_workflow_node_definitions():
            if node_definition.node_pack_id is None or node_definition.node_pack_version is None:
                continue
            pack_key = (node_definition.node_pack_id, node_definition.node_pack_version)
            grouped_node_definitions.setdefault(pack_key, []).append(node_definition)
        return {
            pack_key: tuple(node_definitions)
            for pack_key, node_definitions in grouped_node_definitions.items()
        }

    def _register_node_pack_handlers(
        self,
        *,
        manifest: NodePackManifest,
        node_definitions: tuple[NodeDefinition, ...],
    ) -> None:
        """导入 node pack backend entrypoint 并注册处理函数。"""

        backend_entrypoint = manifest.entrypoints.get(BACKEND_ENTRYPOINT_NAME)
        executable_node_definitions = tuple(
            node_definition
            for node_definition in node_definitions
            if node_definition.runtime_kind in SUPPORTED_EXECUTABLE_RUNTIME_KINDS
        )
        if not executable_node_definitions:
            return
        if backend_entrypoint is None:
            raise ServiceConfigurationError(
                "可执行 custom node 缺少 backend entrypoint",
                details={
                    "node_pack_id": manifest.node_pack_id,
                    "node_pack_version": manifest.version,
                    "node_type_ids": [node.node_type_id for node in executable_node_definitions],
                },
            )

        entrypoint_callable = self._load_backend_entrypoint(
            manifest=manifest,
            backend_entrypoint=backend_entrypoint,
        )
        registration_context = NodePackEntrypointRegistrationContext(
            manifest=manifest,
            runtime_registry=self._runtime_registry,
            node_definitions_by_type_id={
                node_definition.node_type_id: node_definition for node_definition in node_definitions
            },
        )
        try:
            entrypoint_callable(registration_context)
        except ServiceConfigurationError:
            raise
        except Exception as exc:  # pragma: no cover - 防御性异常封装
            raise ServiceConfigurationError(
                "执行 node pack backend entrypoint 失败",
                details={
                    "node_pack_id": manifest.node_pack_id,
                    "node_pack_version": manifest.version,
                    "backend_entrypoint": backend_entrypoint,
                },
            ) from exc

        for node_definition in executable_node_definitions:
            if not self._runtime_registry.has_registered_handler(node_definition=node_definition):
                raise ServiceConfigurationError(
                    "node pack backend entrypoint 未完成全部 handler 注册",
                    details={
                        "node_pack_id": manifest.node_pack_id,
                        "node_pack_version": manifest.version,
                        "node_type_id": node_definition.node_type_id,
                        "runtime_kind": node_definition.runtime_kind,
                        "backend_entrypoint": backend_entrypoint,
                    },
                )

    def _load_backend_entrypoint(
        self,
        *,
        manifest: NodePackManifest,
        backend_entrypoint: str,
    ) -> NodePackBackendEntrypoint:
        """解析并导入单个 node pack 的 backend entrypoint。"""

        module_name, separator, attribute_name = backend_entrypoint.partition(":")
        if not separator or not module_name or not attribute_name:
            raise ServiceConfigurationError(
                "node pack backend entrypoint 格式无效",
                details={
                    "node_pack_id": manifest.node_pack_id,
                    "backend_entrypoint": backend_entrypoint,
                },
            )

        with self._prepend_runtime_module_search_paths():
            self._clear_cached_runtime_module(module_name)
            try:
                imported_module = importlib.import_module(module_name)
            except Exception as exc:  # pragma: no cover - 防御性异常封装
                raise ServiceConfigurationError(
                    "导入 node pack backend module 失败",
                    details={
                        "node_pack_id": manifest.node_pack_id,
                        "backend_entrypoint": backend_entrypoint,
                        "module_name": module_name,
                    },
                ) from exc

        entrypoint_callable = getattr(imported_module, attribute_name, None)
        if not callable(entrypoint_callable):
            raise ServiceConfigurationError(
                "node pack backend entrypoint 不可调用",
                details={
                    "node_pack_id": manifest.node_pack_id,
                    "backend_entrypoint": backend_entrypoint,
                    "attribute_name": attribute_name,
                },
            )
        return cast(NodePackBackendEntrypoint, entrypoint_callable)

    def _clear_cached_runtime_module(self, module_name: str) -> None:
        """清理当前 entrypoint 及其父包的模块缓存。

        参数：
        - module_name：准备重新导入的完整模块名。

        说明：
        - custom_nodes 允许来自不同目录的同名 node pack 在测试或刷新阶段重复装载。
        - 这里在正式导入前移除当前模块及其父包，避免 Python 继续复用旧目录下的缓存对象。
        """

        module_name_parts = module_name.split(".")
        for current_index in range(len(module_name_parts), 0, -1):
            cached_module_name = ".".join(module_name_parts[:current_index])
            sys.modules.pop(cached_module_name, None)

    @contextmanager
    def _prepend_runtime_module_search_paths(self) -> Iterator[None]:
        """临时把 node pack 模块搜索路径加入 sys.path 头部。"""

        original_sys_path = list(sys.path)
        module_search_paths = tuple(
            current_path
            for current_path in self.node_pack_loader.get_runtime_module_search_paths()
            if current_path
        )
        try:
            for module_search_path in reversed(module_search_paths):
                if module_search_path in sys.path:
                    sys.path.remove(module_search_path)
                sys.path.insert(0, module_search_path)
            importlib.invalidate_caches()
            yield
        finally:
            sys.path[:] = original_sys_path
            importlib.invalidate_caches()