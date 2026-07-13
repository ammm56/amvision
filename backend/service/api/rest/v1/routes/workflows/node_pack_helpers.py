"""workflow node pack 管理路由支撑函数。"""

from __future__ import annotations

from fastapi import Request

from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.nodes.node_pack_loader import NodePackStatusItem, NodePackStatusLog, NodePackStatusSnapshot
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.runtime_registry_loader import WorkflowNodeRuntimeRegistryLoader

from .schemas import (
    WorkflowNodePackDependencyStatusResponse,
    WorkflowNodePackStatusIssueResponse,
    WorkflowNodePackStatusItemResponse,
    WorkflowNodePackStatusLogResponse,
    WorkflowNodePackStatusResponse,
)

def _require_local_node_pack_loader(node_catalog_registry: NodeCatalogRegistry) -> LocalNodePackLoader:
    """读取当前服务中的本地 node pack loader。"""

    node_pack_loader = node_catalog_registry.node_pack_loader
    if not isinstance(node_pack_loader, LocalNodePackLoader):
        raise ServiceConfigurationError(
            "当前服务未启用本地 node pack loader",
            details={"loader_type": type(node_pack_loader).__name__ if node_pack_loader is not None else None},
        )
    return node_pack_loader


def _refresh_workflow_runtime_registry(request: Request) -> None:
    """刷新当前应用状态中的 workflow node runtime registry。"""

    node_catalog_registry = getattr(request.app.state, "node_catalog_registry", None)
    if isinstance(node_catalog_registry, NodeCatalogRegistry):
        node_catalog_registry.invalidate_cache()

    runtime_registry_loader = getattr(request.app.state, "workflow_node_runtime_registry_loader", None)
    if not isinstance(runtime_registry_loader, WorkflowNodeRuntimeRegistryLoader):
        raise ServiceConfigurationError(
            "当前服务尚未完成 workflow node runtime registry loader 装配",
            details={"state_field": "workflow_node_runtime_registry_loader"},
        )
    runtime_registry_loader.refresh()


def _build_node_pack_status_response(snapshot: NodePackStatusSnapshot) -> WorkflowNodePackStatusResponse:
    """构建 node pack 状态快照响应。"""

    return WorkflowNodePackStatusResponse(
        generated_at=snapshot.generated_at,
        custom_nodes_root_dir=snapshot.custom_nodes_root_dir,
        items=[_build_node_pack_status_item_response(item) for item in snapshot.items],
        logs=_build_node_pack_log_responses(snapshot.logs),
    )


def _build_node_pack_status_item_response(item: NodePackStatusItem) -> WorkflowNodePackStatusItemResponse:
    """构建单个 node pack 状态响应。"""

    return WorkflowNodePackStatusItemResponse(
        node_pack_id=item.node_pack_id,
        display_name=item.display_name,
        version=item.version,
        state=item.state,
        enabled=item.enabled,
        source_dir=item.source_dir,
        manifest_path=item.manifest_path,
        custom_node_catalog_path=item.custom_node_catalog_path,
        loaded_at=item.loaded_at,
        node_count=item.node_count,
        capabilities=list(item.capabilities),
        permission_scopes=list(item.permission_scopes),
        dependencies=[
            WorkflowNodePackDependencyStatusResponse(
                node_pack_id=dependency.node_pack_id,
                version_range=dependency.version_range,
                installed=dependency.installed,
                enabled=dependency.enabled,
                version=dependency.version,
                satisfied=dependency.satisfied,
            )
            for dependency in item.dependencies
        ],
        issues=[
            WorkflowNodePackStatusIssueResponse(
                severity=issue.severity,
                code=issue.code,
                message=issue.message,
                details=issue.details,
            )
            for issue in item.issues
        ],
        logs=_build_node_pack_log_responses(item.logs),
        manifest=item.manifest,
    )


def _build_node_pack_log_responses(
    logs: tuple[NodePackStatusLog, ...],
) -> list[WorkflowNodePackStatusLogResponse]:
    """构建 node pack 状态日志响应列表。"""

    return [
        WorkflowNodePackStatusLogResponse(
            level=log.level,
            message=log.message,
            created_at=log.created_at,
            details=log.details,
        )
        for log in logs
    ]

