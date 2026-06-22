"""workflow 路由请求与响应 schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.contracts.nodes import NodePackManifest
from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    NodeDefinition,
    WorkflowGraphTemplate,
    WorkflowPayloadContract,
)

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


class WorkflowTemplateCopyRequestBody(BaseModel):
    """描述图模板版本复制请求体。"""

    target_template_id: str = Field(description="目标模板 id")
    target_template_version: str = Field(description="目标模板版本")
    display_name: str | None = Field(default=None, description="可选目标显示名称；未提供时复用源模板")
    description: str | None = Field(default=None, description="可选目标说明；未提供时复用源模板")


class WorkflowApplicationCopyRequestBody(BaseModel):
    """描述流程应用复制请求体。"""

    target_application_id: str = Field(description="目标流程应用 id")
    display_name: str | None = Field(default=None, description="可选目标显示名称；未提供时复用源应用")
    description: str | None = Field(default=None, description="可选目标说明；未提供时复用源应用")


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
    - payload_contracts：当前已注册的 payload 规则 列表。
    - node_definitions：当前已注册的节点定义列表。
    - palette_groups：按节点分类整理后的 palette 分组结果。
    """

    node_pack_manifests: list[NodePackManifest] = Field(default_factory=list, description="节点包 manifest 列表")
    payload_contracts: list[WorkflowPayloadContract] = Field(
        default_factory=list,
        description="payload 规则 列表",
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


class WorkflowNodePackStatusIssueResponse(BaseModel):
    """描述 node pack 状态问题响应。"""

    severity: str = Field(description="问题级别")
    code: str = Field(description="稳定问题码")
    message: str = Field(description="问题消息")
    details: dict[str, object] = Field(default_factory=dict, description="附加问题细节")


class WorkflowNodePackStatusLogResponse(BaseModel):
    """描述 node pack 状态日志响应。"""

    level: str = Field(description="日志级别")
    message: str = Field(description="日志消息")
    created_at: str = Field(description="日志生成时间")
    details: dict[str, object] = Field(default_factory=dict, description="附加日志细节")


class WorkflowNodePackDependencyStatusResponse(BaseModel):
    """描述 node pack 依赖状态响应。"""

    node_pack_id: str = Field(description="依赖的 node pack id")
    version_range: str | None = Field(default=None, description="依赖版本范围")
    installed: bool = Field(description="依赖包是否存在")
    enabled: bool = Field(description="依赖包是否启用")
    version: str | None = Field(default=None, description="当前发现的依赖包版本")
    satisfied: bool = Field(description="依赖是否满足")


class WorkflowNodePackStatusItemResponse(BaseModel):
    """描述单个 node pack 状态响应。"""

    node_pack_id: str = Field(description="node pack id")
    display_name: str = Field(description="显示名称")
    version: str | None = Field(default=None, description="版本号")
    state: str = Field(description="状态：loaded、disabled 或 failed")
    enabled: bool = Field(description="manifest 当前是否启用")
    source_dir: str = Field(description="来源目录")
    manifest_path: str | None = Field(default=None, description="manifest 文件路径")
    custom_node_catalog_path: str | None = Field(default=None, description="自定义节点目录文件路径")
    loaded_at: str | None = Field(default=None, description="最近一次 loader 扫描时间")
    node_count: int = Field(description="当前成功加载的节点数量")
    capabilities: list[str] = Field(default_factory=list, description="能力标签")
    permission_scopes: list[str] = Field(default_factory=list, description="权限 scope")
    dependencies: list[WorkflowNodePackDependencyStatusResponse] = Field(
        default_factory=list,
        description="依赖状态列表",
    )
    issues: list[WorkflowNodePackStatusIssueResponse] = Field(default_factory=list, description="问题列表")
    logs: list[WorkflowNodePackStatusLogResponse] = Field(default_factory=list, description="状态日志")
    manifest: dict[str, object] | None = Field(default=None, description="manifest JSON 摘要")


class WorkflowNodePackStatusResponse(BaseModel):
    """描述 node pack loader 状态快照响应。"""

    generated_at: str = Field(description="快照生成时间")
    custom_nodes_root_dir: str = Field(description="custom_nodes 根目录")
    items: list[WorkflowNodePackStatusItemResponse] = Field(default_factory=list, description="node pack 状态列表")
    logs: list[WorkflowNodePackStatusLogResponse] = Field(default_factory=list, description="聚合日志")


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
