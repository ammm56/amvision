"""workflow application 文档路由。"""

from __future__ import annotations

from contextlib import ExitStack
from typing import Annotated

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
from backend.service.application.workflows.model_sessions import (
    build_workflow_preview_model_session_scope_id,
)
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from backend.service.application.workflows.app_version_service import (
    WorkflowAppVersionDetail,
    WorkflowAppVersionService,
)
from backend.service.application.workflows.application_lifecycle import (
    WorkflowApplicationLifecycleService,
)
from backend.service.application.workflows.lifecycle_resource_keys import (
    build_workflow_template_lifecycle_resource_key,
)
from backend.service.application.workflows.documents.storage import (
    normalize_application_identifier,
)
from backend.service.application.errors import InvalidRequestError, ResourceInUseError
from backend.service.domain.workflows.workflow_runtime_records import WorkflowAppVersion

from .documents import (
    _build_application_document_response,
    _build_application_summary_response,
    _build_application_validation_response,
    _build_template_document_response,
    _build_workflow_json_service,
    _ensure_application_path_matches,
    _ensure_project_visible,
)
from .schemas import (
    WorkflowApplicationCopyRequestBody,
    WorkflowApplicationBundleSaveResponse,
    WorkflowApplicationDocumentResponse,
    WorkflowApplicationSaveRequestBody,
    WorkflowApplicationSummaryResponse,
    WorkflowApplicationUpdateRequestBody,
    WorkflowApplicationValidateRequestBody,
    WorkflowApplicationValidationResponse,
    WorkflowAppVersionComparisonResponse,
    WorkflowAppVersionArchiveRequestBody,
    WorkflowAppVersionDetailResponse,
    WorkflowAppVersionPublishRequestBody,
    WorkflowAppVersionResponse,
    WorkflowAppVersionRestoreRequestBody,
)


workflow_applications_router = APIRouter()


def _build_app_version_service(request: Request) -> WorkflowAppVersionService:
    """从应用状态构建 Workflow App 版本服务。"""

    from backend.service.api.rest.v1.routes.workflow_runtime_support.services import (  # noqa: PLC0415
        require_dataset_storage,
        require_node_catalog_registry,
        require_session_factory,
    )

    return WorkflowAppVersionService(
        session_factory=require_session_factory(request),
        dataset_storage=require_dataset_storage(request),
        node_catalog_registry=require_node_catalog_registry(request),
    )


def _build_application_lifecycle_service(
    request: Request,
) -> WorkflowApplicationLifecycleService:
    """从应用状态构建 Workflow Application 写操作协调服务。"""

    from backend.service.api.rest.v1.routes.workflow_runtime_support.services import (  # noqa: PLC0415
        require_dataset_storage,
        require_session_factory,
    )

    return WorkflowApplicationLifecycleService(
        session_factory=require_session_factory(request),
        dataset_storage=require_dataset_storage(request),
    )


def _build_app_version_response(
    version: WorkflowAppVersion,
) -> WorkflowAppVersionResponse:
    """构建 Workflow App 版本响应。"""

    return WorkflowAppVersionResponse.model_validate(version.__dict__)


def _build_app_version_detail_response(
    detail: WorkflowAppVersionDetail,
) -> WorkflowAppVersionDetailResponse:
    """构建 Workflow App 版本详情响应。"""

    return WorkflowAppVersionDetailResponse.model_validate(
        {
            **detail.version.__dict__,
            "application": detail.application,
            "template": detail.template,
            "contract": detail.contract,
            "dependencies": detail.dependencies,
            "manifest": detail.manifest,
        }
    )


@workflow_applications_router.post(
    "/applications/validate", response_model=WorkflowApplicationValidationResponse
)
def validate_flow_application(
    body: WorkflowApplicationValidateRequestBody,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[
        NodeCatalogRegistry, Depends(get_node_catalog_registry)
    ],
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
    response_model=(
        WorkflowApplicationBundleSaveResponse | WorkflowApplicationDocumentResponse
    ),
    status_code=status.HTTP_201_CREATED,
)
def save_flow_application(
    project_id: str,
    application_id: str,
    body: WorkflowApplicationSaveRequestBody,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[
        NodeCatalogRegistry, Depends(get_node_catalog_registry)
    ],
) -> WorkflowApplicationBundleSaveResponse | WorkflowApplicationDocumentResponse:
    """保存一份流程应用 JSON。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    _ensure_application_path_matches(
        application=body.application, application_id=application_id
    )
    if body.template is not None and (
        body.application.template_ref.template_id != body.template.template_id
        or body.application.template_ref.template_version
        != body.template.template_version
    ):
        raise InvalidRequestError(
            "Workflow Application 与 Template 引用不一致",
            details={
                "application_template_id": body.application.template_ref.template_id,
                "application_template_version": body.application.template_ref.template_version,
                "template_id": body.template.template_id,
                "template_version": body.template.template_version,
            },
        )
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    lifecycle_service = _build_application_lifecycle_service(request)
    with lifecycle_service.operation(
        project_id=project_id,
        application_id=application_id,
        operation="saving",
        allow_deleted=True,
        deleted_on_success=False,
    ) as application_claim:
        assert application_claim.operation_id is not None
        template_resource_key = build_workflow_template_lifecycle_resource_key(
            template_id=body.application.template_ref.template_id,
            template_version=body.application.template_ref.template_version,
        )
        with lifecycle_service.operation(
            project_id=project_id,
            application_id=template_resource_key,
            operation="saving",
            allow_deleted=True,
            deleted_on_success=None,
        ):
            if body.template is None:
                document = service.save_application(
                    project_id=project_id,
                    application=body.application,
                    actor_id=principal.principal_id,
                )
                return _build_application_document_response(
                    document,
                    workflow_service=service,
                )
            bundle = service.save_application_bundle(
                project_id=project_id,
                application=body.application,
                template=body.template,
                operation_id=application_claim.operation_id,
                actor_id=principal.principal_id,
            )
            application_response = _build_application_document_response(
                bundle.application_document,
                workflow_service=service,
            )
            return WorkflowApplicationBundleSaveResponse.model_validate(
                {
                    **application_response.model_dump(mode="python"),
                    "saved_template": _build_template_document_response(
                        bundle.template_document
                    ),
                }
            )


@workflow_applications_router.patch(
    "/projects/{project_id}/applications/{application_id}",
    response_model=WorkflowApplicationDocumentResponse,
)
def update_flow_application_metadata(
    project_id: str,
    application_id: str,
    body: WorkflowApplicationUpdateRequestBody,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[
        NodeCatalogRegistry, Depends(get_node_catalog_registry)
    ],
) -> WorkflowApplicationDocumentResponse:
    """更新流程应用名称、说明等基础信息。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    application_id = normalize_application_identifier(application_id, "application_id")
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    lifecycle_service = _build_application_lifecycle_service(request)
    with lifecycle_service.operation(
        project_id=project_id,
        application_id=application_id,
        operation="saving",
        deleted_on_success=False,
    ):
        application = service.get_application(
            project_id=project_id,
            application_id=application_id,
        ).application
        template_resource_key = build_workflow_template_lifecycle_resource_key(
            template_id=application.template_ref.template_id,
            template_version=application.template_ref.template_version,
        )
        with lifecycle_service.operation(
            project_id=project_id,
            application_id=template_resource_key,
            operation="saving",
            allow_deleted=True,
            deleted_on_success=None,
        ):
            document = service.update_application_metadata(
                project_id=project_id,
                application_id=application_id,
                actor_id=principal.principal_id,
                display_name=body.display_name,
                description=body.description,
            )
            return _build_application_document_response(
                document,
                workflow_service=service,
            )


@workflow_applications_router.get(
    "/projects/{project_id}/applications",
    response_model=list[WorkflowApplicationSummaryResponse],
)
def list_flow_applications(
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
) -> list[WorkflowApplicationSummaryResponse]:
    """列出指定 Project 下全部流程应用摘要。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    applications = service.list_applications(project_id=project_id)
    paged_items = paginate_sequence(
        applications, response=response, offset=offset, limit=limit
    )
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
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[
        NodeCatalogRegistry, Depends(get_node_catalog_registry)
    ],
) -> WorkflowApplicationDocumentResponse:
    """读取一份已保存的流程应用 JSON。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    document = service.get_application(
        project_id=project_id, application_id=application_id
    )
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
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[
        NodeCatalogRegistry, Depends(get_node_catalog_registry)
    ],
) -> WorkflowApplicationDocumentResponse:
    """复制一份已保存的流程应用。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    application_id = normalize_application_identifier(application_id, "application_id")
    target_application_id = normalize_application_identifier(
        body.target_application_id,
        "target_application_id",
    )
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    lifecycle_service = _build_application_lifecycle_service(request)
    with ExitStack() as stack:
        for locked_application_id in sorted({application_id, target_application_id}):
            stack.enter_context(
                lifecycle_service.operation(
                    project_id=project_id,
                    application_id=locked_application_id,
                    operation="saving",
                    allow_deleted=locked_application_id == target_application_id,
                    deleted_on_success=False,
                )
            )
        source_application = service.get_application(
            project_id=project_id,
            application_id=application_id,
        ).application
        template_resource_key = build_workflow_template_lifecycle_resource_key(
            template_id=source_application.template_ref.template_id,
            template_version=source_application.template_ref.template_version,
        )
        with lifecycle_service.operation(
            project_id=project_id,
            application_id=template_resource_key,
            operation="saving",
            allow_deleted=True,
            deleted_on_success=None,
        ):
            document = service.copy_application(
                project_id=project_id,
                source_application_id=application_id,
                target_application_id=target_application_id,
                actor_id=principal.principal_id,
                display_name=body.display_name,
                description=body.description,
            )
            return _build_application_document_response(
                document,
                workflow_service=service,
            )


@workflow_applications_router.delete(
    "/projects/{project_id}/applications/{application_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_flow_application(
    project_id: str,
    application_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[
        NodeCatalogRegistry, Depends(get_node_catalog_registry)
    ],
) -> Response:
    """删除一份已保存的流程应用。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    application_id = normalize_application_identifier(application_id, "application_id")
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    with _build_application_lifecycle_service(request).operation(
        project_id=project_id,
        application_id=application_id,
        operation="deleting",
        deleted_on_success=True,
    ):
        versions = _build_app_version_service(request).list_versions(
            project_id=project_id,
            application_id=application_id,
            include_incomplete=True,
        )
        retained_versions = tuple(item for item in versions if item.state != "failed")
        if retained_versions:
            raise ResourceInUseError(
                "Workflow App 已存在版本记录，不能物理删除草稿",
                details={
                    "application_id": application_id,
                    "workflow_app_version_ids": [
                        item.workflow_app_version_id for item in retained_versions
                    ],
                },
            )
        runtime_context = getattr(
            request.app.state,
            "workflow_service_node_runtime_context",
            None,
        )
        if isinstance(runtime_context, WorkflowServiceNodeRuntimeContext):
            preview_scope_id = build_workflow_preview_model_session_scope_id(
                project_id=project_id,
                application_id=application_id,
            )
            model_session_manager = runtime_context.workflow_model_session_manager
            if model_session_manager is not None:
                model_session_manager.close_scope(
                    preview_scope_id,
                    wait=False,
                )
            storage_image_cache = runtime_context.workflow_storage_image_cache
            if storage_image_cache is not None:
                storage_image_cache.clear_shared_scope(preview_scope_id)
        service.delete_application(project_id=project_id, application_id=application_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@workflow_applications_router.post(
    "/projects/{project_id}/applications/{application_id}/versions",
    response_model=WorkflowAppVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def publish_workflow_app_version(
    project_id: str,
    application_id: str,
    body: WorkflowAppVersionPublishRequestBody,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
) -> WorkflowAppVersionResponse:
    """把当前 Workflow App 草稿发布为不可变版本。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    version = _build_app_version_service(request).publish_version(
        project_id=project_id,
        application_id=application_id,
        expected_draft_fingerprint=body.expected_draft_fingerprint,
        release_notes=body.release_notes,
        display_version=body.display_version,
        created_by=principal.principal_id,
        allow_duplicate_content=body.allow_duplicate_content,
    )
    return _build_app_version_response(version)


@workflow_applications_router.get(
    "/projects/{project_id}/applications/{application_id}/versions",
    response_model=list[WorkflowAppVersionResponse],
)
def list_workflow_app_versions(
    project_id: str,
    application_id: str,
    request: Request,
    response: Response,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
    offset: Annotated[int, Query(ge=0, description="结果偏移量")] = 0,
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIST_LIMIT, description="最大返回数量")
    ] = DEFAULT_LIST_LIMIT,
) -> list[WorkflowAppVersionResponse]:
    """列出 Workflow App 的不可变版本。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    versions = _build_app_version_service(request).list_versions(
        project_id=project_id,
        application_id=application_id,
    )
    return [
        _build_app_version_response(item)
        for item in paginate_sequence(
            versions,
            response=response,
            offset=offset,
            limit=limit,
        )
    ]


@workflow_applications_router.post(
    "/projects/{project_id}/applications/{application_id}/versions/{workflow_app_version_id}/archive",
    response_model=WorkflowAppVersionResponse,
)
def archive_workflow_app_version(
    project_id: str,
    application_id: str,
    workflow_app_version_id: str,
    body: WorkflowAppVersionArchiveRequestBody,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
) -> WorkflowAppVersionResponse:
    """归档版本；已存在的 Runtime revision 和 Run 追溯保持不变。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    version = _build_app_version_service(request).archive_version(
        project_id=project_id,
        application_id=application_id,
        workflow_app_version_id=workflow_app_version_id,
        expected_state=body.expected_state,
    )
    return _build_app_version_response(version)


@workflow_applications_router.post(
    "/projects/{project_id}/applications/{application_id}/versions/{workflow_app_version_id}/restore",
    response_model=WorkflowAppVersionResponse,
)
def restore_workflow_app_version(
    project_id: str,
    application_id: str,
    workflow_app_version_id: str,
    body: WorkflowAppVersionRestoreRequestBody,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
) -> WorkflowAppVersionResponse:
    """恢复归档版本，使其重新可用于新 Runtime 或切版。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    version = _build_app_version_service(request).restore_version(
        project_id=project_id,
        application_id=application_id,
        workflow_app_version_id=workflow_app_version_id,
        expected_state=body.expected_state,
    )
    return _build_app_version_response(version)


@workflow_applications_router.get(
    "/projects/{project_id}/applications/{application_id}/versions/{workflow_app_version_id}",
    response_model=WorkflowAppVersionDetailResponse,
)
def get_workflow_app_version(
    project_id: str,
    application_id: str,
    workflow_app_version_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
) -> WorkflowAppVersionDetailResponse:
    """读取 Workflow App 版本及其不可变快照。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    detail = _build_app_version_service(request).get_version_detail(
        project_id=project_id,
        application_id=application_id,
        workflow_app_version_id=workflow_app_version_id,
    )
    return _build_app_version_detail_response(detail)


@workflow_applications_router.get(
    "/projects/{project_id}/applications/{application_id}/versions/{workflow_app_version_id}/compare",
    response_model=WorkflowAppVersionComparisonResponse,
)
def compare_workflow_app_version_to_draft(
    project_id: str,
    application_id: str,
    workflow_app_version_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
) -> WorkflowAppVersionComparisonResponse:
    """比较已发布版本与当前草稿的公开契约。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    comparison = _build_app_version_service(request).compare_version_to_draft(
        project_id=project_id,
        application_id=application_id,
        workflow_app_version_id=workflow_app_version_id,
    )
    return WorkflowAppVersionComparisonResponse.model_validate(comparison)
