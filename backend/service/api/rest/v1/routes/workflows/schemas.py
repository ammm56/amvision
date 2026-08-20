"""workflow 路由请求与响应 schema。"""

from __future__ import annotations

from typing import Literal

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
    template: WorkflowGraphTemplate | None = Field(
        default=None,
        description="可选的同请求 Template；提供时与 Application 作为一个 bundle 保存",
    )


class WorkflowApplicationUpdateRequestBody(BaseModel):
    """描述流程应用轻量更新请求体。"""

    display_name: str | None = Field(default=None, description="流程应用显示名称")
    description: str | None = Field(default=None, description="流程应用说明")


class WorkflowTemplateCopyRequestBody(BaseModel):
    """描述图模板版本复制请求体。"""

    target_template_id: str = Field(description="目标模板 id")
    target_template_version: str = Field(description="目标模板版本")
    display_name: str | None = Field(
        default=None, description="可选目标显示名称；未提供时复用源模板"
    )
    description: str | None = Field(
        default=None, description="可选目标说明；未提供时复用源模板"
    )


class WorkflowApplicationCopyRequestBody(BaseModel):
    """描述流程应用复制请求体。"""

    target_application_id: str = Field(description="目标流程应用 id")
    display_name: str | None = Field(
        default=None, description="可选目标显示名称；未提供时复用源应用"
    )
    description: str | None = Field(
        default=None, description="可选目标说明；未提供时复用源应用"
    )


class WorkflowTemplateValidationResponse(BaseModel):
    """描述图模板校验响应。"""

    valid: bool = Field(description="当前模板是否通过校验")
    template_id: str = Field(description="模板 id")
    template_version: str = Field(description="模板版本")
    node_count: int = Field(description="节点数量")
    edge_count: int = Field(description="边数量")
    template_input_ids: list[str] = Field(
        default_factory=list, description="逻辑输入 id 列表"
    )
    template_output_ids: list[str] = Field(
        default_factory=list, description="逻辑输出 id 列表"
    )
    referenced_node_type_ids: list[str] = Field(
        default_factory=list, description="引用的节点类型 id 列表"
    )


class WorkflowApplicationValidationResponse(BaseModel):
    """描述流程应用校验响应。"""

    valid: bool = Field(description="当前流程应用是否通过校验")
    application_id: str = Field(description="流程应用 id")
    template_id: str = Field(description="引用的模板 id")
    template_version: str = Field(description="引用的模板版本")
    binding_count: int = Field(description="绑定数量")
    input_binding_ids: list[str] = Field(
        default_factory=list, description="输入绑定 id 列表"
    )
    output_binding_ids: list[str] = Field(
        default_factory=list, description="输出绑定 id 列表"
    )


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
    draft_fingerprint: str = Field(
        description="当前 Application 与 Template 草稿的稳定指纹"
    )
    template_summary: "WorkflowTemplateReferenceSummaryResponse | None" = Field(
        default=None,
        description="引用模板的一跳摘要",
    )
    application: FlowApplication = Field(description="流程应用内容")


class WorkflowApplicationBundleSaveResponse(WorkflowApplicationDocumentResponse):
    """描述 Application 与 Template bundle 保存结果。"""

    saved_template: WorkflowTemplateDocumentResponse = Field(
        description="与 Application 在同一状态门内保存的 Template"
    )


class WorkflowAppVersionPublishRequestBody(BaseModel):
    """描述一次 Workflow App 版本发布请求。"""

    expected_draft_fingerprint: str = Field(description="发布前读取的草稿指纹")
    release_notes: str = Field(default="", max_length=4096, description="版本说明")
    display_version: str | None = Field(
        default=None, max_length=128, description="可选显示版本"
    )
    allow_duplicate_content: bool = Field(
        default=False, description="是否允许重复发布相同内容"
    )


class WorkflowAppVersionArchiveRequestBody(BaseModel):
    """描述已发布版本的归档 CAS 请求。"""

    expected_state: Literal["published"] = Field(
        default="published",
        description="调用方读取到的预期状态",
    )


class WorkflowAppVersionRestoreRequestBody(BaseModel):
    """描述归档版本的恢复 CAS 请求。"""

    expected_state: Literal["archived"] = Field(
        default="archived",
        description="调用方读取到的预期状态",
    )


class WorkflowAppVersionResponse(BaseModel):
    """描述一条不可变 Workflow App 版本记录。"""

    format_id: Literal["amvision.workflow-app-version.v1"] = (
        "amvision.workflow-app-version.v1"
    )
    workflow_app_version_id: str
    project_id: str
    application_id: str
    version_number: int
    display_version: str
    release_notes: str
    application_snapshot_object_key: str
    template_snapshot_object_key: str
    contract_snapshot_object_key: str
    dependency_manifest_object_key: str
    content_fingerprint: str
    contract_fingerprint: str
    state: str
    created_at: str
    created_by: str | None = None
    completed_at: str | None = None
    error: str | None = None


class WorkflowAppVersionDetailResponse(WorkflowAppVersionResponse):
    """描述版本记录和完整不可变发布内容。"""

    application: dict[str, object]
    template: dict[str, object]
    contract: dict[str, object]
    dependencies: dict[str, object]
    manifest: dict[str, object]


class WorkflowAppVersionComparisonResponse(BaseModel):
    """描述已发布版本与当前草稿的契约差异。"""

    compatible: bool
    changes: list[dict[str, object]] = Field(default_factory=list)
    breaking_changes: list[dict[str, object]] = Field(default_factory=list)
    source_contract_fingerprint: str
    target_contract_fingerprint: str


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

    node_pack_manifests: list[NodePackManifest] = Field(
        default_factory=list, description="节点包 manifest 列表"
    )
    payload_contracts: list[WorkflowPayloadContract] = Field(
        default_factory=list,
        description="payload 规则 列表",
    )
    node_definitions: list[NodeDefinition] = Field(
        default_factory=list, description="节点定义列表"
    )
    palette_groups: list["WorkflowNodePaletteGroupResponse"] = Field(
        default_factory=list,
        description="按分类分组后的 palette 结果",
    )


class WorkflowNodePaletteGroupResponse(BaseModel):
    """描述前端可直接消费的节点 palette 分组结果。"""

    category: str = Field(description="节点分类 id")
    display_name: str = Field(description="分组显示名称")
    item_count: int = Field(description="当前分组的节点数量")
    node_definitions: list[NodeDefinition] = Field(
        default_factory=list, description="当前分组下的节点定义列表"
    )


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
    custom_node_catalog_path: str | None = Field(
        default=None, description="自定义节点目录文件路径"
    )
    loaded_at: str | None = Field(default=None, description="最近一次 loader 扫描时间")
    node_count: int = Field(description="当前成功加载的节点数量")
    capabilities: list[str] = Field(default_factory=list, description="能力标签")
    dependencies: list[WorkflowNodePackDependencyStatusResponse] = Field(
        default_factory=list,
        description="依赖状态列表",
    )
    issues: list[WorkflowNodePackStatusIssueResponse] = Field(
        default_factory=list, description="问题列表"
    )
    logs: list[WorkflowNodePackStatusLogResponse] = Field(
        default_factory=list, description="状态日志"
    )
    manifest: dict[str, object] | None = Field(
        default=None, description="manifest JSON 摘要"
    )


class WorkflowNodePackStatusResponse(BaseModel):
    """描述 node pack loader 状态快照响应。"""

    generated_at: str = Field(description="快照生成时间")
    custom_nodes_root_dir: str = Field(description="custom_nodes 根目录")
    items: list[WorkflowNodePackStatusItemResponse] = Field(
        default_factory=list, description="node pack 状态列表"
    )
    logs: list[WorkflowNodePackStatusLogResponse] = Field(
        default_factory=list, description="聚合日志"
    )


class WorkflowNodePackVersionResponse(BaseModel):
    """描述节点包版本库中的一个版本。"""

    node_pack_id: str = Field(description="node pack id")
    version: str = Field(description="节点包版本")
    content_sha256: str = Field(description="规范化内容 SHA-256")
    directory_name: str = Field(description="稳定运行时目录名")
    installed_at: str = Field(description="版本登记时间")
    installed_by: str = Field(description="版本登记主体 id")
    source_file_name: str | None = Field(default=None, description="安装 ZIP 文件名")
    active: bool = Field(description="是否为当前激活版本")


class WorkflowNodePackAuditResponse(BaseModel):
    """描述节点包生命周期审计事件。"""

    event_id: str = Field(description="审计事件 id")
    action: str = Field(
        description="install、upgrade、rollback、enable、disable 等动作"
    )
    status: str = Field(description="succeeded 或 failed")
    created_at: str = Field(description="事件时间")
    actor_id: str = Field(description="操作主体 id")
    node_pack_id: str | None = Field(default=None, description="node pack id")
    from_version: str | None = Field(default=None, description="操作前版本")
    to_version: str | None = Field(default=None, description="目标版本")
    content_sha256: str | None = Field(default=None, description="目标内容 SHA-256")
    source_file_name: str | None = Field(default=None, description="安装 ZIP 文件名")
    details: dict[str, object] = Field(default_factory=dict, description="附加审计细节")


class WorkflowNodePackLifecycleResponse(BaseModel):
    """描述节点包安装、升级或回滚结果。"""

    node_pack_id: str = Field(description="node pack id")
    version: str = Field(description="当前激活版本")
    active_directory: str = Field(description="当前激活目录名")
    versions: list[WorkflowNodePackVersionResponse] = Field(
        default_factory=list,
        description="全部可回滚版本",
    )
    audit: WorkflowNodePackAuditResponse = Field(description="本次生命周期审计事件")
    status: WorkflowNodePackStatusResponse = Field(description="激活后的 loader 状态")


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
    versions: list[str] = Field(
        default_factory=list, description="全部模板版本 id 列表"
    )


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
    template_input_ids: list[str] = Field(
        default_factory=list, description="逻辑输入 id 列表"
    )
    template_output_ids: list[str] = Field(
        default_factory=list, description="逻辑输出 id 列表"
    )
    referenced_node_type_ids: list[str] = Field(
        default_factory=list, description="引用的节点类型 id 列表"
    )


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
    input_binding_ids: list[str] = Field(
        default_factory=list, description="输入绑定 id 列表"
    )
    output_binding_ids: list[str] = Field(
        default_factory=list, description="输出绑定 id 列表"
    )
