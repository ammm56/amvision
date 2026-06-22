"""workflow 文档和节点管理路由总装配。"""

from __future__ import annotations

from fastapi import APIRouter

from backend.service.api.rest.v1.routes.workflows.applications import workflow_applications_router
from backend.service.api.rest.v1.routes.workflows.node_catalog import workflow_node_catalog_router
from backend.service.api.rest.v1.routes.workflows.node_pack_admin import workflow_node_pack_admin_router
from backend.service.api.rest.v1.routes.workflows.templates import workflow_templates_router


workflows_router = APIRouter(prefix="/workflows", tags=["workflows"])
workflows_router.include_router(workflow_node_catalog_router)
workflows_router.include_router(workflow_node_pack_admin_router)
workflows_router.include_router(workflow_templates_router)
workflows_router.include_router(workflow_applications_router)
