"""workflow 模板与流程应用 REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from backend.contracts.nodes import NodePackManifest
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    NodeDefinition,
    WorkflowGraphTemplate,
    WorkflowPayloadContract,
)
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.nodes import get_node_catalog_registry
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.application.errors import (
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from backend.service.application.workflows.workflow_service import (
    LocalWorkflowJsonService,
    WorkflowApplicationDocument,
    WorkflowApplicationSummary,
    WorkflowApplicationValidationSummary,
    WorkflowTemplateDocument,
    WorkflowTemplateSummary,
    WorkflowTemplateVersionSummary,
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
    created_at: str = Field(description="模板版本创建时间")
    updated_at: str = Field(description="模板版本更新时间")
    created_by: str | None = Field(default=None, description="模板版本创建主体 id")
    updated_by: str | None = Field(default=None, description="模板版本最近修改主体 id")
    template: WorkflowGraphTemplate = Field(description="图模板内容")


class WorkflowApplicationDocumentResponse(WorkflowApplicationValidationResponse):
    """描述流程应用保存或读取响应。"""

    project_id: str = Field(description="所属 Project id")
    object_key: str = Field(description="流程应用 JSON 对象路径")
    created_at: str = Field(description="流程应用创建时间")
    updated_at: str = Field(description="流程应用更新时间")
    created_by: str | None = Field(default=None, description="流程应用创建主体 id")
    updated_by: str | None = Field(default=None, description="流程应用最近修改主体 id")
    template_summary: "WorkflowTemplateReferenceSummaryResponse | None" = Field(
        default=None,
        description="引用模板的一跳摘要",
    )
    application: FlowApplication = Field(description="流程应用内容")


class WorkflowTemplateReferenceSummaryResponse(BaseModel):
    """描述流程应用引用模板的一跳摘要。"""

    project_id: str = Field(description="所属 Project id")
    template_id: str = Field(description="模板 id")
    template_version: str = Field(description="模板版本")
    display_name: str = Field(description="模板显示名称")
    description: str = Field(description="模板说明")
    created_at: str = Field(description="模板版本创建时间")
    updated_at: str = Field(description="模板版本更新时间")
    created_by: str | None = Field(default=None, description="模板版本创建主体 id")
    updated_by: str | None = Field(default=None, description="模板版本最近修改主体 id")


class WorkflowNodeCatalogResponse(BaseModel):
    """描述当前 workflow 节点目录快照响应。

    字段：
    - node_pack_manifests：当前已发现的节点包 manifest 列表。
    - payload_contracts：当前已注册的 payload contract 列表。
    - node_definitions：当前已注册的节点定义列表。
    - palette_groups：按节点分类整理后的 palette 分组结果。
    """

    node_pack_manifests: list[NodePackManifest] = Field(default_factory=list, description="节点包 manifest 列表")
    payload_contracts: list[WorkflowPayloadContract] = Field(
        default_factory=list,
        description="payload contract 列表",
    )
    node_definitions: list[NodeDefinition] = Field(default_factory=list, description="节点定义列表")
    palette_groups: list["WorkflowNodePaletteGroupResponse"] = Field(
        default_factory=list,
        description="按分类分组后的 palette 结果",
    )


class WorkflowNodePaletteGroupResponse(BaseModel):
    """描述前端可直接消费的节点 palette 分组结果。"""

    category: str = Field(description="节点分类 id")
    display_name: str = Field(description="分组显示名称")
    item_count: int = Field(description="当前分组的节点数量")
    node_definitions: list[NodeDefinition] = Field(default_factory=list, description="当前分组下的节点定义列表")


class WorkflowTemplateSummaryResponse(BaseModel):
    """描述图模板聚合摘要响应。"""

    project_id: str = Field(description="所属 Project id")
    template_id: str = Field(description="模板 id")
    display_name: str = Field(description="模板显示名称")
    description: str = Field(description="模板说明")
    created_at: str = Field(description="模板最早版本创建时间")
    updated_at: str = Field(description="模板最近更新时间")
    created_by: str | None = Field(default=None, description="模板最早版本创建主体 id")
    updated_by: str | None = Field(default=None, description="模板最近修改主体 id")
    latest_template_version: str = Field(description="当前最新模板版本")
    version_count: int = Field(description="当前模板版本数量")
    versions: list[str] = Field(default_factory=list, description="全部模板版本 id 列表")


class WorkflowTemplateVersionSummaryResponse(BaseModel):
    """描述图模板版本摘要响应。"""

    project_id: str = Field(description="所属 Project id")
    object_key: str = Field(description="模板 JSON 对象路径")
    template_id: str = Field(description="模板 id")
    template_version: str = Field(description="模板版本")
    display_name: str = Field(description="模板显示名称")
    description: str = Field(description="模板说明")
    created_at: str = Field(description="模板版本创建时间")
    updated_at: str = Field(description="模板版本更新时间")
    created_by: str | None = Field(default=None, description="模板版本创建主体 id")
    updated_by: str | None = Field(default=None, description="模板版本最近修改主体 id")
    node_count: int = Field(description="节点数量")
    edge_count: int = Field(description="边数量")
    template_input_ids: list[str] = Field(default_factory=list, description="逻辑输入 id 列表")
    template_output_ids: list[str] = Field(default_factory=list, description="逻辑输出 id 列表")
    referenced_node_type_ids: list[str] = Field(default_factory=list, description="引用的节点类型 id 列表")


class WorkflowApplicationSummaryResponse(BaseModel):
    """描述流程应用摘要响应。"""

    project_id: str = Field(description="所属 Project id")
    object_key: str = Field(description="流程应用 JSON 对象路径")
    application_id: str = Field(description="流程应用 id")
    display_name: str = Field(description="流程应用显示名称")
    description: str = Field(description="流程应用说明")
    created_at: str = Field(description="流程应用创建时间")
    updated_at: str = Field(description="流程应用更新时间")
    created_by: str | None = Field(default=None, description="流程应用创建主体 id")
    updated_by: str | None = Field(default=None, description="流程应用最近修改主体 id")
    template_id: str = Field(description="引用的模板 id")
    template_version: str = Field(description="引用的模板版本")
    template_summary: WorkflowTemplateReferenceSummaryResponse | None = Field(
        default=None,
        description="引用模板的一跳摘要",
    )
    binding_count: int = Field(description="绑定数量")
    input_binding_ids: list[str] = Field(default_factory=list, description="输入绑定 id 列表")
    output_binding_ids: list[str] = Field(default_factory=list, description="输出绑定 id 列表")


@workflows_router.get("/node-catalog", response_model=WorkflowNodeCatalogResponse)
def get_workflow_node_catalog(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
    category: Annotated[str | None, Query(description="按节点分类前缀过滤")] = None,
    node_pack_id: Annotated[str | None, Query(description="按节点包 id 过滤")] = None,
    payload_type_id: Annotated[str | None, Query(description="按端口 payload 类型过滤")] = None,
    q: Annotated[str | None, Query(description="按节点类型 id、显示名称或说明搜索")] = None,
) -> WorkflowNodeCatalogResponse:
    """按查询条件读取当前 workflow 节点目录快照。

    参数：
    - category：可选节点分类前缀过滤条件。
    - node_pack_id：可选节点包 id 过滤条件。
    - payload_type_id：可选端口 payload 类型过滤条件。
    - q：可选关键词搜索条件。
    - principal：当前认证主体。
    - node_catalog_registry：统一节点目录注册表。

    返回：
    - WorkflowNodeCatalogResponse：按条件过滤后的节点目录快照。
    """

    _ = principal
    catalog_snapshot = node_catalog_registry.get_catalog_snapshot()
    filtered_node_definitions = _filter_workflow_node_definitions(
        node_definitions=catalog_snapshot.node_definitions,
        category=category,
        node_pack_id=node_pack_id,
        payload_type_id=payload_type_id,
        keyword=q,
    )
    filtered_payload_contracts = _filter_workflow_payload_contracts(
        payload_contracts=catalog_snapshot.payload_contracts,
        node_definitions=filtered_node_definitions,
        payload_type_id=payload_type_id,
        filters_active=any(item is not None and item.strip() for item in (category, node_pack_id, payload_type_id, q)),
    )
    filtered_node_pack_manifests = _filter_node_pack_manifests(
        node_pack_manifests=catalog_snapshot.node_pack_manifests,
        node_definitions=filtered_node_definitions,
        node_pack_id=node_pack_id,
        filters_active=any(item is not None and item.strip() for item in (category, node_pack_id, payload_type_id, q)),
    )
    return WorkflowNodeCatalogResponse(
        node_pack_manifests=filtered_node_pack_manifests,
        payload_contracts=filtered_payload_contracts,
        node_definitions=filtered_node_definitions,
        palette_groups=_build_workflow_node_palette_groups(filtered_node_definitions),
    )


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
    document = service.save_template(
        project_id=project_id,
        template=body.template,
        actor_id=principal.principal_id,
    )
    return _build_template_document_response(document)


@workflows_router.get(
    "/projects/{project_id}/templates",
    response_model=list[WorkflowTemplateSummaryResponse],
)
def list_workflow_templates(
    project_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
) -> list[WorkflowTemplateSummaryResponse]:
    """列出指定 Project 下全部图模板摘要。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    return [_build_template_summary_response(item) for item in service.list_templates(project_id=project_id)]


@workflows_router.get(
    "/projects/{project_id}/templates/{template_id}/versions",
    response_model=list[WorkflowTemplateVersionSummaryResponse],
)
def list_workflow_template_versions(
    project_id: str,
    template_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
) -> list[WorkflowTemplateVersionSummaryResponse]:
    """列出指定图模板的全部版本摘要。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    return [
        _build_template_version_summary_response(item)
        for item in service.list_template_versions(project_id=project_id, template_id=template_id)
    ]


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


@workflows_router.delete(
    "/projects/{project_id}/templates/{template_id}/versions/{template_version}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_workflow_template(
    project_id: str,
    template_id: str,
    template_version: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
) -> Response:
    """删除一份已保存的 workflow 图模板版本。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    service.delete_template(
        project_id=project_id,
        template_id=template_id,
        template_version=template_version,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    document = service.save_application(
        project_id=project_id,
        application=body.application,
        actor_id=principal.principal_id,
    )
    return _build_application_document_response(document, workflow_service=service)


@workflows_router.get(
    "/projects/{project_id}/applications",
    response_model=list[WorkflowApplicationSummaryResponse],
)
def list_flow_applications(
    project_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))],
    dataset_storage: Annotated[LocalDatasetStorage, Depends(get_dataset_storage)],
    node_catalog_registry: Annotated[NodeCatalogRegistry, Depends(get_node_catalog_registry)],
) -> list[WorkflowApplicationSummaryResponse]:
    """列出指定 Project 下全部流程应用摘要。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    service = _build_workflow_json_service(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    return [
        _build_application_summary_response(item, workflow_service=service)
        for item in service.list_applications(project_id=project_id)
    ]


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
    return _build_application_document_response(document, workflow_service=service)


@workflows_router.delete(
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


def _build_workflow_node_palette_groups(
    node_definitions: list[NodeDefinition],
) -> list[WorkflowNodePaletteGroupResponse]:
    """把节点定义整理为前端可直接消费的 palette 分组结果。"""

    grouped_nodes: dict[str, list[NodeDefinition]] = {}
    for node_definition in node_definitions:
        grouped_nodes.setdefault(node_definition.category, []).append(node_definition)

    palette_groups: list[WorkflowNodePaletteGroupResponse] = []
    for category in sorted(grouped_nodes):
        grouped_items = sorted(
            grouped_nodes[category],
            key=lambda item: (item.display_name.casefold(), item.node_type_id.casefold()),
        )
        palette_groups.append(
            WorkflowNodePaletteGroupResponse(
                category=category,
                display_name=_build_workflow_palette_group_display_name(category),
                item_count=len(grouped_items),
                node_definitions=grouped_items,
            )
        )
    return palette_groups


def _build_workflow_palette_group_display_name(category: str) -> str:
    """把节点分类 id 转换为更适合 palette 展示的分组名称。"""

    category_tokens = [token for token in category.replace("-", ".").replace("_", ".").split(".") if token]
    if not category_tokens:
        return category
    return " / ".join(_humanize_palette_token(token) for token in category_tokens)


def _humanize_palette_token(token: str) -> str:
    """把 palette 分类片段转换为展示文本。"""

    token_mapping = {
        "api": "API",
        "cv": "CV",
        "io": "IO",
        "opencv": "OpenCV",
        "plc": "PLC",
        "sdk": "SDK",
        "ui": "UI",
        "zmq": "ZeroMQ",
    }
    normalized_token = token.strip().casefold()
    if normalized_token in token_mapping:
        return token_mapping[normalized_token]
    return token.replace("-", " ").replace("_", " ").title()


def _filter_workflow_node_definitions(
    *,
    node_definitions: tuple[NodeDefinition, ...],
    category: str | None,
    node_pack_id: str | None,
    payload_type_id: str | None,
    keyword: str | None,
) -> list[NodeDefinition]:
    """按查询条件过滤 workflow 节点定义列表。

    参数：
    - node_definitions：待过滤的节点定义列表。
    - category：可选节点分类前缀。
    - node_pack_id：可选节点包 id。
    - payload_type_id：可选端口 payload 类型。
    - keyword：可选关键词。

    返回：
    - list[NodeDefinition]：过滤后的节点定义列表。
    """

    normalized_category = _normalize_optional_filter_text(category)
    normalized_node_pack_id = _normalize_optional_filter_text(node_pack_id)
    normalized_payload_type_id = _normalize_optional_filter_text(payload_type_id)
    normalized_keyword = _normalize_optional_filter_text(keyword)

    filtered_items: list[NodeDefinition] = []
    for node_definition in node_definitions:
        if normalized_category is not None and not node_definition.category.casefold().startswith(normalized_category):
            continue
        if normalized_node_pack_id is not None:
            if node_definition.node_pack_id is None or node_definition.node_pack_id.casefold() != normalized_node_pack_id:
                continue
        if normalized_payload_type_id is not None:
            payload_type_ids = {
                port.payload_type_id.casefold()
                for port in (*node_definition.input_ports, *node_definition.output_ports)
            }
            if normalized_payload_type_id not in payload_type_ids:
                continue
        if normalized_keyword is not None:
            searchable_values = (
                node_definition.node_type_id,
                node_definition.display_name,
                node_definition.description,
                node_definition.category,
            )
            if not any(normalized_keyword in value.casefold() for value in searchable_values if value):
                continue
        filtered_items.append(node_definition)
    return filtered_items


def _filter_workflow_payload_contracts(
    *,
    payload_contracts: tuple[WorkflowPayloadContract, ...],
    node_definitions: list[NodeDefinition],
    payload_type_id: str | None,
    filters_active: bool,
) -> list[WorkflowPayloadContract]:
    """按节点过滤结果裁剪 payload contract 列表。

    参数：
    - payload_contracts：待过滤的 payload contract 列表。
    - node_definitions：已经过滤后的节点定义列表。
    - payload_type_id：可选显式 payload 类型过滤条件。
    - filters_active：当前是否存在任何过滤条件。

    返回：
    - list[WorkflowPayloadContract]：过滤后的 payload contract 列表。
    """

    if not filters_active:
        return list(payload_contracts)

    referenced_payload_type_ids = {
        port.payload_type_id
        for node_definition in node_definitions
        for port in (*node_definition.input_ports, *node_definition.output_ports)
    }
    normalized_payload_type_id = _normalize_optional_filter_text(payload_type_id)
    if normalized_payload_type_id is not None:
        referenced_payload_type_ids.update(
            contract.payload_type_id
            for contract in payload_contracts
            if contract.payload_type_id.casefold() == normalized_payload_type_id
        )

    return [
        contract
        for contract in payload_contracts
        if contract.payload_type_id in referenced_payload_type_ids
    ]


def _filter_node_pack_manifests(
    *,
    node_pack_manifests: tuple[NodePackManifest, ...],
    node_definitions: list[NodeDefinition],
    node_pack_id: str | None,
    filters_active: bool,
) -> list[NodePackManifest]:
    """按节点过滤结果裁剪节点包 manifest 列表。

    参数：
    - node_pack_manifests：待过滤的节点包 manifest 列表。
    - node_definitions：已经过滤后的节点定义列表。
    - node_pack_id：可选显式节点包 id 过滤条件。
    - filters_active：当前是否存在任何过滤条件。

    返回：
    - list[NodePackManifest]：过滤后的节点包 manifest 列表。
    """

    normalized_node_pack_id = _normalize_optional_filter_text(node_pack_id)
    if normalized_node_pack_id is not None:
        return [
            manifest
            for manifest in node_pack_manifests
            if manifest.node_pack_id.casefold() == normalized_node_pack_id
        ]
    if not filters_active:
        return list(node_pack_manifests)

    referenced_node_pack_ids = {
        node_definition.node_pack_id
        for node_definition in node_definitions
        if node_definition.node_pack_id is not None
    }
    return [
        manifest
        for manifest in node_pack_manifests
        if manifest.node_pack_id in referenced_node_pack_ids
    ]


def _normalize_optional_filter_text(value: str | None) -> str | None:
    """规范化可选查询过滤值。

    参数：
    - value：原始过滤值。

    返回：
    - str | None：去除空白并转为小写后的过滤值；空值返回 None。
    """

    if value is None:
        return None
    normalized_value = value.strip()
    if not normalized_value:
        return None
    return normalized_value.casefold()


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