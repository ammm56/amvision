"""workflow template 文档路由。"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from typing import Annotated, Iterator

from fastapi import APIRouter, Depends, Query, Request, Response, status

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.nodes import get_node_catalog_registry
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.rest.v1.pagination import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    paginate_sequence,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.workflows.application_lifecycle import (
    WorkflowApplicationLifecycleService,
)
from backend.service.application.workflows.lifecycle_resource_keys import (
    build_workflow_template_lifecycle_resource_key,
)

from .documents import (
    _build_template_document_response,
    _build_template_summary_response,
    _build_template_validation_response,
    _build_template_version_summary_response,
    _build_workflow_json_service,
    _ensure_project_visible,
    _ensure_template_path_matches,
)
from .schemas import (
    WorkflowTemplateCopyRequestBody,
    WorkflowTemplateDocumentResponse,
    WorkflowTemplateSaveRequestBody,
    WorkflowTemplateSummaryResponse,
    WorkflowTemplateValidateRequestBody,
    WorkflowTemplateValidationResponse,
    WorkflowTemplateVersionSummaryResponse,
)


workflow_templates_router = APIRouter()


def _build_template_lifecycle_service(
    request: Request,
) -> WorkflowApplicationLifecycleService:
    """从应用状态构建 Template 共用的持久化 lifecycle 服务。"""

    from backend.service.api.rest.v1.routes.workflow_runtime_support.services import (  # noqa: PLC0415
        require_dataset_storage,
        require_session_factory,
    )

    return WorkflowApplicationLifecycleService(
        session_factory=require_session_factory(request),
        dataset_storage=require_dataset_storage(request),
    )


@contextmanager
def _template_lifecycle_operations(
    request: Request,
    *,
    project_id: str,
    template_refs: tuple[tuple[str, str], ...],
) -> Iterator[None]:
    """按稳定顺序占用一个或多个 Template lifecycle claim。"""

    resource_keys = sorted(
        {
            build_workflow_template_lifecycle_resource_key(
                template_id=template_id,
                template_version=template_version,
            )
            for template_id, template_version in template_refs
        }
    )
    lifecycle_service = _build_template_lifecycle_service(request)
    with ExitStack() as stack:
        for resource_key in resource_keys:
            stack.enter_context(
                lifecycle_service.operation(
                    project_id=project_id,
                    application_id=resource_key,
                    operation="saving",
                    allow_deleted=True,
                    deleted_on_success=None,
                )
            )
        yield


@workflow_templates_router.post(
    "/templates/validate", response_model=WorkflowTemplateValidationResponse
)
def validate_workflow_template(
    body: WorkflowTemplateValidateRequestBody,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[
        NodeCatalogRegistry, Depends(get_node_catalog_registry)
    ],
) -> WorkflowTemplateValidationResponse:
    """校验一份 workflow 图模板。"""

    _ = principal
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    validation_summary = service.validate_template(body.template)
    return _build_template_validation_response(validation_summary)


@workflow_templates_router.put(
    "/projects/{project_id}/templates/{template_id}/versions/{template_version}",
    response_model=WorkflowTemplateDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def save_workflow_template(
    project_id: str,
    template_id: str,
    template_version: str,
    body: WorkflowTemplateSaveRequestBody,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[
        NodeCatalogRegistry, Depends(get_node_catalog_registry)
    ],
) -> WorkflowTemplateDocumentResponse:
    """保存一份 workflow 图模板 JSON。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    _ensure_template_path_matches(
        template=body.template,
        template_id=template_id,
        template_version=template_version,
    )
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    with _template_lifecycle_operations(
        request,
        project_id=project_id,
        template_refs=((template_id, template_version),),
    ):
        document = service.save_template(
            project_id=project_id,
            template=body.template,
            actor_id=principal.principal_id,
        )
    return _build_template_document_response(document)


@workflow_templates_router.get(
    "/projects/{project_id}/templates",
    response_model=list[WorkflowTemplateSummaryResponse],
)
def list_workflow_templates(
    project_id: str,
    response: Response,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[
        NodeCatalogRegistry, Depends(get_node_catalog_registry)
    ],
    offset: Annotated[int, Query(ge=0, description="结果偏移量")] = 0,
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIST_LIMIT, description="最大返回数量")
    ] = DEFAULT_LIST_LIMIT,
) -> list[WorkflowTemplateSummaryResponse]:
    """列出指定 Project 下全部图模板摘要。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    template_summaries = service.list_templates(project_id=project_id)
    paged_items = paginate_sequence(
        template_summaries, response=response, offset=offset, limit=limit
    )
    return [_build_template_summary_response(item) for item in paged_items]


@workflow_templates_router.get(
    "/projects/{project_id}/templates/{template_id}/versions",
    response_model=list[WorkflowTemplateVersionSummaryResponse],
)
def list_workflow_template_versions(
    project_id: str,
    template_id: str,
    response: Response,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[
        NodeCatalogRegistry, Depends(get_node_catalog_registry)
    ],
    offset: Annotated[int, Query(ge=0, description="结果偏移量")] = 0,
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIST_LIMIT, description="最大返回数量")
    ] = DEFAULT_LIST_LIMIT,
) -> list[WorkflowTemplateVersionSummaryResponse]:
    """列出指定图模板的全部版本摘要。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    template_versions = service.list_template_versions(
        project_id=project_id, template_id=template_id
    )
    paged_items = paginate_sequence(
        template_versions, response=response, offset=offset, limit=limit
    )
    return [_build_template_version_summary_response(item) for item in paged_items]


@workflow_templates_router.get(
    "/projects/{project_id}/templates/{template_id}/versions/{template_version}",
    response_model=WorkflowTemplateDocumentResponse,
)
def get_workflow_template(
    project_id: str,
    template_id: str,
    template_version: str,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[
        NodeCatalogRegistry, Depends(get_node_catalog_registry)
    ],
) -> WorkflowTemplateDocumentResponse:
    """读取一份已保存的 workflow 图模板 JSON。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    document = service.get_template(
        project_id=project_id,
        template_id=template_id,
        template_version=template_version,
    )
    return _build_template_document_response(document)


@workflow_templates_router.get(
    "/projects/{project_id}/templates/{template_id}/latest",
    response_model=WorkflowTemplateDocumentResponse,
)
def get_latest_workflow_template(
    project_id: str,
    template_id: str,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[
        NodeCatalogRegistry, Depends(get_node_catalog_registry)
    ],
) -> WorkflowTemplateDocumentResponse:
    """读取一份模板当前可见的最新版本。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    document = service.get_latest_template(
        project_id=project_id, template_id=template_id
    )
    return _build_template_document_response(document)


@workflow_templates_router.post(
    "/projects/{project_id}/templates/{template_id}/versions/{template_version}/copy",
    response_model=WorkflowTemplateDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def copy_workflow_template_version(
    project_id: str,
    template_id: str,
    template_version: str,
    body: WorkflowTemplateCopyRequestBody,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[
        NodeCatalogRegistry, Depends(get_node_catalog_registry)
    ],
) -> WorkflowTemplateDocumentResponse:
    """复制一份已保存的 workflow 图模板版本。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    with _template_lifecycle_operations(
        request,
        project_id=project_id,
        template_refs=(
            (template_id, template_version),
            (body.target_template_id, body.target_template_version),
        ),
    ):
        document = service.copy_template_version(
            project_id=project_id,
            source_template_id=template_id,
            source_template_version=template_version,
            target_template_id=body.target_template_id,
            target_template_version=body.target_template_version,
            actor_id=principal.principal_id,
            display_name=body.display_name,
            description=body.description,
        )
    return _build_template_document_response(document)


@workflow_templates_router.delete(
    "/projects/{project_id}/templates/{template_id}/versions/{template_version}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_workflow_template(
    project_id: str,
    template_id: str,
    template_version: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[
        NodeCatalogRegistry, Depends(get_node_catalog_registry)
    ],
) -> Response:
    """删除一份已保存的 workflow 图模板版本。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    with _template_lifecycle_operations(
        request,
        project_id=project_id,
        template_refs=((template_id, template_version),),
    ):
        service.delete_template(
            project_id=project_id,
            template_id=template_id,
            template_version=template_version,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
