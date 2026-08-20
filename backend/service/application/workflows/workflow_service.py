"""workflow 模板与流程应用文件服务门面。"""

from __future__ import annotations

import logging

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    NodeDefinition,
    WorkflowGraphTemplate,
    WorkflowPayloadContract,
    validate_node_definition_catalog,
)
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.workflows.application_bundle_journal import (
    WorkflowApplicationBundleJournalService,
)
from backend.service.application.workflows.documents.applications import (
    WorkflowApplicationDocumentStore,
)
from backend.service.application.workflows.documents.contracts import (
    WorkflowApplicationBundleDocument,
    WorkflowApplicationDocument,
    WorkflowApplicationSummary,
    WorkflowApplicationValidationSummary,
    WorkflowTemplateDocument,
    WorkflowTemplateSummary,
    WorkflowTemplateValidationSummary,
    WorkflowTemplateVersionSummary,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.documents.storage import (
    normalize_application_identifier,
    normalize_identifier,
)
from backend.service.application.workflows.documents.templates import (
    WorkflowTemplateDocumentStore,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


logger = logging.getLogger(__name__)


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
        self.payload_contracts = (
            payload_contracts or registry.get_workflow_payload_contracts()
        )
        self.node_definitions = (
            node_definitions or registry.get_workflow_node_definitions()
        )
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
        self.application_bundle_journals = WorkflowApplicationBundleJournalService(
            dataset_storage=self.dataset_storage,
        )

    def validate_template(
        self, template: WorkflowGraphTemplate
    ) -> WorkflowTemplateValidationSummary:
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

    def list_applications(
        self, *, project_id: str
    ) -> tuple[WorkflowApplicationSummary, ...]:
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

    def save_application_bundle(
        self,
        *,
        project_id: str,
        application: FlowApplication,
        template: WorkflowGraphTemplate,
        operation_id: str,
        actor_id: str | None = None,
    ) -> WorkflowApplicationBundleDocument:
        """交叉校验并用可跨进程恢复的 journal 保存 Application 与 Template。"""

        normalized_project_id = normalize_identifier(project_id, "project_id")
        normalize_application_identifier(application.application_id, "application_id")
        normalize_identifier(template.template_id, "template_id")
        normalize_identifier(template.template_version, "template_version")
        if (
            application.template_ref.template_id != template.template_id
            or application.template_ref.template_version != template.template_version
        ):
            raise InvalidRequestError(
                "Workflow Application 与 Template 引用不一致",
                details={
                    "application_template_id": application.template_ref.template_id,
                    "application_template_version": application.template_ref.template_version,
                    "template_id": template.template_id,
                    "template_version": template.template_version,
                },
            )

        # 所有交叉校验必须先于任何文件写入，失败时不触碰当前草稿。
        self.template_documents.validate_template(template)
        self.application_documents.validate_application(
            project_id=normalized_project_id,
            application=application,
            template_override=template,
        )
        journal = self.application_bundle_journals.prepare(
            operation_id=operation_id,
            project_id=normalized_project_id,
            application_id=application.application_id,
            template_id=template.template_id,
            template_version=template.template_version,
        )
        try:
            template_document = self.template_documents.save_template(
                project_id=normalized_project_id,
                template=template,
                actor_id=actor_id,
            )
            application_document = self.application_documents.save_application(
                project_id=normalized_project_id,
                application=application,
                actor_id=actor_id,
                # 非权威 Prompt Mask 清理推迟到两份权威 JSON 都提交后。
                prune_unreferenced_prompt_masks=False,
            )
            self.application_bundle_journals.commit(journal)
        except Exception:
            # rollback 失败会抛出 WorkflowRecoveryRequiredError 并保留 journal；
            # lifecycle context 会保留 Application/Template claim 供启动恢复。
            self.application_bundle_journals.rollback(journal)
            raise

        try:
            self.application_documents._prune_unreferenced_prompt_masks(  # noqa: SLF001
                project_id=normalized_project_id,
                application_id=application.application_id,
                template=template,
            )
        except Exception as error:  # noqa: BLE001 - 权威 bundle 已经 committed
            # Prompt Mask 属于可重建的编辑资产清理，不得把已经一致提交的
            # Application + Template 重新报告为保存失败。
            logger.warning(
                "Workflow App bundle 已保存，但 Prompt Mask 清理失败：%s",
                error,
            )
        return WorkflowApplicationBundleDocument(
            application_document=application_document,
            template_document=template_document,
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
