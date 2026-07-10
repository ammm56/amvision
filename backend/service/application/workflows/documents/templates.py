"""workflow 图模板文档存储服务。"""

from __future__ import annotations

from collections import defaultdict

from backend.contracts.workflows.workflow_graph import (
    NodeDefinition,
    WorkflowGraphTemplate,
    validate_workflow_graph_template,
)
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.application.workflows.documents.contracts import (
    WorkflowTemplateDocument,
    WorkflowTemplateSummary,
    WorkflowTemplateValidationSummary,
    WorkflowTemplateVersionSummary,
)
from backend.service.application.workflows.documents.storage import (
    build_natural_sort_key,
    build_resource_summary_for_save,
    build_template_object_key,
    build_template_version_directory_key,
    build_template_versions_dir_key,
    build_templates_dir_key,
    normalize_identifier,
    normalize_optional_non_empty_text,
    read_resource_summary,
    to_object_key,
    write_resource_summary,
)
from backend.service.application.workflows.documents.validation import summarize_workflow_template
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


class WorkflowTemplateDocumentStore:
    """管理 workflow 图模板 JSON、版本摘要和模板 sidecar。"""

    def __init__(
        self,
        *,
        dataset_storage: LocalDatasetStorage,
        node_definitions: tuple[NodeDefinition, ...],
    ) -> None:
        """初始化图模板文档存储服务。"""

        self.dataset_storage = dataset_storage
        self.node_definitions = node_definitions

    def validate_template(self, template: WorkflowGraphTemplate) -> WorkflowTemplateValidationSummary:
        """校验图模板。"""

        try:
            validate_workflow_graph_template(
                template=template,
                node_definitions=self.node_definitions,
            )
        except ValueError as exc:
            raise InvalidRequestError(
                "Workflow 图模板校验失败",
                details={"reason": str(exc)},
            ) from exc
        return summarize_workflow_template(template)

    def list_templates(self, *, project_id: str) -> tuple[WorkflowTemplateSummary, ...]:
        """列出指定 Project 下全部图模板摘要。"""

        normalized_project_id = normalize_identifier(project_id, "project_id")
        grouped_versions: dict[str, list[WorkflowTemplateVersionSummary]] = defaultdict(list)
        for version_summary in self._iter_template_version_summaries(project_id=normalized_project_id):
            grouped_versions[version_summary.template_id].append(version_summary)

        template_summaries: list[WorkflowTemplateSummary] = []
        for template_id in sorted(grouped_versions):
            versions = sorted(
                grouped_versions[template_id],
                key=lambda item: build_natural_sort_key(item.template_version),
            )
            created_version = min(
                versions,
                key=lambda item: (
                    item.created_at,
                    build_natural_sort_key(item.template_version),
                ),
            )
            updated_version = max(
                versions,
                key=lambda item: (
                    item.updated_at,
                    build_natural_sort_key(item.template_version),
                ),
            )
            latest_version = versions[-1]
            template_summaries.append(
                WorkflowTemplateSummary(
                    project_id=normalized_project_id,
                    template_id=template_id,
                    display_name=latest_version.display_name,
                    description=latest_version.description,
                    created_at=min(item.created_at for item in versions),
                    updated_at=max(item.updated_at for item in versions),
                    created_by=created_version.created_by,
                    updated_by=updated_version.updated_by,
                    latest_template_version=latest_version.template_version,
                    version_count=len(versions),
                    versions=tuple(item.template_version for item in versions),
                )
            )
        template_summaries.sort(key=lambda item: item.template_id.casefold())
        template_summaries.sort(key=lambda item: item.updated_at, reverse=True)
        return tuple(template_summaries)

    def list_template_versions(
        self,
        *,
        project_id: str,
        template_id: str,
    ) -> tuple[WorkflowTemplateVersionSummary, ...]:
        """列出指定图模板的全部版本摘要。"""

        normalized_project_id = normalize_identifier(project_id, "project_id")
        normalized_template_id = normalize_identifier(template_id, "template_id")
        versions_dir = self.dataset_storage.resolve(
            build_template_versions_dir_key(
                project_id=normalized_project_id,
                template_id=normalized_template_id,
            )
        )
        if not versions_dir.is_dir():
            return ()

        version_summaries: list[WorkflowTemplateVersionSummary] = []
        for template_file in versions_dir.glob("*/template.json"):
            if not template_file.is_file():
                continue
            version_summaries.append(
                self._build_template_version_summary(
                    project_id=normalized_project_id,
                    object_key=to_object_key(
                        dataset_storage=self.dataset_storage,
                        path=template_file,
                    ),
                )
            )
        return tuple(
            sorted(
                version_summaries,
                key=lambda item: build_natural_sort_key(item.template_version),
            )
        )

    def delete_template(
        self,
        *,
        project_id: str,
        template_id: str,
        template_version: str,
    ) -> None:
        """删除一份已保存的图模板版本。"""

        normalized_project_id = normalize_identifier(project_id, "project_id")
        normalized_template_id = normalize_identifier(template_id, "template_id")
        normalized_template_version = normalize_identifier(template_version, "template_version")
        object_key = build_template_object_key(
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
        self.dataset_storage.delete_tree(
            build_template_version_directory_key(
                project_id=normalized_project_id,
                template_id=normalized_template_id,
                template_version=normalized_template_version,
            )
        )

    def get_template_version_summary(
        self,
        *,
        project_id: str,
        template_id: str,
        template_version: str,
    ) -> WorkflowTemplateVersionSummary:
        """读取单个图模板版本摘要。"""

        normalized_project_id = normalize_identifier(project_id, "project_id")
        normalized_template_id = normalize_identifier(template_id, "template_id")
        normalized_template_version = normalize_identifier(
            template_version,
            "template_version",
        )
        object_key = build_template_object_key(
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
        return self._build_template_version_summary(
            project_id=normalized_project_id,
            object_key=object_key,
        )

    def save_template(
        self,
        *,
        project_id: str,
        template: WorkflowGraphTemplate,
        actor_id: str | None = None,
    ) -> WorkflowTemplateDocument:
        """保存图模板 JSON。"""

        normalized_project_id = normalize_identifier(project_id, "project_id")
        validation_summary = self.validate_template(template)
        object_key = build_template_object_key(
            project_id=normalized_project_id,
            template_id=template.template_id,
            template_version=template.template_version,
        )
        resource_summary = build_resource_summary_for_save(
            dataset_storage=self.dataset_storage,
            object_key=object_key,
            actor_id=actor_id,
        )
        self.dataset_storage.write_json(object_key, template.model_dump(mode="json"))
        write_resource_summary(
            dataset_storage=self.dataset_storage,
            object_key=object_key,
            summary=resource_summary,
        )
        return WorkflowTemplateDocument(
            project_id=normalized_project_id,
            object_key=object_key,
            template=template,
            validation_summary=validation_summary,
            resource_summary=resource_summary,
        )

    def get_template(
        self,
        *,
        project_id: str,
        template_id: str,
        template_version: str,
    ) -> WorkflowTemplateDocument:
        """读取已保存的图模板 JSON。"""

        normalized_project_id = normalize_identifier(project_id, "project_id")
        normalized_template_id = normalize_identifier(template_id, "template_id")
        normalized_template_version = normalize_identifier(template_version, "template_version")
        object_key = build_template_object_key(
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
            resource_summary=read_resource_summary(
                dataset_storage=self.dataset_storage,
                object_key=object_key,
            ),
        )

    def get_latest_template(
        self,
        *,
        project_id: str,
        template_id: str,
    ) -> WorkflowTemplateDocument:
        """读取指定模板当前可见的最新版本。"""

        normalized_project_id = normalize_identifier(project_id, "project_id")
        normalized_template_id = normalize_identifier(template_id, "template_id")
        version_summaries = self.list_template_versions(
            project_id=normalized_project_id,
            template_id=normalized_template_id,
        )
        if not version_summaries:
            raise ResourceNotFoundError(
                "请求的 workflow template 不存在",
                details={
                    "project_id": normalized_project_id,
                    "template_id": normalized_template_id,
                },
            )
        latest_version = version_summaries[-1].template_version
        return self.get_template(
            project_id=normalized_project_id,
            template_id=normalized_template_id,
            template_version=latest_version,
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

        normalized_project_id = normalize_identifier(project_id, "project_id")
        normalized_source_template_id = normalize_identifier(source_template_id, "source_template_id")
        normalized_source_template_version = normalize_identifier(
            source_template_version,
            "source_template_version",
        )
        normalized_target_template_id = normalize_identifier(target_template_id, "target_template_id")
        normalized_target_template_version = normalize_identifier(
            target_template_version,
            "target_template_version",
        )
        if (
            normalized_source_template_id == normalized_target_template_id
            and normalized_source_template_version == normalized_target_template_version
        ):
            raise InvalidRequestError(
                "复制 workflow template 时目标 template_id 和 template_version 不能与源版本相同",
                details={
                    "template_id": normalized_target_template_id,
                    "template_version": normalized_target_template_version,
                },
            )

        source_document = self.get_template(
            project_id=normalized_project_id,
            template_id=normalized_source_template_id,
            template_version=normalized_source_template_version,
        )
        target_object_key = build_template_object_key(
            project_id=normalized_project_id,
            template_id=normalized_target_template_id,
            template_version=normalized_target_template_version,
        )
        if self.dataset_storage.resolve(target_object_key).is_file():
            raise InvalidRequestError(
                "目标 workflow template 已存在",
                details={
                    "project_id": normalized_project_id,
                    "template_id": normalized_target_template_id,
                    "template_version": normalized_target_template_version,
                },
            )

        copied_template = source_document.template.model_copy(
            update={
                "template_id": normalized_target_template_id,
                "template_version": normalized_target_template_version,
                "display_name": (
                    normalize_optional_non_empty_text(display_name, "display_name")
                    or source_document.template.display_name
                ),
                "description": (
                    source_document.template.description if description is None else description
                ),
            }
        )
        return self.save_template(
            project_id=normalized_project_id,
            template=copied_template,
            actor_id=actor_id,
        )

    def _iter_template_version_summaries(
        self,
        *,
        project_id: str,
    ) -> tuple[WorkflowTemplateVersionSummary, ...]:
        """遍历指定 Project 下全部图模板版本摘要。"""

        templates_dir = self.dataset_storage.resolve(build_templates_dir_key(project_id=project_id))
        if not templates_dir.is_dir():
            return ()

        version_summaries: list[WorkflowTemplateVersionSummary] = []
        for template_file in templates_dir.glob("*/versions/*/template.json"):
            if not template_file.is_file():
                continue
            version_summaries.append(
                self._build_template_version_summary(
                    project_id=project_id,
                    object_key=to_object_key(
                        dataset_storage=self.dataset_storage,
                        path=template_file,
                    ),
                )
            )
        return tuple(version_summaries)

    def _build_template_version_summary(
        self,
        *,
        project_id: str,
        object_key: str,
    ) -> WorkflowTemplateVersionSummary:
        """基于对象路径构建图模板版本摘要。"""

        template = WorkflowGraphTemplate.model_validate(self.dataset_storage.read_json(object_key))
        validation_summary = summarize_workflow_template(template)
        resource_summary = read_resource_summary(
            dataset_storage=self.dataset_storage,
            object_key=object_key,
        )
        return WorkflowTemplateVersionSummary(
            project_id=project_id,
            object_key=object_key,
            template_id=template.template_id,
            template_version=template.template_version,
            display_name=template.display_name,
            description=template.description,
            created_at=resource_summary.created_at,
            updated_at=resource_summary.updated_at,
            created_by=resource_summary.created_by,
            updated_by=resource_summary.updated_by,
            node_count=validation_summary.node_count,
            edge_count=validation_summary.edge_count,
            template_input_ids=validation_summary.template_input_ids,
            template_output_ids=validation_summary.template_output_ids,
            referenced_node_type_ids=validation_summary.referenced_node_type_ids,
        )

