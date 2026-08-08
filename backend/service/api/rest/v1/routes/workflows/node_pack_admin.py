"""workflow node pack 管理路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile

from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.nodes import get_node_catalog_registry

from .node_pack_helpers import (
    _build_node_pack_audit_response,
    _build_node_pack_lifecycle_manager,
    _build_node_pack_lifecycle_response,
    _build_node_pack_log_responses,
    _build_node_pack_status_response,
    _refresh_workflow_runtime_registry,
    _require_local_node_pack_loader,
)
from .node_pack_helpers import _build_node_pack_version_response
from .schemas import (
    WorkflowNodePackAuditResponse,
    WorkflowNodePackLifecycleResponse,
    WorkflowNodePackStatusLogResponse,
    WorkflowNodePackStatusResponse,
    WorkflowNodePackVersionResponse,
)


workflow_node_pack_admin_router = APIRouter()


@workflow_node_pack_admin_router.post(
    "/node-packs/install",
    response_model=WorkflowNodePackLifecycleResponse,
)
def install_workflow_node_pack(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
    request: Request,
    package: Annotated[UploadFile, File()],
    enabled: Annotated[bool | None, Form()] = None,
) -> WorkflowNodePackLifecycleResponse:
    """从受限 ZIP 安装或升级节点包并原子激活。"""

    node_pack_loader = _require_local_node_pack_loader(node_catalog_registry)
    manager = _build_node_pack_lifecycle_manager(node_catalog_registry)
    result = manager.install_archive(
        package.file,
        source_file_name=package.filename or "node-pack.zip",
        actor_id=principal.principal_id,
        enabled=enabled,
        post_activate=lambda: _refresh_workflow_runtime_registry(request),
    )
    return _build_node_pack_lifecycle_response(
        result,
        node_pack_loader=node_pack_loader,
    )


@workflow_node_pack_admin_router.get(
    "/node-packs/audit",
    response_model=list[WorkflowNodePackAuditResponse],
)
def list_workflow_node_pack_audit(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
    node_pack_id: Annotated[str | None, Query(description="按 node pack id 过滤")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[WorkflowNodePackAuditResponse]:
    """读取节点包安装、升级、回滚与控制动作审计。"""

    _ = principal
    manager = _build_node_pack_lifecycle_manager(node_catalog_registry)
    return [
        _build_node_pack_audit_response(item)
        for item in manager.list_audit_records(node_pack_id=node_pack_id, limit=limit)
    ]


@workflow_node_pack_admin_router.get(
    "/node-packs/{node_pack_id}/versions",
    response_model=list[WorkflowNodePackVersionResponse],
)
def list_workflow_node_pack_versions(
    node_pack_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
) -> list[WorkflowNodePackVersionResponse]:
    """读取节点包全部可回滚版本。"""

    _ = principal
    manager = _build_node_pack_lifecycle_manager(node_catalog_registry)
    return [
        _build_node_pack_version_response(item)
        for item in manager.list_versions(node_pack_id)
    ]


@workflow_node_pack_admin_router.post(
    "/node-packs/{node_pack_id}/rollback/{target_version}",
    response_model=WorkflowNodePackLifecycleResponse,
)
def rollback_workflow_node_pack(
    node_pack_id: str,
    target_version: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
    request: Request,
) -> WorkflowNodePackLifecycleResponse:
    """把节点包原子回滚到已登记版本。"""

    node_pack_loader = _require_local_node_pack_loader(node_catalog_registry)
    manager = _build_node_pack_lifecycle_manager(node_catalog_registry)
    result = manager.rollback(
        node_pack_id,
        target_version,
        actor_id=principal.principal_id,
        post_activate=lambda: _refresh_workflow_runtime_registry(request),
    )
    return _build_node_pack_lifecycle_response(
        result,
        node_pack_loader=node_pack_loader,
    )


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

    node_pack_loader = _require_local_node_pack_loader(node_catalog_registry)
    snapshot = node_pack_loader.reload()
    _refresh_workflow_runtime_registry(request)
    _build_node_pack_lifecycle_manager(node_catalog_registry).append_control_audit(
        action="reload",
        status="succeeded",
        actor_id=principal.principal_id,
    )
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

    manager = _build_node_pack_lifecycle_manager(node_catalog_registry)
    snapshot = manager.set_enabled(
        node_pack_id,
        True,
        actor_id=principal.principal_id,
        post_activate=lambda: _refresh_workflow_runtime_registry(request),
    )
    return _build_node_pack_status_response(snapshot)


@workflow_node_pack_admin_router.post("/node-packs/{node_pack_id}/disable", response_model=WorkflowNodePackStatusResponse)
def disable_workflow_node_pack(
    node_pack_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
    request: Request,
) -> WorkflowNodePackStatusResponse:
    """禁用本地 JSON manifest 中的 node pack。"""

    manager = _build_node_pack_lifecycle_manager(node_catalog_registry)
    snapshot = manager.set_enabled(
        node_pack_id,
        False,
        actor_id=principal.principal_id,
        post_activate=lambda: _refresh_workflow_runtime_registry(request),
    )
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

