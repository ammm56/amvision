"""节点并发策略的保守内部推导规则。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_CONCURRENCY_SERIALIZED,
    NODE_CONCURRENCY_THREAD_SAFE,
    NODE_IMPLEMENTATION_CORE,
    NODE_IMPLEMENTATION_CUSTOM,
    NodeDefinition,
)


_STATELESS_CORE_CATEGORY_PREFIXES = (
    "core.input.",
    "core.inspection.",
    "core.io.",
    "core.logic.",
    "core.ui.",
    "core.vision.",
)
_STATELESS_CUSTOM_CATEGORY_PREFIXES = (
    "barcode.",
    "opencv.",
    "yoloe.",
)
_STATELESS_CUSTOM_CATEGORIES = frozenset(("example.hello", "http.request"))


def apply_inferred_concurrency_policy(
    definition: NodeDefinition,
) -> NodeDefinition:
    """只把白名单内默认串行节点提升为 thread-safe。"""

    if definition.concurrency_policy != NODE_CONCURRENCY_SERIALIZED:
        return definition
    if _is_verified_stateless_definition(definition):
        return definition.model_copy(
            update={"concurrency_policy": NODE_CONCURRENCY_THREAD_SAFE}
        )
    return definition


def _is_verified_stateless_definition(definition: NodeDefinition) -> bool:
    """判断节点是否属于已经审计的无状态能力族。"""

    category = definition.category.strip().lower()
    if definition.implementation_kind == NODE_IMPLEMENTATION_CORE:
        return category.startswith(_STATELESS_CORE_CATEGORY_PREFIXES)
    if definition.implementation_kind != NODE_IMPLEMENTATION_CUSTOM:
        return False
    return category in _STATELESS_CUSTOM_CATEGORIES or category.startswith(
        _STATELESS_CUSTOM_CATEGORY_PREFIXES
    )


__all__ = ["apply_inferred_concurrency_policy"]
