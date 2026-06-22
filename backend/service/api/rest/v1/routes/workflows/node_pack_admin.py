"""workflow node pack 管理路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.nodes import get_node_catalog_registry

from .node_pack_helpers import (
    _build_node_pack_log_responses,
    _build_node_pack_status_response,
    _refresh_workflow_runtime_registry,
    _require_local_node_pack_loader,
)
from .schemas import WorkflowNodePackStatusLogResponse, WorkflowNodePackStatusResponse


workflow_node_pack_admin_router = APIRouter()


@workflow_node_pack_admin_router.get("/node-pack-status", response_model=WorkflowNodePackStatusResponse)
def get_workflow_node_pack_status(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
) -> WorkflowNodePackStatusResponse:
    """读取本地 node pack loader 的真实状态快照。"""

    _ = principal
    node_pack_loader = _require_local_node_pack_loader(node_catalog_registry)
    return _build_node_pack_status_response(node_pack_loader.get_node_pack_status_snapshot())


@workflow_node_pack_admin_router.post("/node-packs/reload", response_model=WorkflowNodePackStatusResponse)
def reload_workflow_node_packs(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
    request: Request,
) -> WorkflowNodePackStatusResponse:
    """重新扫描并加载本地 node pack。"""

    _ = principal
    node_pack_loader = _require_local_node_pack_loader(node_catalog_registry)
    snapshot = node_pack_loader.reload()
    _refresh_workflow_runtime_registry(request)
    return _build_node_pack_status_response(snapshot)


@workflow_node_pack_admin_router.post("/node-packs/{node_pack_id}/validate", response_model=WorkflowNodePackStatusResponse)
def validate_workflow_node_pack(
    node_pack_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
) -> WorkflowNodePackStatusResponse:
    """只读校验单个本地 node pack。"""

    _ = principal
    node_pack_loader = _require_local_node_pack_loader(node_catalog_registry)
    return _build_node_pack_status_response(node_pack_loader.validate(node_pack_id))


@workflow_node_pack_admin_router.post("/node-packs/{node_pack_id}/enable", response_model=WorkflowNodePackStatusResponse)
def enable_workflow_node_pack(
    node_pack_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
    request: Request,
) -> WorkflowNodePackStatusResponse:
    """启用本地 JSON manifest 中的 node pack。"""

    _ = principal
    node_pack_loader = _require_local_node_pack_loader(node_catalog_registry)
    snapshot = node_pack_loader.set_node_pack_enabled(node_pack_id, True)
    _refresh_workflow_runtime_registry(request)
    return _build_node_pack_status_response(snapshot)


@workflow_node_pack_admin_router.post("/node-packs/{node_pack_id}/disable", response_model=WorkflowNodePackStatusResponse)
def disable_workflow_node_pack(
    node_pack_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
    request: Request,
) -> WorkflowNodePackStatusResponse:
    """禁用本地 JSON manifest 中的 node pack。"""

    _ = principal
    node_pack_loader = _require_local_node_pack_loader(node_catalog_registry)
    snapshot = node_pack_loader.set_node_pack_enabled(node_pack_id, False)
    _refresh_workflow_runtime_registry(request)
    return _build_node_pack_status_response(snapshot)


@workflow_node_pack_admin_router.get("/node-packs/{node_pack_id}/logs", response_model=list[WorkflowNodePackStatusLogResponse])
def get_workflow_node_pack_logs(
    node_pack_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
) -> list[WorkflowNodePackStatusLogResponse]:
    """读取单个本地 node pack 的状态日志。"""

    _ = principal
    node_pack_loader = _require_local_node_pack_loader(node_catalog_registry)
    return _build_node_pack_log_responses(node_pack_loader.get_node_pack_logs(node_pack_id))

