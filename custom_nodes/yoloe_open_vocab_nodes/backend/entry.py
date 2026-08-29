"""YOLOE open vocabulary 节点包的 backend entrypoint。"""

from __future__ import annotations

from importlib import import_module
from threading import RLock
from typing import Any, Callable

from backend.service.application.workflows.runtime_registry_loader import (
    NodePackEntrypointRegistrationContext,
)


_NODE_HANDLER_MODULE = "custom_nodes.yoloe_open_vocab_nodes.backend.nodes"
_LOAD_LOCK = RLock()
_NODE_HANDLERS: dict[str, Callable[[Any], dict[str, object]]] = {}


def _resolve_node_handler(
    node_type_id: str,
) -> Callable[[Any], dict[str, object]]:
    """首次执行 YOLOE 节点时加载模型相关实现。"""

    with _LOAD_LOCK:
        handler = _NODE_HANDLERS.get(node_type_id)
        if handler is not None:
            return handler
        module = import_module(_NODE_HANDLER_MODULE)
        discovered = getattr(module, "NODE_HANDLERS", None)
        if not isinstance(discovered, dict):
            raise RuntimeError("YOLOE 节点模块没有返回有效的 NODE_HANDLERS")
        for discovered_node_type_id, discovered_handler in discovered.items():
            if isinstance(discovered_node_type_id, str) and callable(
                discovered_handler
            ):
                _NODE_HANDLERS[discovered_node_type_id] = discovered_handler
        handler = _NODE_HANDLERS.get(node_type_id)
        if handler is None:
            raise RuntimeError(f"找不到 YOLOE 节点 handler: {node_type_id}")
        return handler


def _build_lazy_node_handler(
    node_type_id: str,
) -> Callable[[Any], dict[str, object]]:
    """为单个节点类型构造不提前导入 PyTorch 的稳定代理。"""

    def handle_node(request: Any) -> dict[str, object]:
        return _resolve_node_handler(node_type_id)(request)

    return handle_node


def register(context: NodePackEntrypointRegistrationContext) -> None:
    """注册 YOLOE open vocabulary 节点包中的全部 python-callable 节点。

    参数：
    - context：当前 node pack 的注册上下文。
    """

    for node_definition in context.list_node_definitions():
        if node_definition.runtime_kind == "python-callable":
            context.register_python_callable(
                node_definition.node_type_id,
                _build_lazy_node_handler(node_definition.node_type_id),
            )
