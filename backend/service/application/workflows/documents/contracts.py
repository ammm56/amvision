"""workflow 文档服务使用的对象定义。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.contracts.workflows.workflow_graph import FlowApplication, WorkflowGraphTemplate


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
