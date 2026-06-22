"""workflow application 文档路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.nodes import get_node_catalog_registry
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.pagination import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT, paginate_sequence
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage
from backend.nodes.node_catalog_registry import NodeCatalogRegistry

from .documents import (
    _build_application_document_response,
    _build_application_summary_response,
    _build_application_validation_response,
    _build_workflow_json_service,
    _ensure_application_path_matches,
    _ensure_project_visible,
)
from .schemas import (
    WorkflowApplicationCopyRequestBody,
    WorkflowApplicationDocumentResponse,
    WorkflowApplicationSaveRequestBody,
    WorkflowApplicationSummaryResponse,
    WorkflowApplicationValidateRequestBody,
    WorkflowApplicationValidationResponse,
)


workflow_applications_router = APIRouter()


@workflow_applications_router.post("/applications/validate", response_model=WorkflowApplicationValidationResponse)
def validate_flow_application(
    body: WorkflowApplicationValidateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
) -> WorkflowApplicationValidationResponse:
    """校验一份流程应用与模板绑定关系。"""

    _ensure_project_visible(principal=principal, project_id=body.project_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    validation_summary = service.validate_application(
        project_id=body.project_id,
        application=body.application,
        template_override=body.template,
    )
    return _build_application_validation_response(validation_summary)


@workflow_applications_router.put(
    "/projects/{project_id}/applications/{application_id}",
    response_model=WorkflowApplicationDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def save_flow_application(
    project_id: str,
    application_id: str,
    body: WorkflowApplicationSaveRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
) -> WorkflowApplicationDocumentResponse:
    """保存一份流程应用 JSON。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    _ensure_application_path_matches(application=body.application, application_id=application_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    document = service.save_application(
        project_id=project_id,
        application=body.application,
        actor_id=principal.principal_id,
    )
    return _build_application_document_response(document, workflow_service=service)


@workflow_applications_router.get(
    "/projects/{project_id}/applications",
    response_model=list[WorkflowApplicationSummaryResponse],
)
def list_flow_applications(
    project_id: str,
    response: Response,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
    offset: Annotated[int, Query(ge=0, description="结果偏移量")] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT, description="最大返回数量")] = DEFAULT_LIST_LIMIT,
) -> list[WorkflowApplicationSummaryResponse]:
    """列出指定 Project 下全部流程应用摘要。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    applications = service.list_applications(project_id=project_id)
    paged_items = paginate_sequence(applications, response=response, offset=offset, limit=limit)
    return [
        _build_application_summary_response(item, workflow_service=service)
        for item in paged_items
    ]


@workflow_applications_router.get(
    "/projects/{project_id}/applications/{application_id}",
    response_model=WorkflowApplicationDocumentResponse,
)
def get_flow_application(
    project_id: str,
    application_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
) -> WorkflowApplicationDocumentResponse:
    """读取一份已保存的流程应用 JSON。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    document = service.get_application(project_id=project_id, application_id=application_id)
    return _build_application_document_response(document, workflow_service=service)


@workflow_applications_router.post(
    "/projects/{project_id}/applications/{application_id}/copy",
    response_model=WorkflowApplicationDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def copy_flow_application(
    project_id: str,
    application_id: str,
    body: WorkflowApplicationCopyRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
) -> WorkflowApplicationDocumentResponse:
    """复制一份已保存的流程应用。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    document = service.copy_application(
        project_id=project_id,
        source_application_id=application_id,
        target_application_id=body.target_application_id,
        actor_id=principal.principal_id,
        display_name=body.display_name,
        description=body.description,
    )
    return _build_application_document_response(document, workflow_service=service)


@workflow_applications_router.delete(
    "/projects/{project_id}/applications/{application_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_flow_application(
    project_id: str,
    application_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
) -> Response:
    """删除一份已保存的流程应用。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    service.delete_application(project_id=project_id, application_id=application_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
