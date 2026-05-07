"""workflow 模板与流程应用文件服务。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    FlowTemplateReference,
    NodeDefinition,
    WorkflowGraphTemplate,
    WorkflowPayloadContract,
    validate_flow_application_bindings,
    validate_node_definition_catalog,
    validate_workflow_graph_template,
)
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


_WORKFLOW_ROOT_DIR = "workflows/projects"


@dataclass(frozen=True)
class WorkflowTemplateValidationSummary:
    """描述图模板校验摘要。

    字段：
    - template_id：模板 id。
    - template_version：模板版本。
    - node_count：节点数量。
    - edge_count：边数量。
    - template_input_ids：逻辑输入 id 列表。
    - template_output_ids：逻辑输出 id 列表。
    - referenced_node_type_ids：模板引用的节点类型 id 列表。
    """

    template_id: str
    template_version: str
    node_count: int
    edge_count: int
    template_input_ids: tuple[str, ...] = ()
    template_output_ids: tuple[str, ...] = ()
    referenced_node_type_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowApplicationValidationSummary:
    """描述流程应用校验摘要。

    字段：
    - application_id：流程应用 id。
    - template_id：引用的模板 id。
    - template_version：引用的模板版本。
    - binding_count：绑定数量。
    - input_binding_ids：输入绑定 id 列表。
    - output_binding_ids：输出绑定 id 列表。
    """

    application_id: str
    template_id: str
    template_version: str
    binding_count: int
    input_binding_ids: tuple[str, ...] = ()
    output_binding_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowTemplateDocument:
    """描述已保存的图模板文档。

    字段：
    - project_id：所属 Project id。
    - object_key：存储中的对象路径。
    - template：图模板内容。
    - validation_summary：模板校验摘要。
    """

    project_id: str
    object_key: str
    template: WorkflowGraphTemplate
    validation_summary: WorkflowTemplateValidationSummary


@dataclass(frozen=True)
class WorkflowApplicationDocument:
    """描述已保存的流程应用文档。

    字段：
    - project_id：所属 Project id。
    - object_key：存储中的对象路径。
    - application：流程应用内容。
    - validation_summary：流程应用校验摘要。
    """

    project_id: str
    object_key: str
    application: FlowApplication
    validation_summary: WorkflowApplicationValidationSummary


class LocalWorkflowJsonService:
    """基于 LocalDatasetStorage 管理 workflow 模板与流程应用 JSON。"""

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        node_catalog_registry: NodeCatalogRegistry | None = None,
        payload_contracts: tuple[WorkflowPayloadContract, ...] | None = None,
        node_definitions: tuple[NodeDefinition, ...] | None = None,
    ) -> None:
        """初始化 workflow 文件服务。"""

        self.dataset_storage = dataset_storage
        registry = node_catalog_registry or NodeCatalogRegistry()
        self.payload_contracts = payload_contracts or registry.get_workflow_payload_contracts()
        self.node_definitions = node_definitions or registry.get_workflow_node_definitions()
        validate_node_definition_catalog(
            node_definitions=self.node_definitions,
            payload_contracts=self.payload_contracts,
        )

    def validate_template(self, template: WorkflowGraphTemplate) -> WorkflowTemplateValidationSummary:
        """校验图模板。"""

        validate_workflow_graph_template(
            template=template,
            node_definitions=self.node_definitions,
        )
        return WorkflowTemplateValidationSummary(
            template_id=template.template_id,
            template_version=template.template_version,
            node_count=len(template.nodes),
            edge_count=len(template.edges),
            template_input_ids=tuple(item.input_id for item in template.template_inputs),
            template_output_ids=tuple(item.output_id for item in template.template_outputs),
            referenced_node_type_ids=tuple(node.node_type_id for node in template.nodes),
        )

    def save_template(
        self,
        *,
        project_id: str,
        template: WorkflowGraphTemplate,
    ) -> WorkflowTemplateDocument:
        """保存图模板 JSON。"""

        normalized_project_id = self._normalize_identifier(project_id, "project_id")
        validation_summary = self.validate_template(template)
        object_key = self._build_template_object_key(
            project_id=normalized_project_id,
            template_id=template.template_id,
            template_version=template.template_version,
        )
        self.dataset_storage.write_json(object_key, template.model_dump(mode="json"))
        return WorkflowTemplateDocument(
            project_id=normalized_project_id,
            object_key=object_key,
            template=template,
            validation_summary=validation_summary,
        )

    def get_template(
        self,
        *,
        project_id: str,
        template_id: str,
        template_version: str,
    ) -> WorkflowTemplateDocument:
        """读取已保存的图模板 JSON。"""

        normalized_project_id = self._normalize_identifier(project_id, "project_id")
        normalized_template_id = self._normalize_identifier(template_id, "template_id")
        normalized_template_version = self._normalize_identifier(template_version, "template_version")
        object_key = self._build_template_object_key(
            project_id=normalized_project_id,
            template_id=normalized_template_id,
            template_version=normalized_template_version,
        )
        if not self.dataset_storage.resolve(object_key).is_file():
            raise ResourceNotFoundError(
                "请求的 workflow template 不存在",
                details={
                    "project_id": normalized_project_id,
                    "template_id": normalized_template_id,
                    "template_version": normalized_template_version,
                },
            )
        template = WorkflowGraphTemplate.model_validate(self.dataset_storage.read_json(object_key))
        return WorkflowTemplateDocument(
            project_id=normalized_project_id,
            object_key=object_key,
            template=template,
            validation_summary=self.validate_template(template),
        )

    def validate_application(
        self,
        *,
        project_id: str,
        application: FlowApplication,
        template_override: WorkflowGraphTemplate | None = None,
    ) -> WorkflowApplicationValidationSummary:
        """校验流程应用与图模板绑定关系。"""

        normalized_project_id = self._normalize_identifier(project_id, "project_id")
        template = template_override
        if template is not None:
            self.validate_template(template)
        else:
            template = self.get_template(
                project_id=normalized_project_id,
                template_id=application.template_ref.template_id,
                template_version=application.template_ref.template_version,
            ).template
        validate_flow_application_bindings(template=template, application=application)
        return WorkflowApplicationValidationSummary(
            application_id=application.application_id,
            template_id=application.template_ref.template_id,
            template_version=application.template_ref.template_version,
            binding_count=len(application.bindings),
            input_binding_ids=tuple(
                binding.binding_id for binding in application.bindings if binding.direction == "input"
            ),
            output_binding_ids=tuple(
                binding.binding_id for binding in application.bindings if binding.direction == "output"
            ),
        )

    def save_application(
        self,
        *,
        project_id: str,
        application: FlowApplication,
    ) -> WorkflowApplicationDocument:
        """保存流程应用 JSON。"""

        normalized_project_id = self._normalize_identifier(project_id, "project_id")
        template_document = self.get_template(
            project_id=normalized_project_id,
            template_id=application.template_ref.template_id,
            template_version=application.template_ref.template_version,
        )
        normalized_application = application.model_copy(
            update={
                "template_ref": FlowTemplateReference(
                    template_id=application.template_ref.template_id,
                    template_version=application.template_ref.template_version,
                    source_kind="json-file",
                    source_uri=template_document.object_key,
                    metadata=dict(application.template_ref.metadata),
                )
            }
        )
        validation_summary = self.validate_application(
            project_id=normalized_project_id,
            application=normalized_application,
            template_override=template_document.template,
        )
        object_key = self._build_application_object_key(
            project_id=normalized_project_id,
            application_id=normalized_application.application_id,
        )
        self.dataset_storage.write_json(object_key, normalized_application.model_dump(mode="json"))
        return WorkflowApplicationDocument(
            project_id=normalized_project_id,
            object_key=object_key,
            application=normalized_application,
            validation_summary=validation_summary,
        )

    def get_application(
        self,
        *,
        project_id: str,
        application_id: str,
    ) -> WorkflowApplicationDocument:
        """读取已保存的流程应用 JSON。"""

        normalized_project_id = self._normalize_identifier(project_id, "project_id")
        normalized_application_id = self._normalize_identifier(application_id, "application_id")
        object_key = self._build_application_object_key(
            project_id=normalized_project_id,
            application_id=normalized_application_id,
        )
        if not self.dataset_storage.resolve(object_key).is_file():
            raise ResourceNotFoundError(
                "请求的 workflow application 不存在",
                details={
                    "project_id": normalized_project_id,
                    "application_id": normalized_application_id,
                },
            )
        application = FlowApplication.model_validate(self.dataset_storage.read_json(object_key))
        return WorkflowApplicationDocument(
            project_id=normalized_project_id,
            object_key=object_key,
            application=application,
            validation_summary=self.validate_application(
                project_id=normalized_project_id,
                application=application,
            ),
        )

    def _build_template_object_key(
        self,
        *,
        project_id: str,
        template_id: str,
        template_version: str,
    ) -> str:
        """构建图模板 JSON 的对象路径。"""

        return (
            f"{_WORKFLOW_ROOT_DIR}/{project_id}/templates/{template_id}"
            f"/versions/{template_version}/template.json"
        )

    def _build_application_object_key(
        self,
        *,
        project_id: str,
        application_id: str,
    ) -> str:
        """构建流程应用 JSON 的对象路径。"""

        return f"{_WORKFLOW_ROOT_DIR}/{project_id}/applications/{application_id}/application.json"

    def _normalize_identifier(self, value: str, field_name: str) -> str:
        """校验 project_id、template_id 等路径关键字段。"""

        normalized_value = value.strip()
        if not normalized_value:
            raise InvalidRequestError(f"{field_name} 不能为空")
        if "/" in normalized_value or "\\" in normalized_value or ".." in normalized_value:
            raise InvalidRequestError(
                f"{field_name} 不能包含路径分隔符或父目录引用",
                details={field_name: normalized_value},
            )
        return normalized_value