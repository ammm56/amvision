"""workflow 文档路由支撑函数。"""

from __future__ import annotations


from backend.contracts.workflows.workflow_graph import FlowApplication, WorkflowGraphTemplate
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.application.errors import InvalidRequestError, PermissionDeniedError, ResourceNotFoundError
from backend.service.application.workflows.documents.contracts import (
    WorkflowApplicationDocument,
    WorkflowApplicationSummary,
    WorkflowApplicationValidationSummary,
    WorkflowTemplateDocument,
    WorkflowTemplateSummary,
    WorkflowTemplateValidationSummary,
    WorkflowTemplateVersionSummary,
)
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage

from .schemas import (
    WorkflowApplicationDocumentResponse,
    WorkflowApplicationSummaryResponse,
    WorkflowApplicationValidationResponse,
    WorkflowTemplateDocumentResponse,
    WorkflowTemplateReferenceSummaryResponse,
    WorkflowTemplateSummaryResponse,
    WorkflowTemplateValidationResponse,
    WorkflowTemplateVersionSummaryResponse,
)

def _build_workflow_json_service(
    *,
    dataset_storage: LocalDatasetStorage,
    node_catalog_registry: NodeCatalogRegistry,
) -> LocalWorkflowJsonService:
    """构建带 NodeCatalogRegistry 的 workflow 文件服务。"""

    return LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )




def _ensure_project_visible(*, principal: AuthenticatedPrincipal, project_id: str) -> None:
    """校验当前主体是否可访问指定 Project。"""

    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": project_id},
        )


def _ensure_template_path_matches(
    *,
    template: WorkflowGraphTemplate,
    template_id: str,
    template_version: str,
) -> None:
    """校验路径参数与模板体内 id/version 一致。"""

    if template.template_id != template_id or template.template_version != template_version:
        raise InvalidRequestError(
            "模板路径参数与请求体中的 template_id 或 template_version 不一致",
            details={
                "path_template_id": template_id,
                "path_template_version": template_version,
                "body_template_id": template.template_id,
                "body_template_version": template.template_version,
            },
        )


def _ensure_application_path_matches(*, application: FlowApplication, application_id: str) -> None:
    """校验路径参数与流程应用体内 application_id 一致。"""

    if application.application_id != application_id:
        raise InvalidRequestError(
            "流程应用路径参数与请求体中的 application_id 不一致",
            details={
                "path_application_id": application_id,
                "body_application_id": application.application_id,
            },
        )


def _build_template_validation_response(
    validation_summary: WorkflowTemplateValidationSummary,
) -> WorkflowTemplateValidationResponse:
    """构建图模板校验响应。"""

    return WorkflowTemplateValidationResponse(
        valid=True,
        template_id=validation_summary.template_id,
        template_version=validation_summary.template_version,
        node_count=validation_summary.node_count,
        edge_count=validation_summary.edge_count,
        template_input_ids=list(validation_summary.template_input_ids),
        template_output_ids=list(validation_summary.template_output_ids),
        referenced_node_type_ids=list(validation_summary.referenced_node_type_ids),
    )


def _build_application_validation_response(
    validation_summary: WorkflowApplicationValidationSummary,
) -> WorkflowApplicationValidationResponse:
    """构建流程应用校验响应。"""

    return WorkflowApplicationValidationResponse(
        valid=True,
        application_id=validation_summary.application_id,
        template_id=validation_summary.template_id,
        template_version=validation_summary.template_version,
        binding_count=validation_summary.binding_count,
        input_binding_ids=list(validation_summary.input_binding_ids),
        output_binding_ids=list(validation_summary.output_binding_ids),
    )


def _build_template_document_response(
    document: WorkflowTemplateDocument,
) -> WorkflowTemplateDocumentResponse:
    """构建图模板保存或读取响应。"""

    payload = _build_template_validation_response(document.validation_summary).model_dump(mode="python")
    payload.update(
        {
            "project_id": document.project_id,
            "object_key": document.object_key,
            "created_at": document.resource_summary.created_at,
            "updated_at": document.resource_summary.updated_at,
            "created_by": document.resource_summary.created_by,
            "updated_by": document.resource_summary.updated_by,
            "template": document.template,
        }
    )
    return WorkflowTemplateDocumentResponse.model_validate(payload)


def _build_template_summary_response(
    summary: WorkflowTemplateSummary,
) -> WorkflowTemplateSummaryResponse:
    """构建图模板聚合摘要响应。"""

    return WorkflowTemplateSummaryResponse(
        project_id=summary.project_id,
        template_id=summary.template_id,
        display_name=summary.display_name,
        description=summary.description,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        created_by=summary.created_by,
        updated_by=summary.updated_by,
        latest_template_version=summary.latest_template_version,
        version_count=summary.version_count,
        versions=list(summary.versions),
    )


def _build_template_version_summary_response(
    summary: WorkflowTemplateVersionSummary,
) -> WorkflowTemplateVersionSummaryResponse:
    """构建图模板版本摘要响应。"""

    return WorkflowTemplateVersionSummaryResponse(
        project_id=summary.project_id,
        object_key=summary.object_key,
        template_id=summary.template_id,
        template_version=summary.template_version,
        display_name=summary.display_name,
        description=summary.description,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        created_by=summary.created_by,
        updated_by=summary.updated_by,
        node_count=summary.node_count,
        edge_count=summary.edge_count,
        template_input_ids=list(summary.template_input_ids),
        template_output_ids=list(summary.template_output_ids),
        referenced_node_type_ids=list(summary.referenced_node_type_ids),
    )


def _build_template_reference_summary_response(
    summary: WorkflowTemplateVersionSummary,
) -> WorkflowTemplateReferenceSummaryResponse:
    """构建模板一跳摘要响应。"""

    return WorkflowTemplateReferenceSummaryResponse(
        project_id=summary.project_id,
        template_id=summary.template_id,
        template_version=summary.template_version,
        display_name=summary.display_name,
        description=summary.description,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        created_by=summary.created_by,
        updated_by=summary.updated_by,
    )


def _try_build_template_reference_summary_response(
    *,
    workflow_service: LocalWorkflowJsonService,
    project_id: str,
    template_id: str,
    template_version: str,
) -> WorkflowTemplateReferenceSummaryResponse | None:
    """按需读取模板一跳摘要，不存在时返回 None。"""

    try:
        summary = workflow_service.get_template_version_summary(
            project_id=project_id,
            template_id=template_id,
            template_version=template_version,
        )
    except ResourceNotFoundError:
        return None
    return _build_template_reference_summary_response(summary)


def _build_application_document_response(
    document: WorkflowApplicationDocument,
    *,
    workflow_service: LocalWorkflowJsonService,
) -> WorkflowApplicationDocumentResponse:
    """构建流程应用保存或读取响应。"""

    payload = _build_application_validation_response(document.validation_summary).model_dump(mode="python")
    payload.update(
        {
            "project_id": document.project_id,
            "object_key": document.object_key,
            "created_at": document.resource_summary.created_at,
            "updated_at": document.resource_summary.updated_at,
            "created_by": document.resource_summary.created_by,
            "updated_by": document.resource_summary.updated_by,
            "template_summary": _try_build_template_reference_summary_response(
                workflow_service=workflow_service,
                project_id=document.project_id,
                template_id=document.application.template_ref.template_id,
                template_version=document.application.template_ref.template_version,
            ),
            "application": document.application,
        }
    )
    return WorkflowApplicationDocumentResponse.model_validate(payload)


def _build_application_summary_response(
    summary: WorkflowApplicationSummary,
    *,
    workflow_service: LocalWorkflowJsonService,
) -> WorkflowApplicationSummaryResponse:
    """构建流程应用摘要响应。"""

    return WorkflowApplicationSummaryResponse(
        project_id=summary.project_id,
        object_key=summary.object_key,
        application_id=summary.application_id,
        display_name=summary.display_name,
        description=summary.description,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        created_by=summary.created_by,
        updated_by=summary.updated_by,
        template_id=summary.template_id,
        template_version=summary.template_version,
        template_summary=_try_build_template_reference_summary_response(
            workflow_service=workflow_service,
            project_id=summary.project_id,
            template_id=summary.template_id,
            template_version=summary.template_version,
        ),
        binding_count=summary.binding_count,
        input_binding_ids=list(summary.input_binding_ids),
        output_binding_ids=list(summary.output_binding_ids),
    )

