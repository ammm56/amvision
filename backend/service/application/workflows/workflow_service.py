"""workflow 模板与流程应用文件服务门面。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    NodeDefinition,
    WorkflowGraphTemplate,
    WorkflowPayloadContract,
    validate_node_definition_catalog,
)
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.workflows.documents.applications import WorkflowApplicationDocumentStore
from backend.service.application.workflows.documents.contracts import (
    WorkflowApplicationDocument,
    WorkflowApplicationSummary,
    WorkflowApplicationValidationSummary,
    WorkflowTemplateDocument,
    WorkflowTemplateSummary,
    WorkflowTemplateValidationSummary,
    WorkflowTemplateVersionSummary,
)
from backend.service.application.workflows.documents.templates import WorkflowTemplateDocumentStore
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class LocalWorkflowJsonService:
    """组合图模板和流程应用文档存储服务，保持原有 workflow JSON 门面。"""

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
        self.template_documents = WorkflowTemplateDocumentStore(
            dataset_storage=self.dataset_storage,
            node_definitions=self.node_definitions,
        )
        self.application_documents = WorkflowApplicationDocumentStore(
            dataset_storage=self.dataset_storage,
            template_documents=self.template_documents,
        )

    def validate_template(self, template: WorkflowGraphTemplate) -> WorkflowTemplateValidationSummary:
        """校验图模板。"""

        return self.template_documents.validate_template(template)

    def list_templates(self, *, project_id: str) -> tuple[WorkflowTemplateSummary, ...]:
        """列出指定 Project 下全部图模板摘要。"""

        return self.template_documents.list_templates(project_id=project_id)

    def list_template_versions(
        self,
        *,
        project_id: str,
        template_id: str,
    ) -> tuple[WorkflowTemplateVersionSummary, ...]:
        """列出指定图模板的全部版本摘要。"""

        return self.template_documents.list_template_versions(
            project_id=project_id,
            template_id=template_id,
        )

    def delete_template(
        self,
        *,
        project_id: str,
        template_id: str,
        template_version: str,
    ) -> None:
        """删除一份已保存的图模板版本。"""

        self.template_documents.delete_template(
            project_id=project_id,
            template_id=template_id,
            template_version=template_version,
        )

    def get_template_version_summary(
        self,
        *,
        project_id: str,
        template_id: str,
        template_version: str,
    ) -> WorkflowTemplateVersionSummary:
        """读取单个图模板版本摘要。"""

        return self.template_documents.get_template_version_summary(
            project_id=project_id,
            template_id=template_id,
            template_version=template_version,
        )

    def save_template(
        self,
        *,
        project_id: str,
        template: WorkflowGraphTemplate,
        actor_id: str | None = None,
    ) -> WorkflowTemplateDocument:
        """保存图模板 JSON。"""

        return self.template_documents.save_template(
            project_id=project_id,
            template=template,
            actor_id=actor_id,
        )

    def get_template(
        self,
        *,
        project_id: str,
        template_id: str,
        template_version: str,
    ) -> WorkflowTemplateDocument:
        """读取已保存的图模板 JSON。"""

        return self.template_documents.get_template(
            project_id=project_id,
            template_id=template_id,
            template_version=template_version,
        )

    def get_latest_template(
        self,
        *,
        project_id: str,
        template_id: str,
    ) -> WorkflowTemplateDocument:
        """读取指定模板当前可见的最新版本。"""

        return self.template_documents.get_latest_template(
            project_id=project_id,
            template_id=template_id,
        )

    def copy_template_version(
        self,
        *,
        project_id: str,
        source_template_id: str,
        source_template_version: str,
        target_template_id: str,
        target_template_version: str,
        actor_id: str | None = None,
        display_name: str | None = None,
        description: str | None = None,
    ) -> WorkflowTemplateDocument:
        """复制一份图模板版本到新的 template_id/template_version。"""

        return self.template_documents.copy_template_version(
            project_id=project_id,
            source_template_id=source_template_id,
            source_template_version=source_template_version,
            target_template_id=target_template_id,
            target_template_version=target_template_version,
            actor_id=actor_id,
            display_name=display_name,
            description=description,
        )

    def validate_application(
        self,
        *,
        project_id: str,
        application: FlowApplication,
        template_override: WorkflowGraphTemplate | None = None,
    ) -> WorkflowApplicationValidationSummary:
        """校验流程应用与图模板绑定关系。"""

        return self.application_documents.validate_application(
            project_id=project_id,
            application=application,
            template_override=template_override,
        )

    def list_applications(self, *, project_id: str) -> tuple[WorkflowApplicationSummary, ...]:
        """列出指定 Project 下全部流程应用摘要。"""

        return self.application_documents.list_applications(project_id=project_id)

    def delete_application(
        self,
        *,
        project_id: str,
        application_id: str,
    ) -> None:
        """删除一份已保存的流程应用。"""

        self.application_documents.delete_application(
            project_id=project_id,
            application_id=application_id,
        )

    def save_application(
        self,
        *,
        project_id: str,
        application: FlowApplication,
        actor_id: str | None = None,
    ) -> WorkflowApplicationDocument:
        """保存流程应用 JSON。"""

        return self.application_documents.save_application(
            project_id=project_id,
            application=application,
            actor_id=actor_id,
        )

    def update_application_metadata(
        self,
        *,
        project_id: str,
        application_id: str,
        actor_id: str | None = None,
        display_name: str | None = None,
        description: str | None = None,
    ) -> WorkflowApplicationDocument:
        """只更新流程应用基础显示信息。"""

        return self.application_documents.update_application_metadata(
            project_id=project_id,
            application_id=application_id,
            actor_id=actor_id,
            display_name=display_name,
            description=description,
        )

    def get_application_summary(
        self,
        *,
        project_id: str,
        application_id: str,
    ) -> WorkflowApplicationSummary:
        """读取单个流程应用摘要。"""

        return self.application_documents.get_application_summary(
            project_id=project_id,
            application_id=application_id,
        )

    def get_application(
        self,
        *,
        project_id: str,
        application_id: str,
    ) -> WorkflowApplicationDocument:
        """读取已保存的流程应用 JSON。"""

        return self.application_documents.get_application(
            project_id=project_id,
            application_id=application_id,
        )

    def copy_application(
        self,
        *,
        project_id: str,
        source_application_id: str,
        target_application_id: str,
        actor_id: str | None = None,
        display_name: str | None = None,
        description: str | None = None,
    ) -> WorkflowApplicationDocument:
        """复制一份流程应用到新的 application_id。"""

        return self.application_documents.copy_application(
            project_id=project_id,
            source_application_id=source_application_id,
            target_application_id=target_application_id,
            actor_id=actor_id,
            display_name=display_name,
            description=description,
        )
