"""任意值预览节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import require_value_payload, try_extract_value_by_path
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.application.workflows.preview_display_outputs import register_preview_display_output


def _value_preview_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """把任意 value.v1 包装成可显示的 value-preview body。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包含 value-preview body 的节点输出。
    """

    value_payload = require_value_payload(request.input_values.get("value"), field_name="value")
    preview_value = value_payload["value"]
    normalized_path = _read_optional_path_parameter(request.parameters.get("path"))
    preview_body: dict[str, object] = {
        "type": "value-preview",
        "value": preview_value,
    }
    title = request.parameters.get("title")
    if isinstance(title, str) and title.strip():
        preview_body["title"] = title.strip()
    if normalized_path is not None:
        path_exists, extracted_value = try_extract_value_by_path(root=preview_value, path=normalized_path)
        preview_body["path"] = normalized_path
        if path_exists:
            preview_body["value"] = extracted_value
            preview_body["status_text"] = f"Path: {normalized_path}"
        else:
            preview_body["value"] = None
            preview_body["missing_path"] = True
            preview_body["empty_text"] = f"未找到路径：{normalized_path}"
    register_preview_display_output(
        request.execution_metadata,
        node_id=request.node_id,
        node_type_id=request.node_definition.node_type_id,
        output_name="body",
        payload=preview_body,
    )
    return {"body": preview_body}


def _read_optional_path_parameter(raw_value: object) -> str | None:
    """读取可选 path 参数。

    参数：
    - raw_value：节点参数中的原始 path 值。

    返回：
    - str | None：规范化后的 path；未设置时返回 None。
    """

    if raw_value is None or not isinstance(raw_value, str):
        return None
    normalized_path = raw_value.strip()
    return normalized_path or None


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.value-preview",
        display_name="Value Preview",
        category="ui.preview",
        description="把任意 value.v1 转成可直接在 workflow editor 和 HTTP 响应里显示的 JSON 预览 body。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="body",
                display_name="Body",
                payload_type_id="response-body.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "minLength": 1,
                    "default": "Value Preview",
                    "title": "标题",
                    "description": "JSON 预览卡片显示名称。",
                },
                "path": {
                    "type": "string",
                    "minLength": 1,
                    "title": "Path",
                    "description": "可选点分路径；例如 items.0.class_name，只预览某个子字段。",
                },
            },
        },
        capability_tags=("ui.preview", "response.body"),
    ),
    handler=_value_preview_handler,
)