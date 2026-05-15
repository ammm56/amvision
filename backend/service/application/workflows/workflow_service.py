"""workflow 模板与流程应用文件服务。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

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
class WorkflowStoredResourceSummary:
    """描述 workflow 文件资源的 sidecar 摘要。

    字段：
    - created_at：资源创建时间。
    - updated_at：资源最近更新时间。
    - created_by：资源创建主体 id。
    - updated_by：资源最近修改主体 id。
    """

    created_at: str
    updated_at: str
    created_by: str | None = None
    updated_by: str | None = None


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
    - resource_summary：资源 sidecar 摘要。
    """

    project_id: str
    object_key: str
    template: WorkflowGraphTemplate
    validation_summary: WorkflowTemplateValidationSummary
    resource_summary: WorkflowStoredResourceSummary


@dataclass(frozen=True)
class WorkflowApplicationDocument:
    """描述已保存的流程应用文档。

    字段：
    - project_id：所属 Project id。
    - object_key：存储中的对象路径。
    - application：流程应用内容。
    - validation_summary：流程应用校验摘要。
    - resource_summary：资源 sidecar 摘要。
    """

    project_id: str
    object_key: str
    application: FlowApplication
    validation_summary: WorkflowApplicationValidationSummary
    resource_summary: WorkflowStoredResourceSummary


@dataclass(frozen=True)
class WorkflowTemplateVersionSummary:
    """描述单个图模板版本的摘要。

    字段：
    - project_id：所属 Project id。
    - object_key：模板 JSON 对象路径。
    - template_id：模板 id。
    - template_version：模板版本。
    - display_name：模板显示名称。
    - description：模板说明。
    - created_at：模板版本文件创建时间。
    - updated_at：模板版本文件更新时间。
    - created_by：模板版本创建主体 id。
    - updated_by：模板版本最近修改主体 id。
    - node_count：节点数量。
    - edge_count：边数量。
    - template_input_ids：逻辑输入 id 列表。
    - template_output_ids：逻辑输出 id 列表。
    - referenced_node_type_ids：引用的节点类型 id 列表。
    """

    project_id: str
    object_key: str
    template_id: str
    template_version: str
    display_name: str
    description: str
    created_at: str
    updated_at: str
    created_by: str | None
    updated_by: str | None
    node_count: int
    edge_count: int
    template_input_ids: tuple[str, ...] = ()
    template_output_ids: tuple[str, ...] = ()
    referenced_node_type_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowTemplateSummary:
    """描述一个图模板在当前 Project 下的聚合摘要。

    字段：
    - project_id：所属 Project id。
    - template_id：模板 id。
    - display_name：模板显示名称。
    - description：模板说明。
    - created_at：当前模板最早版本的创建时间。
    - updated_at：当前模板最近一次变更时间。
    - created_by：当前模板最早版本创建主体 id。
    - updated_by：当前模板最近一次变更主体 id。
    - latest_template_version：当前可见的最新模板版本。
    - version_count：当前模板版本数量。
    - versions：当前模板全部版本 id 列表。
    """

    project_id: str
    template_id: str
    display_name: str
    description: str
    created_at: str
    updated_at: str
    created_by: str | None
    updated_by: str | None
    latest_template_version: str
    version_count: int
    versions: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowApplicationSummary:
    """描述单个流程应用的摘要。

    字段：
    - project_id：所属 Project id。
    - object_key：流程应用 JSON 对象路径。
    - application_id：流程应用 id。
    - display_name：流程应用显示名称。
    - description：流程应用说明。
    - created_at：流程应用文件创建时间。
    - updated_at：流程应用文件更新时间。
    - created_by：流程应用创建主体 id。
    - updated_by：流程应用最近修改主体 id。
    - template_id：引用的模板 id。
    - template_version：引用的模板版本。
    - binding_count：绑定数量。
    - input_binding_ids：输入绑定 id 列表。
    - output_binding_ids：输出绑定 id 列表。
    """

    project_id: str
    object_key: str
    application_id: str
    display_name: str
    description: str
    created_at: str
    updated_at: str
    created_by: str | None
    updated_by: str | None
    template_id: str
    template_version: str
    binding_count: int
    input_binding_ids: tuple[str, ...] = ()
    output_binding_ids: tuple[str, ...] = ()


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
        return self._summarize_template(template)

    def list_templates(self, *, project_id: str) -> tuple[WorkflowTemplateSummary, ...]:
        """列出指定 Project 下全部图模板摘要。

        参数：
        - project_id：所属 Project id。

        返回：
        - 当前 Project 下按 template_id 聚合后的图模板摘要列表。
        """

        normalized_project_id = self._normalize_identifier(project_id, "project_id")
        grouped_versions: dict[str, list[WorkflowTemplateVersionSummary]] = defaultdict(list)
        for version_summary in self._iter_template_version_summaries(project_id=normalized_project_id):
            grouped_versions[version_summary.template_id].append(version_summary)

        template_summaries: list[WorkflowTemplateSummary] = []
        for template_id in sorted(grouped_versions):
            versions = sorted(
                grouped_versions[template_id],
                key=lambda item: self._build_natural_sort_key(item.template_version),
            )
            created_version = min(
                versions,
                key=lambda item: (
                    item.created_at,
                    self._build_natural_sort_key(item.template_version),
                ),
            )
            updated_version = max(
                versions,
                key=lambda item: (
                    item.updated_at,
                    self._build_natural_sort_key(item.template_version),
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
        """列出指定图模板的全部版本摘要。

        参数：
        - project_id：所属 Project id。
        - template_id：模板 id。

        返回：
        - 当前模板全部版本摘要列表。
        """

        normalized_project_id = self._normalize_identifier(project_id, "project_id")
        normalized_template_id = self._normalize_identifier(template_id, "template_id")
        versions_dir = self.dataset_storage.resolve(
            self._build_template_versions_dir_key(
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
                    object_key=self._to_object_key(template_file),
                )
            )
        return tuple(
            sorted(
                version_summaries,
                key=lambda item: self._build_natural_sort_key(item.template_version),
            )
        )

    def delete_template(
        self,
        *,
        project_id: str,
        template_id: str,
        template_version: str,
    ) -> None:
        """删除一份已保存的图模板版本。

        参数：
        - project_id：所属 Project id。
        - template_id：模板 id。
        - template_version：模板版本。

        异常：
        - 当目标模板版本不存在时抛出资源不存在错误。
        """

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
        self.dataset_storage.delete_tree(
            self._build_template_version_directory_key(
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

        normalized_project_id = self._normalize_identifier(project_id, "project_id")
        normalized_template_id = self._normalize_identifier(template_id, "template_id")
        normalized_template_version = self._normalize_identifier(
            template_version,
            "template_version",
        )
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

        normalized_project_id = self._normalize_identifier(project_id, "project_id")
        validation_summary = self.validate_template(template)
        object_key = self._build_template_object_key(
            project_id=normalized_project_id,
            template_id=template.template_id,
            template_version=template.template_version,
        )
        resource_summary = self._build_resource_summary_for_save(
            object_key=object_key,
            actor_id=actor_id,
        )
        self.dataset_storage.write_json(object_key, template.model_dump(mode="json"))
        self._write_resource_summary(
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
            resource_summary=self._read_resource_summary(object_key),
        )

    def get_latest_template(
        self,
        *,
        project_id: str,
        template_id: str,
    ) -> WorkflowTemplateDocument:
        """读取指定模板当前可见的最新版本。"""

        normalized_project_id = self._normalize_identifier(project_id, "project_id")
        normalized_template_id = self._normalize_identifier(template_id, "template_id")
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

        normalized_project_id = self._normalize_identifier(project_id, "project_id")
        normalized_source_template_id = self._normalize_identifier(source_template_id, "source_template_id")
        normalized_source_template_version = self._normalize_identifier(
            source_template_version,
            "source_template_version",
        )
        normalized_target_template_id = self._normalize_identifier(target_template_id, "target_template_id")
        normalized_target_template_version = self._normalize_identifier(
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
        target_object_key = self._build_template_object_key(
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
                    self._normalize_optional_non_empty_text(display_name, "display_name")
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
        return self._summarize_application(application)

    def list_applications(self, *, project_id: str) -> tuple[WorkflowApplicationSummary, ...]:
        """列出指定 Project 下全部流程应用摘要。

        参数：
        - project_id：所属 Project id。

        返回：
        - 当前 Project 下全部流程应用摘要列表。
        """

        normalized_project_id = self._normalize_identifier(project_id, "project_id")
        applications_dir = self.dataset_storage.resolve(
            self._build_applications_dir_key(project_id=normalized_project_id)
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
                    object_key=self._to_object_key(application_file),
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
        """删除一份已保存的流程应用。

        参数：
        - project_id：所属 Project id。
        - application_id：流程应用 id。

        异常：
        - 当目标流程应用不存在时抛出资源不存在错误。
        """

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
        self.dataset_storage.delete_tree(
            self._build_application_directory_key(
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
        resource_summary = self._build_resource_summary_for_save(
            object_key=object_key,
            actor_id=actor_id,
        )
        self.dataset_storage.write_json(object_key, normalized_application.model_dump(mode="json"))
        self._write_resource_summary(
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

        normalized_project_id = self._normalize_identifier(project_id, "project_id")
        normalized_application_id = self._normalize_identifier(
            application_id,
            "application_id",
        )
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
            resource_summary=self._read_resource_summary(object_key),
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

        normalized_project_id = self._normalize_identifier(project_id, "project_id")
        normalized_source_application_id = self._normalize_identifier(source_application_id, "source_application_id")
        normalized_target_application_id = self._normalize_identifier(target_application_id, "target_application_id")
        if normalized_source_application_id == normalized_target_application_id:
            raise InvalidRequestError(
                "复制 workflow application 时目标 application_id 不能与源 application_id 相同",
                details={"application_id": normalized_target_application_id},
            )

        source_document = self.get_application(
            project_id=normalized_project_id,
            application_id=normalized_source_application_id,
        )
        target_object_key = self._build_application_object_key(
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
                    self._normalize_optional_non_empty_text(display_name, "display_name")
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

    def _summarize_template(self, template: WorkflowGraphTemplate) -> WorkflowTemplateValidationSummary:
        """构建图模板的结构摘要。

        参数：
        - template：待汇总的图模板。

        返回：
        - 当前图模板的结构摘要。
        """

        return WorkflowTemplateValidationSummary(
            template_id=template.template_id,
            template_version=template.template_version,
            node_count=len(template.nodes),
            edge_count=len(template.edges),
            template_input_ids=tuple(item.input_id for item in template.template_inputs),
            template_output_ids=tuple(item.output_id for item in template.template_outputs),
            referenced_node_type_ids=tuple(node.node_type_id for node in template.nodes),
        )

    def _summarize_application(self, application: FlowApplication) -> WorkflowApplicationValidationSummary:
        """构建流程应用的结构摘要。

        参数：
        - application：待汇总的流程应用。

        返回：
        - 当前流程应用的结构摘要。
        """

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

    def _iter_template_version_summaries(
        self,
        *,
        project_id: str,
    ) -> tuple[WorkflowTemplateVersionSummary, ...]:
        """遍历指定 Project 下全部图模板版本摘要。

        参数：
        - project_id：所属 Project id。

        返回：
        - 当前 Project 下全部图模板版本摘要。
        """

        templates_dir = self.dataset_storage.resolve(self._build_templates_dir_key(project_id=project_id))
        if not templates_dir.is_dir():
            return ()

        version_summaries: list[WorkflowTemplateVersionSummary] = []
        for template_file in templates_dir.glob("*/versions/*/template.json"):
            if not template_file.is_file():
                continue
            version_summaries.append(
                self._build_template_version_summary(
                    project_id=project_id,
                    object_key=self._to_object_key(template_file),
                )
            )
        return tuple(version_summaries)

    def _build_template_version_summary(
        self,
        *,
        project_id: str,
        object_key: str,
    ) -> WorkflowTemplateVersionSummary:
        """基于对象路径构建图模板版本摘要。

        参数：
        - project_id：所属 Project id。
        - object_key：模板 JSON 对象路径。

        返回：
        - 图模板版本摘要。
        """

        template = WorkflowGraphTemplate.model_validate(self.dataset_storage.read_json(object_key))
        validation_summary = self._summarize_template(template)
        resource_summary = self._read_resource_summary(object_key)
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

    def _build_application_summary(
        self,
        *,
        project_id: str,
        object_key: str,
    ) -> WorkflowApplicationSummary:
        """基于对象路径构建流程应用摘要。

        参数：
        - project_id：所属 Project id。
        - object_key：流程应用 JSON 对象路径。

        返回：
        - 流程应用摘要。
        """

        application = FlowApplication.model_validate(self.dataset_storage.read_json(object_key))
        validation_summary = self._summarize_application(application)
        resource_summary = self._read_resource_summary(object_key)
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

    def _build_resource_summary_for_save(
        self,
        *,
        object_key: str,
        actor_id: str | None,
    ) -> WorkflowStoredResourceSummary:
        """为保存动作构建 sidecar 摘要。"""

        normalized_actor_id = _normalize_optional_text(actor_id)
        existing_summary: WorkflowStoredResourceSummary | None = None
        if self.dataset_storage.resolve(object_key).is_file():
            existing_summary = self._read_resource_summary(object_key)
        now = _now_isoformat()
        return WorkflowStoredResourceSummary(
            created_at=(existing_summary.created_at if existing_summary is not None else now),
            updated_at=now,
            created_by=(
                existing_summary.created_by
                if existing_summary is not None and existing_summary.created_by is not None
                else normalized_actor_id
            ),
            updated_by=(
                normalized_actor_id
                if normalized_actor_id is not None
                else existing_summary.updated_by if existing_summary is not None else None
            ),
        )

    def _read_resource_summary(self, object_key: str) -> WorkflowStoredResourceSummary:
        """读取 workflow 资源的 sidecar 摘要。"""

        summary_key = self._build_resource_summary_object_key(object_key)
        summary_path = self.dataset_storage.resolve(summary_key)
        if summary_path.is_file():
            payload = self.dataset_storage.read_json(summary_key)
            summary = self._parse_resource_summary_payload(payload)
            if summary is not None:
                return summary
        created_at, updated_at = self._read_object_timestamps(object_key)
        return WorkflowStoredResourceSummary(
            created_at=created_at,
            updated_at=updated_at,
        )

    def _write_resource_summary(
        self,
        *,
        object_key: str,
        summary: WorkflowStoredResourceSummary,
    ) -> None:
        """写入 workflow 资源的 sidecar 摘要。"""

        self.dataset_storage.write_json(
            self._build_resource_summary_object_key(object_key),
            {
                "created_at": summary.created_at,
                "updated_at": summary.updated_at,
                "created_by": summary.created_by,
                "updated_by": summary.updated_by,
            },
        )

    def _parse_resource_summary_payload(
        self,
        payload: object,
    ) -> WorkflowStoredResourceSummary | None:
        """把 sidecar JSON 解析为资源摘要。"""

        if not isinstance(payload, dict):
            return None
        created_at = payload.get("created_at")
        updated_at = payload.get("updated_at")
        if not isinstance(created_at, str) or not created_at.strip():
            return None
        if not isinstance(updated_at, str) or not updated_at.strip():
            return None
        return WorkflowStoredResourceSummary(
            created_at=created_at,
            updated_at=updated_at,
            created_by=_normalize_optional_text(payload.get("created_by")),
            updated_by=_normalize_optional_text(payload.get("updated_by")),
        )

    def _read_object_timestamps(self, object_key: str) -> tuple[str, str]:
        """读取 workflow JSON 文件的创建和更新时间。

        参数：
        - object_key：对象存储相对路径。

        返回：
        - tuple[str, str]：按 ISO8601 文本返回的创建时间和更新时间。
        """

        file_stat = self.dataset_storage.resolve(object_key).stat()
        created_at = datetime.fromtimestamp(file_stat.st_ctime, tz=timezone.utc).isoformat().replace(
            "+00:00",
            "Z",
        )
        updated_at = datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc).isoformat().replace(
            "+00:00",
            "Z",
        )
        return created_at, updated_at

    def _build_resource_summary_object_key(self, object_key: str) -> str:
        """把主 JSON 路径转换为 sidecar 摘要路径。"""

        if object_key.endswith(".json"):
            return f"{object_key[:-5]}.summary.json"
        return f"{object_key}.summary.json"

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

    def _build_templates_dir_key(self, *, project_id: str) -> str:
        """构建当前 Project 的图模板根目录对象路径。

        参数：
        - project_id：所属 Project id。

        返回：
        - 图模板根目录对象路径。
        """

        return f"{_WORKFLOW_ROOT_DIR}/{project_id}/templates"

    def _build_template_versions_dir_key(self, *, project_id: str, template_id: str) -> str:
        """构建指定图模板的版本目录对象路径。

        参数：
        - project_id：所属 Project id。
        - template_id：模板 id。

        返回：
        - 模板版本目录对象路径。
        """

        return f"{_WORKFLOW_ROOT_DIR}/{project_id}/templates/{template_id}/versions"

    def _build_template_version_directory_key(
        self,
        *,
        project_id: str,
        template_id: str,
        template_version: str,
    ) -> str:
        """构建指定图模板版本目录对象路径。

        参数：
        - project_id：所属 Project id。
        - template_id：模板 id。
        - template_version：模板版本。

        返回：
        - 模板版本目录对象路径。
        """

        return f"{_WORKFLOW_ROOT_DIR}/{project_id}/templates/{template_id}/versions/{template_version}"

    def _build_application_object_key(
        self,
        *,
        project_id: str,
        application_id: str,
    ) -> str:
        """构建流程应用 JSON 的对象路径。"""

        return f"{_WORKFLOW_ROOT_DIR}/{project_id}/applications/{application_id}/application.json"

    def _build_applications_dir_key(self, *, project_id: str) -> str:
        """构建当前 Project 的流程应用根目录对象路径。

        参数：
        - project_id：所属 Project id。

        返回：
        - 流程应用根目录对象路径。
        """

        return f"{_WORKFLOW_ROOT_DIR}/{project_id}/applications"

    def _build_application_directory_key(self, *, project_id: str, application_id: str) -> str:
        """构建单个流程应用目录对象路径。

        参数：
        - project_id：所属 Project id。
        - application_id：流程应用 id。

        返回：
        - 流程应用目录对象路径。
        """

        return f"{_WORKFLOW_ROOT_DIR}/{project_id}/applications/{application_id}"

    def _to_object_key(self, path: Path) -> str:
        """把本地绝对路径转换回对象存储相对路径。

        参数：
        - path：当前对象在本地存储中的绝对路径。

        返回：
        - 对应的对象存储相对路径。
        """

        return path.relative_to(self.dataset_storage.root_dir).as_posix()

    def _build_natural_sort_key(self, value: str) -> tuple[tuple[int, int | str], ...]:
        """构建用于 template_version 和类似标识的自然排序键。

        参数：
        - value：待排序的版本或标识字符串。

        返回：
        - 可直接用于 sorted 的排序键。
        """

        parts = re.split(r"(\d+)", value)
        return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts if part)

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

    def _normalize_optional_non_empty_text(self, value: str | None, field_name: str) -> str | None:
        """规范化可选非空文本；传空白字符串时抛出请求错误。"""

        if value is None:
            return None
        normalized_value = value.strip()
        if not normalized_value:
            raise InvalidRequestError(
                f"{field_name} 不能为空字符串",
                details={field_name: value},
            )
        return normalized_value


def _normalize_optional_text(value: object) -> str | None:
    """规范化可选字符串值。"""

    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _now_isoformat() -> str:
    """返回当前 UTC 时间字符串。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")