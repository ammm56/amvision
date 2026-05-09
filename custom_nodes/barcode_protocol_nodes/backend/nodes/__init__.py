"""Barcode/QR 协议节点实现集合。"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from types import ModuleType


def _iter_node_module_names() -> tuple[str, ...]:
    """返回 backend/nodes 目录下全部节点模块名称。

    返回：
    - tuple[str, ...]：按文件名排序的模块名集合。
    """

    nodes_dir = Path(__file__).resolve().parent
    return tuple(
        sorted(
            file_path.stem
            for file_path in nodes_dir.glob("*.py")
            if file_path.is_file() and file_path.stem != "__init__" and not file_path.stem.startswith("_")
        )
    )


def _load_node_modules() -> tuple[ModuleType, ...]:
    """导入 backend/nodes 目录下的全部显式节点模块。

    返回：
    - tuple[ModuleType, ...]：节点模块对象列表。
    """

    return tuple(import_module(f"{__name__}.{module_name}") for module_name in _iter_node_module_names())


def _read_node_type_id(module: ModuleType) -> str:
    """读取节点模块中的 NODE_TYPE_ID。

    参数：
    - module：单个节点模块。

    返回：
    - str：节点类型 id。
    """

    node_type_id = getattr(module, "NODE_TYPE_ID", None)
    if not isinstance(node_type_id, str) or not node_type_id:
        raise RuntimeError(f"节点模块缺少有效的 NODE_TYPE_ID: {module.__name__}")
    return node_type_id


def _read_node_definition_payload(module: ModuleType) -> dict[str, object]:
    """读取节点模块中的显式 NodeDefinition payload。

    参数：
    - module：单个节点模块。

    返回：
    - dict[str, object]：节点定义 payload。
    """

    payload = getattr(module, "NODE_DEFINITION_PAYLOAD", None)
    if not isinstance(payload, dict):
        raise RuntimeError(f"节点模块缺少显式 NODE_DEFINITION_PAYLOAD: {module.__name__}")
    return dict(payload)


NODE_MODULES = _load_node_modules()

NODE_DEFINITION_PAYLOADS: tuple[dict[str, object], ...] = tuple(
    _read_node_definition_payload(module) for module in NODE_MODULES
)

NODE_HANDLERS: dict[str, object] = {}
for module in NODE_MODULES:
    handle_node = getattr(module, "handle_node", None)
    if callable(handle_node):
        node_type_id = _read_node_type_id(module)
        if node_type_id in NODE_HANDLERS:
            raise RuntimeError(f"检测到重复的 barcode 节点类型 id: {node_type_id}")
        NODE_HANDLERS[node_type_id] = handle_node


__all__ = ["NODE_DEFINITION_PAYLOADS", "NODE_HANDLERS", "NODE_MODULES"]