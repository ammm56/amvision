"""Workflow App Mode v1 配置契约与发布引用校验。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    NodeDefinition,
    WorkflowGraphTemplate,
)


WORKFLOW_APP_MODE_METADATA_KEY = "app_mode"
WORKFLOW_APP_MODE_FORMAT = "amvision.workflow-app-mode.v1"


class WorkflowAppModeDisplay(BaseModel):
    """描述 App Mode 中一个确定性的 Preview 显示槽。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    output_port: str
    title: str = Field(default="", max_length=128)
    size: Literal["small", "medium", "large"] = "medium"

    @field_validator("node_id", "output_port")
    @classmethod
    def validate_identity_text(cls, value: str, info: object) -> str:
        """规范化显示引用 identity，拒绝空值。"""

        normalized = value.strip()
        if not normalized:
            field_name = getattr(info, "field_name", "identity")
            raise ValueError(f"{field_name} 不能为空")
        return normalized

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        """移除标题首尾空白，空标题表示沿用 Preview payload 标题。"""

        return value.strip()


class WorkflowAppModeConfig(BaseModel):
    """描述随 Workflow App 发布的轻量应用模式配置。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_APP_MODE_FORMAT] = WORKFLOW_APP_MODE_FORMAT
    title: str = Field(default="", max_length=128)
    displays: tuple[WorkflowAppModeDisplay, ...] = Field(min_length=1)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        """规范化页面标题，空标题表示使用 Workflow App 显示名称。"""

        return value.strip()

    @model_validator(mode="after")
    def validate_unique_displays(self) -> WorkflowAppModeConfig:
        """拒绝重复显示 identity，数组顺序只用于布局。"""

        identities = [(item.node_id, item.output_port) for item in self.displays]
        if len(set(identities)) != len(identities):
            raise ValueError("displays 中的 node_id + output_port 不能重复")
        return self


def read_workflow_app_mode_config(
    application: FlowApplication,
) -> WorkflowAppModeConfig | None:
    """从 Application metadata 读取 App Mode；缺少配置时返回 None。"""

    if WORKFLOW_APP_MODE_METADATA_KEY not in application.metadata:
        return None
    return WorkflowAppModeConfig.model_validate(
        application.metadata[WORKFLOW_APP_MODE_METADATA_KEY]
    )


def validate_workflow_app_mode_config(
    *,
    application: FlowApplication,
    template: WorkflowGraphTemplate,
    node_definitions: tuple[NodeDefinition, ...],
) -> WorkflowAppModeConfig | None:
    """校验 App Mode 显示项只引用已启用的标准 Preview 输出。"""

    config = read_workflow_app_mode_config(application)
    if config is None:
        return None

    node_index = {node.node_id: node for node in template.nodes}
    definition_index = {
        definition.node_type_id: definition for definition in node_definitions
    }
    for display in config.displays:
        node = node_index.get(display.node_id)
        if node is None:
            raise ValueError(f"App Mode 引用了不存在的节点 {display.node_id}")
        if not node.enabled:
            raise ValueError(f"App Mode 引用了已禁用的节点 {display.node_id}")
        definition = definition_index.get(node.node_type_id)
        if definition is None:
            raise ValueError(
                f"App Mode 节点 {display.node_id} 的定义 {node.node_type_id} 不存在"
            )
        if "ui.preview" not in definition.capability_tags:
            raise ValueError(f"App Mode 节点 {display.node_id} 不是 Preview 节点")
        output_ports = {port.name for port in definition.output_ports}
        if display.output_port not in output_ports:
            raise ValueError(
                f"App Mode 节点 {display.node_id} 不存在输出端口 "
                f"{display.output_port}"
            )
    return config
