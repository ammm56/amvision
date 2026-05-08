"""workflow 模板与流程应用 REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.contracts.workflows.workflow_graph import FlowApplication, WorkflowGraphTemplate
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.nodes import get_node_catalog_registry
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import (
    InvalidRequestError,
    PermissionDeniedError,
)
from backend.service.application.workflows.workflow_service import (
    LocalWorkflowJsonService,
    WorkflowApplicationDocument,
    WorkflowApplicationValidationSummary,
    WorkflowTemplateDocument,
    WorkflowTemplateValidationSummary,
)
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


workflows_router = APIRouter(prefix="/workflows", tags=["workflows"])


class WorkflowTemplateValidateRequestBody(BaseModel):
    """描述图模板校验请求体。"""

    template: WorkflowGraphTemplate = Field(description="待校验的图模板")


class WorkflowApplicationValidateRequestBody(BaseModel):
    """描述流程应用校验请求体。"""

    project_id: str = Field(description="所属 Project id")
    application: FlowApplication = Field(description="待校验的流程应用")
    template: WorkflowGraphTemplate | None = Field(
        default=None,
        description="可选模板覆盖；提供时优先使用该模板进行校验",
    )


class WorkflowTemplateSaveRequestBody(BaseModel):
    """描述图模板保存请求体。"""

    template: WorkflowGraphTemplate = Field(description="待保存的图模板")


class WorkflowApplicationSaveRequestBody(BaseModel):
    """描述流程应用保存请求体。"""

    application: FlowApplication = Field(description="待保存的流程应用")


class WorkflowTemplateValidationResponse(BaseModel):
    """描述图模板校验响应。"""

    valid: bool = Field(description="当前模板是否通过校验")
    template_id: str = Field(description="模板 id")
    template_version: str = Field(description="模板版本")
    node_count: int = Field(description="节点数量")
    edge_count: int = Field(description="边数量")
    template_input_ids: list[str] = Field(default_factory=list, description="逻辑输入 id 列表")
    template_output_ids: list[str] = Field(default_factory=list, description="逻辑输出 id 列表")
    referenced_node_type_ids: list[str] = Field(default_factory=list, description="引用的节点类型 id 列表")


class WorkflowApplicationValidationResponse(BaseModel):
    """描述流程应用校验响应。"""

    valid: bool = Field(description="当前流程应用是否通过校验")
    application_id: str = Field(description="流程应用 id")
    template_id: str = Field(description="引用的模板 id")
    template_version: str = Field(description="引用的模板版本")
    binding_count: int = Field(description="绑定数量")
    input_binding_ids: list[str] = Field(default_factory=list, description="输入绑定 id 列表")
    output_binding_ids: list[str] = Field(default_factory=list, description="输出绑定 id 列表")


class WorkflowTemplateDocumentResponse(WorkflowTemplateValidationResponse):
    """描述图模板保存或读取响应。"""

    project_id: str = Field(description="所属 Project id")
    object_key: str = Field(description="模板 JSON 对象路径")
    template: WorkflowGraphTemplate = Field(description="图模板内容")


class WorkflowApplicationDocumentResponse(WorkflowApplicationValidationResponse):
    """描述流程应用保存或读取响应。"""

    project_id: str = Field(description="所属 Project id")
    object_key: str = Field(description="流程应用 JSON 对象路径")
    application: FlowApplication = Field(description="流程应用内容")


@workflows_router.post("/templates/validate", response_model=WorkflowTemplateValidationResponse)
def validate_workflow_template(
    body: WorkflowTemplateValidateRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
) -> WorkflowTemplateValidationResponse:
    """校验一份 workflow 图模板。"""

    _ = principal
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    validation_summary = service.validate_template(body.template)
    return _build_template_validation_response(validation_summary)


@workflows_router.put(
    "/projects/{project_id}/templates/{template_id}/versions/{template_version}",
    response_model=WorkflowTemplateDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def save_workflow_template(
    project_id: str,
    template_id: str,
    template_version: str,
    body: WorkflowTemplateSaveRequestBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
) -> WorkflowTemplateDocumentResponse:
    """保存一份 workflow 图模板 JSON。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    _ensure_template_path_matches(template=body.template, template_id=template_id, template_version=template_version)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    document = service.save_template(project_id=project_id, template=body.template)
    return _build_template_document_response(document)


@workflows_router.get(
    "/projects/{project_id}/templates/{template_id}/versions/{template_version}",
    response_model=WorkflowTemplateDocumentResponse,
)
def get_workflow_template(
    project_id: str,
    template_id: str,
    template_version: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
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


@workflows_router.post("/applications/validate", response_model=WorkflowApplicationValidationResponse)
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


@workflows_router.put(
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
    document = service.save_application(project_id=project_id, application=body.application)
    return _build_application_document_response(document)


@workflows_router.get(
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
    return _build_application_document_response(document)


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
            "template": document.template,
        }
    )
    return WorkflowTemplateDocumentResponse.model_validate(payload)


def _build_application_document_response(
    document: WorkflowApplicationDocument,
) -> WorkflowApplicationDocumentResponse:
    """构建流程应用保存或读取响应。"""

    payload = _build_application_validation_response(document.validation_summary).model_dump(mode="python")
    payload.update(
        {
            "project_id": document.project_id,
            "object_key": document.object_key,
            "application": document.application,
        }
    )
    return WorkflowApplicationDocumentResponse.model_validate(payload)


def _build_application_execute_response(
    execution_result,
) -> WorkflowApplicationExecuteResponse:
    """构建 workflow application 执行响应。"""

    return WorkflowApplicationExecuteResponse(
        project_id=execution_result.project_id,
        application_id=execution_result.application_id,
        template_id=execution_result.template_id,
        template_version=execution_result.template_version,
        outputs=dict(execution_result.outputs),
        template_outputs=dict(execution_result.template_outputs),
        node_records=[
            WorkflowNodeExecutionRecordResponse(
                node_id=node_record.node_id,
                node_type_id=node_record.node_type_id,
                runtime_kind=node_record.runtime_kind,
                outputs=dict(node_record.outputs),
            )
            for node_record in execution_result.node_records
        ],
    )