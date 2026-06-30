"""system bootstrap 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from backend.contracts.datasets.exports.dataset_formats import (
    IMPLEMENTED_DATASET_EXPORT_FORMATS,
    IMPLEMENTED_DATASET_EXPORT_FORMAT_TYPES_BY_TASK_TYPE,
)
from backend.service.api.deps.auth import AuthenticatedPrincipal, get_optional_principal
from backend.service.api.rest.v1.routes.projects.responses import (
    build_project_catalog_item_response,
)
from backend.service.api.rest.v1.routes.projects.schemas import ProjectCatalogItemResponse
from backend.service.api.rest.v1.routes.projects.services import list_visible_project_ids
from backend.service.api.rest.v1.routes.system.responses import (
    build_auth_provider_contract,
    build_current_principal_contract,
)
from backend.service.api.rest.v1.routes.system.diagnostics import build_device_diagnostics
from backend.service.api.rest.v1.routes.system.schemas import (
    DatasetExportCapabilityContract,
    DatasetImportCapabilityContract,
    SystemBootstrapCapabilitiesContract,
    SystemBootstrapResponse,
)
from backend.service.api.rest.v1.routes.system.services import (
    require_backend_service_settings,
    require_session_factory,
)
from backend.service.application.auth.provider_registry import AuthProviderRegistry
from backend.service.application.project_summary import get_supported_project_summary_topics
from backend.service.domain.datasets.dataset_import import (
    IMPLEMENTED_DATASET_IMPORT_FORMAT_TYPES_BY_TASK_TYPE,
    IMPLEMENTED_DATASET_IMPORT_TASK_TYPES,
)
from backend.service.domain.models.platform_model_support import (
    SUPPORTED_PLATFORM_MODEL_TYPES_BY_TASK_TYPE,
)


system_bootstrap_router = APIRouter()


@system_bootstrap_router.get("/bootstrap", response_model=SystemBootstrapResponse)
def get_system_bootstrap(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal | None, Depends(get_optional_principal)],
) -> SystemBootstrapResponse:
    """返回前端首屏初始化需要的聚合响应。"""

    settings = require_backend_service_settings(request)
    providers = [
        build_auth_provider_contract(item)
        for item in AuthProviderRegistry(
            settings=settings,
            session_factory=require_session_factory(request),
        ).list_providers()
    ]
    visible_projects: list[ProjectCatalogItemResponse] = []
    if principal is not None:
        visible_projects = [
            build_project_catalog_item_response(
                request=request,
                project_id=project_id,
                include_summary=False,
            )
            for project_id in list_visible_project_ids(request=request, principal=principal)
        ]

    return SystemBootstrapResponse(
        auth_mode=settings.auth.mode,
        bearer_auth_enabled=settings.auth.bearer_auth_enabled(),
        websocket_query_token_enabled=settings.auth.websocket_query_token_enabled,
        current_user=None if principal is None else build_current_principal_contract(principal),
        providers=providers,
        visible_projects=visible_projects,
        capabilities=SystemBootstrapCapabilitiesContract(
            project_bootstrap_enabled=True,
            dataset_import=DatasetImportCapabilityContract(
                implemented_task_types=list(IMPLEMENTED_DATASET_IMPORT_TASK_TYPES),
                format_types_by_task_type={
                    task_type: list(format_types)
                    for task_type, format_types in IMPLEMENTED_DATASET_IMPORT_FORMAT_TYPES_BY_TASK_TYPE.items()
                },
            ),
            dataset_export=DatasetExportCapabilityContract(
                implemented_formats=list(IMPLEMENTED_DATASET_EXPORT_FORMATS),
                default_format=IMPLEMENTED_DATASET_EXPORT_FORMATS[0],
                format_types_by_task_type={
                    task_type: list(format_types)
                    for task_type, format_types in IMPLEMENTED_DATASET_EXPORT_FORMAT_TYPES_BY_TASK_TYPE.items()
                },
            ),
            project_summary_topics=list(get_supported_project_summary_topics()),
            platform_model_types_by_task_type={
                task_type: list(model_types)
                for task_type, model_types in SUPPORTED_PLATFORM_MODEL_TYPES_BY_TASK_TYPE.items()
            },
        ),
        devices=build_device_diagnostics(),
    )
