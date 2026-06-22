"""workflow 流程应用文档存储服务。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    FlowTemplateReference,
    WorkflowGraphTemplate,
    validate_flow_application_bindings,
)
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.workflows.documents.contracts import (
    WorkflowApplicationDocument,
    WorkflowApplicationSummary,
    WorkflowApplicationValidationSummary,
)
from backend.service.application.workflows.documents.storage import (
    build_application_directory_key,
    build_application_object_key,
    build_applications_dir_key,
    normalize_identifier,
    normalize_optional_non_empty_text,
    read_resource_summary,
    to_object_key,
    write_resource_summary,
    build_resource_summary_for_save,
)
from backend.service.application.workflows.documents.templates import WorkflowTemplateDocumentStore
from backend.service.application.workflows.documents.validation import summarize_workflow_application
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class WorkflowApplicationDocumentStore:
    """管理 workflow 流程应用 JSON、摘要和模板绑定校验。"""

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        template_documents: WorkflowTemplateDocumentStore,
    ) -> None:
        """初始化流程应用文档存储服务。"""

        self.dataset_storage = dataset_storage
        self.template_documents = template_documents

    def validate_application(
        self,
        *,
        project_id: str,
        application: FlowApplication,
        template_override: WorkflowGraphTemplate | None = None,
    ) -> WorkflowApplicationValidationSummary:
        """校验流程应用与图模板绑定关系。"""

        normalized_project_id = normalize_identifier(project_id, "project_id")
        template = template_override
        if template is not None:
            self.template_documents.validate_template(template)
        else:
            template = self.template_documents.get_template(
                project_id=normalized_project_id,
                template_id=application.template_ref.template_id,
                template_version=application.template_ref.template_version,
            ).template
        validate_flow_application_bindings(template=template, application=application)
        return summarize_workflow_application(application)

    def list_applications(self, *, project_id: str) -> tuple[WorkflowApplicationSummary, ...]:
        """列出指定 Project 下全部流程应用摘要。"""

        normalized_project_id = normalize_identifier(project_id, "project_id")
        applications_dir = self.dataset_storage.resolve(
            build_applications_dir_key(project_id=normalized_project_id)
        )
        if not applications_dir.is_dir():
            return ()

        application_summaries: list[WorkflowApplicationSummary] = []
        for application_file in applications_dir.glob("*/application.json"):
            if not application_file.is_file():
                continue
            application_summaries.append(
                self._build_application_summary(
                    project_id=normalized_project_id,
                    object_key=to_object_key(
                        dataset_storage=self.dataset_storage,
                        path=application_file,
                    ),
                )
            )
        application_summaries.sort(key=lambda item: item.application_id.casefold())
        application_summaries.sort(key=lambda item: item.updated_at, reverse=True)
        return tuple(application_summaries)

    def delete_application(
        self,
        *,
        project_id: str,
        application_id: str,
    ) -> None:
        """删除一份已保存的流程应用。"""

        normalized_project_id = normalize_identifier(project_id, "project_id")
        normalized_application_id = normalize_identifier(application_id, "application_id")
        object_key = build_application_object_key(
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
        self.dataset_storage.delete_tree(
            build_application_directory_key(
                project_id=normalized_project_id,
                application_id=normalized_application_id,
            )
        )

    def save_application(
        self,
        *,
        project_id: str,
        application: FlowApplication,
        actor_id: str | None = None,
    ) -> WorkflowApplicationDocument:
        """保存流程应用 JSON。"""

        normalized_project_id = normalize_identifier(project_id, "project_id")
        template_document = self.template_documents.get_template(
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
        object_key = build_application_object_key(
            project_id=normalized_project_id,
            application_id=normalized_application.application_id,
        )
        resource_summary = build_resource_summary_for_save(
            dataset_storage=self.dataset_storage,
            object_key=object_key,
            actor_id=actor_id,
        )
        self.dataset_storage.write_json(object_key, normalized_application.model_dump(mode="json"))
        write_resource_summary(
            dataset_storage=self.dataset_storage,
            object_key=object_key,
            summary=resource_summary,
        )
        return WorkflowApplicationDocument(
            project_id=normalized_project_id,
            object_key=object_key,
            application=normalized_application,
            validation_summary=validation_summary,
            resource_summary=resource_summary,
        )

    def get_application_summary(
        self,
        *,
        project_id: str,
        application_id: str,
    ) -> WorkflowApplicationSummary:
        """读取单个流程应用摘要。"""

        normalized_project_id = normalize_identifier(project_id, "project_id")
        normalized_application_id = normalize_identifier(
            application_id,
            "application_id",
        )
        object_key = build_application_object_key(
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
        return self._build_application_summary(
            project_id=normalized_project_id,
            object_key=object_key,
        )

    def get_application(
        self,
        *,
        project_id: str,
        application_id: str,
    ) -> WorkflowApplicationDocument:
        """读取已保存的流程应用 JSON。"""

        normalized_project_id = normalize_identifier(project_id, "project_id")
        normalized_application_id = normalize_identifier(application_id, "application_id")
        object_key = build_application_object_key(
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
            resource_summary=read_resource_summary(
                dataset_storage=self.dataset_storage,
                object_key=object_key,
            ),
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

        normalized_project_id = normalize_identifier(project_id, "project_id")
        normalized_source_application_id = normalize_identifier(source_application_id, "source_application_id")
        normalized_target_application_id = normalize_identifier(target_application_id, "target_application_id")
        if normalized_source_application_id == normalized_target_application_id:
            raise InvalidRequestError(
                "复制 workflow application 时目标 application_id 不能与源 application_id 相同",
                details={"application_id": normalized_target_application_id},
            )

        source_document = self.get_application(
            project_id=normalized_project_id,
            application_id=normalized_source_application_id,
        )
        target_object_key = build_application_object_key(
            project_id=normalized_project_id,
            application_id=normalized_target_application_id,
        )
        if self.dataset_storage.resolve(target_object_key).is_file():
            raise InvalidRequestError(
                "目标 workflow application 已存在",
                details={
                    "project_id": normalized_project_id,
                    "application_id": normalized_target_application_id,
                },
            )

        copied_application = source_document.application.model_copy(
            update={
                "application_id": normalized_target_application_id,
                "display_name": (
                    normalize_optional_non_empty_text(display_name, "display_name")
                    or source_document.application.display_name
                ),
                "description": (
                    source_document.application.description if description is None else description
                ),
            }
        )
        return self.save_application(
            project_id=normalized_project_id,
            application=copied_application,
            actor_id=actor_id,
        )

    def _build_application_summary(
        self,
        *,
        project_id: str,
        object_key: str,
    ) -> WorkflowApplicationSummary:
        """基于对象路径构建流程应用摘要。"""

        application = FlowApplication.model_validate(self.dataset_storage.read_json(object_key))
        validation_summary = summarize_workflow_application(application)
        resource_summary = read_resource_summary(
            dataset_storage=self.dataset_storage,
            object_key=object_key,
        )
        return WorkflowApplicationSummary(
            project_id=project_id,
            object_key=object_key,
            application_id=application.application_id,
            display_name=application.display_name,
            description=application.description,
            created_at=resource_summary.created_at,
            updated_at=resource_summary.updated_at,
            created_by=resource_summary.created_by,
            updated_by=resource_summary.updated_by,
            template_id=application.template_ref.template_id,
            template_version=application.template_ref.template_version,
            binding_count=validation_summary.binding_count,
            input_binding_ids=validation_summary.input_binding_ids,
            output_binding_ids=validation_summary.output_binding_ids,
        )
