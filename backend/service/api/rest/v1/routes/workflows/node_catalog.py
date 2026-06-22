"""workflow node catalog 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.nodes import get_node_catalog_registry

from .node_catalog_helpers import (
    _build_effective_node_definitions,
    _build_workflow_node_palette_groups,
    _filter_node_pack_manifests,
    _filter_workflow_node_definitions,
    _filter_workflow_payload_contracts,
)
from .schemas import WorkflowNodeCatalogResponse


workflow_node_catalog_router = APIRouter()


@workflow_node_catalog_router.get("/node-catalog", response_model=WorkflowNodeCatalogResponse)
def get_workflow_node_catalog(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
    category: Annotated[str | None, Query(description="按节点分类前缀过滤")] = None,
    node_pack_id: Annotated[str | None, Query(description="按节点包 id 过滤")] = None,
    payload_type_id: Annotated[str | None, Query(description="按端口 payload 类型过滤")] = None,
    q: Annotated[str | None, Query(description="按节点类型 id、显示名称或说明搜索")] = None,
) -> WorkflowNodeCatalogResponse:
    """按查询条件读取当前 workflow 节点目录快照。

    参数：
    - category：可选节点分类前缀过滤条件。
    - node_pack_id：可选节点包 id 过滤条件。
    - payload_type_id：可选端口 payload 类型过滤条件。
    - q：可选关键词搜索条件。
    - principal：当前认证主体。
    - node_catalog_registry：统一节点目录注册表。

    返回：
    - WorkflowNodeCatalogResponse：按条件过滤后的节点目录快照。
    """

    _ = principal
    catalog_snapshot = node_catalog_registry.get_catalog_snapshot()
    filtered_node_definitions = _filter_workflow_node_definitions(
        node_definitions=catalog_snapshot.node_definitions,
        category=category,
        node_pack_id=node_pack_id,
        payload_type_id=payload_type_id,
        keyword=q,
    )
    filtered_payload_contracts = _filter_workflow_payload_contracts(
        payload_contracts=catalog_snapshot.payload_contracts,
        node_definitions=filtered_node_definitions,
        payload_type_id=payload_type_id,
        filters_active=any(item is not None and item.strip() for item in (category, node_pack_id, payload_type_id, q)),
    )
    filtered_node_pack_manifests = _filter_node_pack_manifests(
        node_pack_manifests=catalog_snapshot.node_pack_manifests,
        node_definitions=filtered_node_definitions,
        node_pack_id=node_pack_id,
        filters_active=any(item is not None and item.strip() for item in (category, node_pack_id, payload_type_id, q)),
    )
    effective_node_definitions = _build_effective_node_definitions(filtered_node_definitions)
    return WorkflowNodeCatalogResponse(
        node_pack_manifests=filtered_node_pack_manifests,
        payload_contracts=filtered_payload_contracts,
        node_definitions=effective_node_definitions,
        palette_groups=_build_workflow_node_palette_groups(effective_node_definitions),
    )

