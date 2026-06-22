"""workflow runtime 路由总装配。"""

from __future__ import annotations

from fastapi import APIRouter

from backend.service.api.rest.v1.routes.workflow_runtime.app_runtimes import workflow_app_runtimes_router
from backend.service.api.rest.v1.routes.workflow_runtime.policies import workflow_runtime_policies_router
from backend.service.api.rest.v1.routes.workflow_runtime.preview_runs import workflow_runtime_preview_runs_router
from backend.service.api.rest.v1.routes.workflow_runtime.runs import workflow_runtime_runs_router


workflow_runtime_router = APIRouter(prefix="/workflows", tags=["workflow-runtime"])
workflow_runtime_router.include_router(workflow_runtime_policies_router)
workflow_runtime_router.include_router(workflow_runtime_preview_runs_router)
workflow_runtime_router.include_router(workflow_app_runtimes_router)
workflow_runtime_router.include_router(workflow_runtime_runs_router)
