"""Workflow App Mode 配置契约测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.contracts.workflows.workflow_app_mode import (
    WorkflowAppModeConfig,
    read_workflow_app_mode_config,
    validate_workflow_app_mode_config,
)
from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    NodeDefinition,
    WorkflowGraphTemplate,
)


def _build_application(app_mode: object | None) -> FlowApplication:
    """构造包含可选 App Mode metadata 的最小 Application。"""

    metadata = {} if app_mode is None else {"app_mode": app_mode}
    return FlowApplication.model_validate(
        {
            "application_id": "workflow-app-20260905000000",
            "display_name": "App Mode test",
            "template_ref": {
                "template_id": "workflow-graph-20260905000000",
                "template_version": "1.0.0",
                "source_uri": "template.json",
            },
            "metadata": metadata,
        }
    )


def _build_template(*, enabled: bool = True) -> WorkflowGraphTemplate:
    """构造包含一个 Preview 节点的最小模板。"""

    return WorkflowGraphTemplate.model_validate(
        {
            "template_id": "workflow-graph-20260905000000",
            "template_version": "1.0.0",
            "display_name": "App Mode test graph",
            "nodes": [
                {
                    "node_id": "preview-1",
                    "node_type_id": "core.output.image-preview",
                    "enabled": enabled,
                }
            ],
        }
    )


def _build_definition(*, preview_capability: bool = True) -> NodeDefinition:
    """构造 Preview 节点目录定义。"""

    return NodeDefinition.model_validate(
        {
            "node_type_id": "core.output.image-preview",
            "display_name": "Image Preview",
            "category": "core.output.preview",
            "implementation_kind": "core-node",
            "runtime_kind": "python-callable",
            "version": "1.0.0",
            "output_ports": [
                {
                    "name": "preview",
                    "display_name": "Preview",
                    "payload_type_id": "image-preview.v1",
                }
            ],
            "capability_tags": ["ui.preview"] if preview_capability else [],
        }
    )


def test_missing_app_mode_config_is_supported() -> None:
    """缺少配置表示 Workflow 尚未提供 App Mode。"""

    application = _build_application(None)

    assert read_workflow_app_mode_config(application) is None
    assert (
        validate_workflow_app_mode_config(
            application=application,
            template=_build_template(),
            node_definitions=(_build_definition(),),
        )
        is None
    )


def test_app_mode_config_normalizes_and_validates_preview_reference() -> None:
    """合法配置会规范化文本并保留确定性的显示引用。"""

    application = _build_application(
        {
            "format_id": "amvision.workflow-app-mode.v1",
            "title": "  Production view  ",
            "displays": [
                {
                    "node_id": " preview-1 ",
                    "output_port": " preview ",
                    "title": " Main image ",
                    "size": "large",
                }
            ],
        }
    )

    config = validate_workflow_app_mode_config(
        application=application,
        template=_build_template(),
        node_definitions=(_build_definition(),),
    )

    assert config is not None
    assert config.title == "Production view"
    assert config.displays[0].node_id == "preview-1"
    assert config.displays[0].output_port == "preview"
    assert config.displays[0].title == "Main image"
    assert config.displays[0].size == "large"


@pytest.mark.parametrize(
    ("template", "definitions", "node_id", "output_port", "reason"),
    [
        (_build_template(enabled=False), (_build_definition(),), "preview-1", "preview", "已禁用"),
        (_build_template(), (_build_definition(preview_capability=False),), "preview-1", "preview", "不是 Preview"),
        (_build_template(), (), "preview-1", "preview", "定义"),
        (_build_template(), (_build_definition(),), "missing", "preview", "不存在的节点"),
        (_build_template(), (_build_definition(),), "preview-1", "missing", "不存在输出端口"),
    ],
)
def test_app_mode_rejects_invalid_preview_reference(
    template: WorkflowGraphTemplate,
    definitions: tuple[NodeDefinition, ...],
    node_id: str,
    output_port: str,
    reason: str,
) -> None:
    """发布前拒绝失效、非 Preview 或定义缺失的显示引用。"""

    application = _build_application(
        {
            "format_id": "amvision.workflow-app-mode.v1",
            "displays": [{"node_id": node_id, "output_port": output_port}],
        }
    )

    with pytest.raises(ValueError, match=reason):
        validate_workflow_app_mode_config(
            application=application,
            template=template,
            node_definitions=definitions,
        )


def test_app_mode_rejects_duplicate_display_identity() -> None:
    """同一个节点输出不能重复占用多个显示槽。"""

    with pytest.raises(ValidationError, match="不能重复"):
        WorkflowAppModeConfig.model_validate(
            {
                "format_id": "amvision.workflow-app-mode.v1",
                "displays": [
                    {"node_id": "preview-1", "output_port": "preview"},
                    {"node_id": "preview-1", "output_port": "preview"},
                ],
            }
        )


@pytest.mark.parametrize(
    "config",
    [
        {"format_id": "amvision.workflow-app-mode.v1", "displays": []},
        {
            "format_id": "amvision.workflow-app-mode.v1",
            "displays": [
                {"node_id": "preview-1", "output_port": "preview", "size": "huge"}
            ],
        },
        {
            "format_id": "amvision.workflow-app-mode.v1",
            "title": "x" * 129,
            "displays": [{"node_id": "preview-1", "output_port": "preview"}],
        },
    ],
)
def test_app_mode_rejects_invalid_shape(config: object) -> None:
    """空显示列表、非法尺寸和超长标题都不能进入发布配置。"""

    with pytest.raises(ValidationError):
        WorkflowAppModeConfig.model_validate(config)
