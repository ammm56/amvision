"""模型路由 service 装配与查询 helper。"""

from __future__ import annotations

from collections.abc import Sequence
from stat import S_ISREG

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
    ProjectModelCatalogResponse,
    ProjectModelCatalogItemResponse,
)
from backend.service.application.errors import ResourceNotFoundError
from backend.service.application.models.registry.model_service import SqlAlchemyModelService
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.service.application.errors import InvalidRequestError


def list_project_model_catalog_response(
    *, session_factory: SessionFactory, project_id: str, task_type: str | None,
    query: str | None, offset: int, limit: int,
) -> ProjectModelCatalogResponse:
    """查询项目模型目录及筛选总数。"""

    models, total = SqlAlchemyModelService(session_factory=session_factory).list_project_model_catalog(
        project_id=project_id, task_type=task_type, query=query, offset=offset, limit=limit
    )
    return ProjectModelCatalogResponse(
        items=[ProjectModelCatalogItemResponse(
            **build_platform_base_model_summary_response(model).model_dump(), build_formats=formats
        ) for model, formats in models], total=total
    )


def list_platform_base_model_responses(
    *,
    session_factory: SessionFactory,
    model_name: str | None,
    model_scale: str | None,
    task_type: str | None,
    limit: int,
    storage: LocalDatasetStorage,
) -> list[PlatformBaseModelSummaryResponse]:
    """查询平台基础模型列表并转换为响应对象。"""

    service = SqlAlchemyModelService(session_factory=session_factory)
    models = service.list_platform_base_models(
        model_name=model_name,
        model_scale=model_scale,
        task_type=task_type,
        limit=limit,
    )
    responses = [build_platform_base_model_summary_response(model) for model in models]
    _check_checkpoint_states(responses, storage)
    return responses


def _check_checkpoint_states(
    responses: Sequence[PlatformBaseModelSummaryResponse], storage: LocalDatasetStorage,
) -> None:
    """只检查已登记 checkpoint 的存在性，不推断内容或运行环境兼容性。"""

    for model in responses:
        for version in model.available_versions:
            if not version.checkpoint_storage_uri:
                version.checkpoint_state = "missing"
                continue
            try:
                path = storage.resolve_deletion_path(version.checkpoint_storage_uri)
                version.checkpoint_state = "present" if S_ISREG(path.stat().st_mode) else "unavailable"
            except FileNotFoundError:
                version.checkpoint_state = "missing"
            except (OSError, InvalidRequestError, ValueError):
                version.checkpoint_state = "unavailable"


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
    storage: LocalDatasetStorage,
) -> list[DeploymentSourceModelSummaryResponse]:
    """查询部署页可用模型来源并转换为响应对象。"""

    service = SqlAlchemyModelService(session_factory=session_factory)
    models = service.list_deployment_source_models(
        project_id=project_id,
        task_type=task_type,
        limit=limit,
    )
    responses = [build_deployment_source_model_summary_response(model) for model in models]
    _check_checkpoint_states(responses, storage)
    return responses


def get_deployment_source_model_detail_response(
    *,
    session_factory: SessionFactory,
    project_id: str,
    model_id: str,
    project_catalog_only: bool = False,
) -> DeploymentSourceModelDetailResponse:
    """查询单个部署来源模型详情并转换为响应对象。"""

    service = SqlAlchemyModelService(session_factory=session_factory)
    model_detail = service.get_deployment_source_model_detail(
        project_id=project_id,
        model_id=model_id,
        project_catalog_only=project_catalog_only,
    )
    if model_detail is None:
        raise ResourceNotFoundError(
            "找不到指定的项目模型" if project_catalog_only else "找不到指定的部署来源模型",
            details={"project_id": project_id, "model_id": model_id},
        )

    return build_deployment_source_model_detail_response(model_detail)
