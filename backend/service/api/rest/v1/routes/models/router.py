"""模型 REST 路由。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.rest.v1.routes.models.schemas import (
    DeploymentSourceModelDetailResponse,
    DeploymentSourceModelSummaryResponse,
    DeploymentRuntimeCapabilitiesResponse,
    PlatformBaseModelDetailResponse,
    PlatformBaseModelSummaryResponse,
    TrainingParameterSchemaCatalogResponse,
    TrainingParameterSchemaItemResponse,
)
from backend.service.api.rest.v1.routes.models.services import (
    get_deployment_source_model_detail_response,
    get_platform_base_model_detail_response,
    list_deployment_source_model_responses,
    list_platform_base_model_responses,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.application.runtime.deployment.runtime_capabilities import (
    inspect_deployment_runtime_capabilities,
)
from backend.service.api.rest.v1.routes.training_parameter_schemas import (
    TRAINING_PARAMETER_SCHEMA_BY_TASK_AND_MODEL,
)
from backend.service.api.rest.v1.routes.training_parameter_catalog import (
    build_training_numeric_parameter_specs,
)
from backend.service.api.rest.v1.routes.training_parameter_capabilities import (
    get_training_parameter_capabilities,
)


models_router = APIRouter(prefix="/models", tags=["models"])


@models_router.get(
    "/training-parameter-schemas",
    response_model=TrainingParameterSchemaCatalogResponse,
)
def list_training_parameter_schemas(
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("models:read"))
    ],
    task_type: Annotated[str | None, Query(description="任务类型筛选")] = None,
    model_type: Annotated[str | None, Query(description="模型类型筛选")] = None,
) -> TrainingParameterSchemaCatalogResponse:
    """返回前端表单和 SDK 共用的严格训练参数协议。"""

    _ = principal
    normalized_task = str(task_type).strip().lower() if task_type else None
    normalized_model = str(model_type).strip().lower() if model_type else None
    items: list[TrainingParameterSchemaItemResponse] = []
    for (registered_task, registered_model), schema in sorted(
        TRAINING_PARAMETER_SCHEMA_BY_TASK_AND_MODEL.items()
    ):
        if normalized_task is not None and registered_task != normalized_task:
            continue
        if normalized_model is not None and registered_model != normalized_model:
            continue
        items.append(
            TrainingParameterSchemaItemResponse(
                task_type=registered_task,
                model_type=registered_model,
                schema_name=schema.__name__,
                parameter_schema=schema.model_json_schema(),
                default_parameters=schema().model_dump(mode="json"),
                numeric_fields=build_training_numeric_parameter_specs(
                    task_type=registered_task,
                    model_type=registered_model,
                    schema=schema,
                ),
                capabilities=asdict(
                    get_training_parameter_capabilities(
                        task_type=registered_task,
                        model_type=registered_model,
                    )
                ),
            )
        )
    return TrainingParameterSchemaCatalogResponse(items=items)


@models_router.get(
    "/deployment-runtime-capabilities",
    response_model=DeploymentRuntimeCapabilitiesResponse,
)
def get_deployment_runtime_capabilities(
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("models:read"))
    ],
    runtime_backend: Annotated[str, Query(description="运行时 backend")],
    device_name: Annotated[str, Query(description="目标 device")],
) -> DeploymentRuntimeCapabilitiesResponse:
    """返回发布表单与运行状态使用的当前 runtime 能力。"""

    _ = principal
    return DeploymentRuntimeCapabilitiesResponse.model_validate(
        inspect_deployment_runtime_capabilities(
            runtime_backend=runtime_backend,
            device_name=device_name,
        )
    )


@models_router.get(
    "/platform-base",
    response_model=list[PlatformBaseModelSummaryResponse],
)
def list_platform_base_models(
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("models:read"))
    ],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    model_name: Annotated[str | None, Query(description="模型名筛选")] = None,
    model_scale: Annotated[str | None, Query(description="模型 scale 筛选")] = None,
    task_type: Annotated[str | None, Query(description="任务类型筛选")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="最大返回数量")] = 100,
) -> list[PlatformBaseModelSummaryResponse]:
    """列出当前可见的平台基础模型。"""

    _ = principal
    return list_platform_base_model_responses(
        session_factory=session_factory,
        model_name=model_name,
        model_scale=model_scale,
        task_type=task_type,
        limit=limit,
    )


@models_router.get(
    "/deployment-sources",
    response_model=list[DeploymentSourceModelSummaryResponse],
)
def list_deployment_source_models(
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("models:read"))
    ],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str, Query(description="当前 Project id")],
    task_type: Annotated[str | None, Query(description="任务类型筛选")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="最大返回数量")] = 100,
) -> list[DeploymentSourceModelSummaryResponse]:
    """列出部署页可选择的 ModelVersion 和 ModelBuild 来源。"""

    _ = principal
    return list_deployment_source_model_responses(
        session_factory=session_factory,
        project_id=project_id,
        task_type=task_type,
        limit=limit,
    )


@models_router.get(
    "/deployment-sources/{model_id}",
    response_model=DeploymentSourceModelDetailResponse,
)
def get_deployment_source_model_detail(
    model_id: str,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("models:read"))
    ],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str, Query(description="当前 Project id")],
) -> DeploymentSourceModelDetailResponse:
    """按 id 返回部署页可选择的模型来源详情。"""

    _ = principal
    return get_deployment_source_model_detail_response(
        session_factory=session_factory,
        project_id=project_id,
        model_id=model_id,
    )


@models_router.get(
    "/platform-base/{model_id}",
    response_model=PlatformBaseModelDetailResponse,
)
def get_platform_base_model_detail(
    model_id: str,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("models:read"))
    ],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> PlatformBaseModelDetailResponse:
    """按 id 返回单个平台基础模型详情。"""

    _ = principal
    return get_platform_base_model_detail_response(
        session_factory=session_factory,
        model_id=model_id,
    )
