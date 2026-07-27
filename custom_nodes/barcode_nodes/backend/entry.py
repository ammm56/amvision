"""Barcode 统一节点包 backend entrypoint。"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from types import ModuleType

from backend.service.application.workflows.runtime_registry_loader import (
    NodePackEntrypointRegistrationContext,
)


def _load_node_modules() -> tuple[ModuleType, ...]:
    """加载所有 Barcode 分类中的显式节点模块。"""

    categories_dir = Path(__file__).resolve().parents[1] / "categories"
    modules: list[ModuleType] = []
    for nodes_dir in sorted(categories_dir.glob("*/backend/nodes")):
        category_name = nodes_dir.parents[1].name
        for module_path in sorted(nodes_dir.glob("*.py")):
            if module_path.stem == "__init__" or module_path.stem.startswith("_"):
                continue
            modules.append(
                import_module(
                    "custom_nodes.barcode_nodes.categories."
                    f"{category_name}.backend.nodes.{module_path.stem}"
                )
            )
    return tuple(modules)


def register(context: NodePackEntrypointRegistrationContext) -> None:
    """注册 Barcode 包内全部分类节点。"""

    registered_node_type_ids: set[str] = set()
    for module in _load_node_modules():
        node_type_id = getattr(module, "NODE_TYPE_ID", None)
        handler = getattr(module, "handle_node", None)
        if not isinstance(node_type_id, str) or not callable(handler):
            raise RuntimeError(f"Barcode 节点模块定义无效: {module.__name__}")
        if node_type_id in registered_node_type_ids:
            raise RuntimeError(f"Barcode 节点类型重复: {node_type_id}")
        context.register_python_callable(node_type_id, handler)
        registered_node_type_ids.add(node_type_id)
