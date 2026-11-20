"""模型 REST 路由。"""

from __future__ import annotations

from dataclasses import asdict
from hashlib import file_digest
import re
from stat import S_ISREG
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from backend.service.api.deps.auth import AuthenticatedPrincipal, _scope_granted, require_scopes
from backend.service.api.deps.db import get_session_factory, get_unit_of_work
from backend.service.api.rest.v1.routes.models.schemas import (
    DeploymentSourceModelDetailResponse,
    DeploymentSourceModelSummaryResponse,
    DeploymentRuntimeCapabilitiesResponse,
    PlatformBaseModelDetailResponse,
    PlatformBaseModelSummaryResponse,
    ProjectModelCatalogResponse,
    ProjectModelReferencePageResponse,
    ProjectModelReferenceResponse,
    ProjectModelFileStatusResponse,
    ProjectModelPresentationRequest,
    ProjectModelPresentationResponse,
    ProjectModelSourceDatasetResponse,
    ProjectModelSourceParentResponse,
    ProjectModelVersionSourceResponse,
    TrainingParameterSchemaCatalogResponse,
    TrainingParameterSchemaItemResponse,
)
from backend.service.api.rest.v1.routes.models.services import (
    get_deployment_source_model_detail_response,
    get_platform_base_model_detail_response,
    list_deployment_source_model_responses,
    list_platform_base_model_responses,
    list_project_model_catalog_response,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.application.project_access import require_explicit_project_access
from backend.service.application.models.registry.model_service import SqlAlchemyModelService
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.unit_of_work import UnitOfWork
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.resource_file_response import ResourceFileResponse
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
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
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
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
        storage=storage,
    )


@models_router.get("/catalog", response_model=ProjectModelCatalogResponse)
def list_project_model_catalog(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str, Query(description="当前项目 id")],
    task_type: Annotated[str | None, Query(description="任务类型筛选")] = None,
    query: Annotated[str | None, Query(max_length=200, description="模型名称搜索")] = None,
    offset: Annotated[int, Query(ge=0, description="分页起点")] = 0,
    limit: Annotated[int, Query(ge=1, le=200, description="每页数量")] = 20,
) -> ProjectModelCatalogResponse:
    """列出项目内全部模型，包含尚未登记版本的模型。"""

    require_explicit_project_access(visible_project_ids=principal.project_ids, project_id=project_id)
    return list_project_model_catalog_response(
        session_factory=session_factory, project_id=project_id, task_type=task_type,
        query=query.strip() if query and query.strip() else None, offset=offset, limit=limit,
    )


@models_router.get("/catalog/{model_id}", response_model=DeploymentSourceModelDetailResponse)
def get_project_model_catalog_detail(
    model_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str, Query(description="当前项目 id")],
) -> DeploymentSourceModelDetailResponse:
    """读取当前项目的模型详情，包括没有版本的模型。"""

    require_explicit_project_access(visible_project_ids=principal.project_ids, project_id=project_id)
    return get_deployment_source_model_detail_response(
        session_factory=session_factory, project_id=project_id, model_id=model_id,
        project_catalog_only=True,
    )


@models_router.get(
    "/catalog/{model_id}/versions/{model_version_id}/source",
    response_model=ProjectModelVersionSourceResponse,
)
def get_project_model_version_source(
    model_id: str, model_version_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    unit: Annotated[UnitOfWork, Depends(get_unit_of_work)],
    project_id: Annotated[str, Query(description="当前项目 id")],
) -> ProjectModelVersionSourceResponse:
    """解析真实的训练数据集和父版本，不用展示名称推断关系。"""

    require_explicit_project_access(visible_project_ids=principal.project_ids, project_id=project_id)
    model = unit.models.get_model(model_id)
    version = unit.models.get_model_version(model_version_id)
    if model is None or model.project_id != project_id or version is None or version.model_id != model_id:
        raise ResourceNotFoundError("找不到当前项目的模型版本")

    dataset = None
    if _scope_granted(principal.scopes, "datasets:read"):
        dataset_version_id = version.dataset_version_id
        if not dataset_version_id and version.training_task_id:
            task = unit.tasks.get_task(version.training_task_id)
            if task and task.project_id == project_id:
                export_id = task.task_spec.get("dataset_export_id")
                if isinstance(export_id, str):
                    export = unit.dataset_exports.get_dataset_export(export_id)
                    if export and export.project_id == project_id:
                        dataset_version_id = export.dataset_version_id
        rows = unit.dataset_catalog.version_summaries([dataset_version_id]) if dataset_version_id else []
        if rows and rows[0]["project_id"] == project_id:
            row = rows[0]
            dataset = ProjectModelSourceDatasetResponse(
                dataset_id=row["dataset_id"], dataset_version_id=row["dataset_version_id"],
                display_name=row["display_name"], version_number=row["version_number"],
            )

    parent = None
    if version.parent_version_id:
        parent_version = unit.models.get_model_version(version.parent_version_id)
        parent_model = unit.models.get_model(parent_version.model_id) if parent_version else None
        if parent_version and parent_model and (parent_model.project_id == project_id or parent_model.scope_kind == "platform-base"):
            parent = ProjectModelSourceParentResponse(
                model_id=parent_model.model_id, model_version_id=parent_version.model_version_id,
                display_name=str(parent_model.metadata.get("display_name") or parent_model.model_name),
                scope_kind=parent_model.scope_kind,
            )
    return ProjectModelVersionSourceResponse(dataset=dataset, parent=parent)


@models_router.put("/catalog/{model_id}/presentation", response_model=ProjectModelPresentationResponse)
def update_project_model_presentation(
    model_id: str, body: ProjectModelPresentationRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:write"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str, Query(description="当前项目 id")],
) -> ProjectModelPresentationResponse:
    """修改展示名称和说明，不修改模型登记键或版本。"""
    require_explicit_project_access(visible_project_ids=principal.project_ids, project_id=project_id)
    display_name = body.display_name.strip()
    if not display_name:
        raise InvalidRequestError("模型名称不能为空")
    revision = SqlAlchemyModelService(session_factory=session_factory).update_project_presentation(
        project_id=project_id, model_id=model_id, display_name=display_name,
        description=body.description.strip(), expected_revision=body.expected_revision,
    )
    return ProjectModelPresentationResponse(revision=revision)


@models_router.get(
    "/catalog/{model_id}/versions/{model_version_id}/references",
    response_model=ProjectModelReferencePageResponse,
)
def list_project_model_version_references(
    model_id: str,
    model_version_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    project_id: Annotated[str, Query(description="当前项目 id")],
    query: Annotated[str | None, Query(max_length=200, description="部署名称搜索")] = None,
    offset: Annotated[int, Query(ge=0, description="分页起点")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="每页数量")] = 6,
    model_build_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
) -> ProjectModelReferencePageResponse:
    """列出当前项目直接绑定此模型版本的部署。"""

    require_explicit_project_access(visible_project_ids=principal.project_ids, project_id=project_id)
    items, total = SqlAlchemyModelService(session_factory=session_factory).list_project_model_version_references(
        project_id=project_id, model_id=model_id, model_version_id=model_version_id,
        query=query.strip() if query and query.strip() else None, offset=offset, limit=limit,
        model_build_id=model_build_id,
    )
    return ProjectModelReferencePageResponse(
        items=[ProjectModelReferenceResponse(**asdict(item)) for item in items], total=total
    )


@models_router.get(
    "/catalog/{model_id}/versions/{model_version_id}/files/{file_id}/status",
    response_model=ProjectModelFileStatusResponse,
    response_model_exclude_unset=True,
)
def get_project_model_file_status(
    model_id: str, model_version_id: str, file_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    project_id: Annotated[str, Query(description="当前项目 id")],
    part: Annotated[Literal["weights"] | None, Query(description="读取旧 OpenVINO IR 的关联权重")] = None,
    include_sha256: Annotated[bool, Query(description="按需计算文件 SHA256")] = False,
) -> ProjectModelFileStatusResponse:
    """检查已登记文件是否存在，按需读取摘要以供比对。"""

    require_explicit_project_access(visible_project_ids=principal.project_ids, project_id=project_id)
    model_file = SqlAlchemyModelService(session_factory=session_factory).get_project_model_version_file(
        project_id=project_id, model_id=model_id, model_version_id=model_version_id, file_id=file_id,
        weights=part == "weights",
    )
    payload = ProjectModelFileStatusResponse(file_id=file_id, state="unavailable", size_bytes=None)
    if part is not None:
        payload.part = part
    try:
        path = storage.resolve_deletion_path(model_file.storage_uri)
        metadata = path.stat()
        if S_ISREG(metadata.st_mode):
            if include_sha256:
                with path.open("rb") as handle:
                    payload.sha256 = file_digest(handle, "sha256").hexdigest()
            payload.state = "present"
            payload.size_bytes = metadata.st_size
    except FileNotFoundError:
        payload.state = "missing"
    except (OSError, InvalidRequestError, ValueError):
        pass
    return payload


@models_router.get("/catalog/{model_id}/versions/{model_version_id}/files/{file_id}/download")
def download_project_model_file(
    model_id: str, model_version_id: str, file_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("models:read"))],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    project_id: Annotated[str, Query(description="当前项目 id")],
    part: Annotated[Literal["weights"] | None, Query(description="下载旧 OpenVINO IR 的关联权重")] = None,
) -> ResourceFileResponse:
    """下载已登记的单个模型文件，传输期间阻止资源被删除。"""

    require_explicit_project_access(visible_project_ids=principal.project_ids, project_id=project_id)
    model_file = SqlAlchemyModelService(session_factory=session_factory).get_project_model_version_file(
        project_id=project_id, model_id=model_id, model_version_id=model_version_id, file_id=file_id,
        weights=part == "weights",
    )
    try:
        path = storage.resolve_deletion_path(model_file.storage_uri)
        if not path.is_file():
            raise ResourceNotFoundError("模型文件不存在", details={"file_id": file_id})
    except (OSError, InvalidRequestError, ValueError) as error:
        raise ResourceNotFoundError("模型文件不可读取", details={"file_id": file_id}) from error
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", path.name)[:160] or "model-file"
    return ResourceFileResponse(
        session_factory=session_factory, project_id=project_id, resource_id=file_id,
        path=path, filename=filename, media_type="application/octet-stream",
        headers={"Cache-Control": "no-store"},
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
    storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    project_id: Annotated[str, Query(description="当前 Project id")],
    task_type: Annotated[str | None, Query(description="任务类型筛选")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="最大返回数量")] = 100,
) -> list[DeploymentSourceModelSummaryResponse]:
    """列出部署页可选择的 ModelVersion 和 ModelBuild 来源。"""

    require_explicit_project_access(
        visible_project_ids=principal.project_ids,
        project_id=project_id,
    )
    return list_deployment_source_model_responses(
        session_factory=session_factory,
        project_id=project_id,
        task_type=task_type,
        limit=limit,
        storage=storage,
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

    require_explicit_project_access(
        visible_project_ids=principal.project_ids,
        project_id=project_id,
    )
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
