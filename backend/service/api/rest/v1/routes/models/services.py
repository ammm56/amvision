"""模型路由 service 装配与查询 helper。"""

from __future__ import annotations

from backend.service.api.rest.v1.routes.models.responses import (
    build_deployment_source_model_detail_response,
    build_deployment_source_model_summary_response,
    build_platform_base_model_detail_response,
    build_platform_base_model_summary_response,
)
from backend.service.api.rest.v1.routes.models.schemas import (
    DeploymentSourceModelDetailResponse,
    DeploymentSourceModelSummaryResponse,
    PlatformBaseModelDetailResponse,
    PlatformBaseModelSummaryResponse,
)
from backend.service.application.errors import ResourceNotFoundError
from backend.service.application.models.registry.model_service import SqlAlchemyModelService
from backend.service.infrastructure.db.session import SessionFactory


def list_platform_base_model_responses(
    *,
    session_factory: SessionFactory,
    model_name: str | None,
    model_scale: str | None,
    task_type: str | None,
    limit: int,
) -> list[PlatformBaseModelSummaryResponse]:
    """查询平台基础模型列表并转换为响应对象。"""

    service = SqlAlchemyModelService(session_factory=session_factory)
    models = service.list_platform_base_models(
        model_name=model_name,
        model_scale=model_scale,
        task_type=task_type,
        limit=limit,
    )
    return [build_platform_base_model_summary_response(model) for model in models]


def get_platform_base_model_detail_response(
    *,
    session_factory: SessionFactory,
    model_id: str,
) -> PlatformBaseModelDetailResponse:
    """查询单个平台基础模型详情并转换为响应对象。"""

    service = SqlAlchemyModelService(session_factory=session_factory)
    model_detail = service.get_platform_base_model_detail(model_id)
    if model_detail is None:
        raise ResourceNotFoundError(
            "找不到指定的平台基础模型",
            details={"model_id": model_id},
        )

    return build_platform_base_model_detail_response(model_detail)


def list_deployment_source_model_responses(
    *,
    session_factory: SessionFactory,
    project_id: str,
    task_type: str | None,
    limit: int,
) -> list[DeploymentSourceModelSummaryResponse]:
    """查询部署页可用模型来源并转换为响应对象。"""

    service = SqlAlchemyModelService(session_factory=session_factory)
    models = service.list_deployment_source_models(
        project_id=project_id,
        task_type=task_type,
        limit=limit,
    )
    return [build_deployment_source_model_summary_response(model) for model in models]


def get_deployment_source_model_detail_response(
    *,
    session_factory: SessionFactory,
    project_id: str,
    model_id: str,
) -> DeploymentSourceModelDetailResponse:
    """查询单个部署来源模型详情并转换为响应对象。"""

    service = SqlAlchemyModelService(session_factory=session_factory)
    model_detail = service.get_deployment_source_model_detail(
        project_id=project_id,
        model_id=model_id,
    )
    if model_detail is None:
        raise ResourceNotFoundError(
            "找不到指定的部署来源模型",
            details={"project_id": project_id, "model_id": model_id},
        )

    return build_deployment_source_model_detail_response(model_detail)
