"""配置字段的轻量显示节点，无文件和业务计算副作用。"""

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.display_body import validate_display_body
from backend.nodes.core_nodes.support.display_appearance import (
    APPEARANCE_SCHEMA, COLOR_PATTERN, STATE_PRESETS, display_appearance, display_color,
)
from backend.nodes.core_nodes.support.jsonl_nodes import input_value
from backend.nodes.core_nodes.support.logic import try_extract_value_by_path
from backend.service.application.runtime.io.jsonl import fail, MAX_SAFE_INTEGER
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)

FORMATS = ["text", "integer", "number", "percent", "status"]
FIELD_SCHEMA = {
    "type": "object",
    "required": ["path", "label"],
    "properties": {
        "path": {"type": "string", "minLength": 1, "title": "Path"},
        "label": {"type": "string", "maxLength": 128, "title": "Label"},
        "format": {
            "type": "string",
            "enum": FORMATS,
            "default": "text",
            "title": "Format",
        },
        "precision": {
            "type": "integer",
            "minimum": 0,
            "maximum": 6,
            "default": 2,
            "title": "Precision",
        },
        "states": {
            "type": "object",
            "title": "State Colors",
            "x-ui-widget": "state-colors",
            "additionalProperties": {
                "type": "string",
                "anyOf": [{"enum": list(STATE_PRESETS)}, {"pattern": COLOR_PATTERN}],
            },
        },
        "label_color": {"type": ["string", "null"], "title": "Label Color", "x-ui-widget": "display-color", "pattern": COLOR_PATTERN},
        "value_color": {"type": ["string", "null"], "title": "Value Color", "x-ui-widget": "display-color", "pattern": COLOR_PATTERN},
    },
}


def _handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """输出字段原始值，由前端共享组件统一格式化一次。"""
    root = input_value(request, "value")
    fields = request.parameters.get("fields")
    if not isinstance(fields, list) or not 1 <= len(fields) <= 32:
        raise fail("Fields 需要 1–32 个字段")
    output = []
    for field in fields:
        if (
            not isinstance(field, dict)
            or not isinstance(field.get("path"), str)
            or not field["path"].strip()
        ):
            raise fail("显示字段 Path 不能为空")
        label, fmt, precision = (
            field.get("label", ""),
            field.get("format", "text"),
            field.get("precision", 2),
        )
        states = field.get("states", {})
        if (
            not isinstance(label, str)
            or len(label) > 128
            or fmt not in FORMATS
            or type(precision) is not int
            or not 0 <= precision <= 6
        ):
            raise fail("显示字段 Label、Format 或 Precision 无效")
        if (
            not isinstance(states, dict)
            or len(states) > 64
            or any(
                not isinstance(k, str) or not k or len(k) > 128
                or not isinstance(v, str) or not v
                for k, v in states.items()
            )
        ):
            raise fail("State Colors 必须为有效状态与颜色的映射")
        states = {key: display_color(color, presets=True) for key, color in states.items()}
        exists, value = try_extract_value_by_path(root=root, path=field["path"])
        if not exists:
            value = None
        if isinstance(value, (dict, list)):
            raise fail("Value Display 字段必须选择标量值")
        if isinstance(value, str) and len(value) > 1024:
            raise fail("显示文本超过 1024 字符")
        if type(value) is int and abs(value) > MAX_SAFE_INTEGER:
            raise fail("显示整数超过安全范围")
        output.append(
            dict(
                label=label, value=value, format=fmt, precision=precision, states=states
            )
        )
        for key in ("label_color", "value_color"):
            if key in field:
                output[-1][key] = display_color(field[key])
    body = dict(
        type="value-display",
        fields=output,
        context=input_value(request, "context"),
        title=request.parameters.get("title", "Value Display"),
    )
    appearance = display_appearance(request.parameters.get("appearance"))
    if appearance:
        body["appearance"] = appearance
    return {"body": validate_display_body(body)}


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.io.value-display",
        display_name="Value Display",
        category="core.ui.preview",
        description="选择字段、格式和状态颜色，独立显示或与图片组合。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value", display_name="Value", payload_type_id="value.v1"
            ),
            NodePortDefinition(
                name="context",
                display_name="Context",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="body", display_name="Display Data", payload_type_id="response-body.v1"
            ),
        ),
        parameter_schema={
            "type": "object",
            "required": ["fields"],
            "properties": {
                "appearance": APPEARANCE_SCHEMA,
                "title": {
                    "type": "string",
                    "title": "Title",
                    "default": "Value Display",
                    "maxLength": 128,
                },
                "fields": {
                    "type": "array",
                    "title": "Fields",
                    "x-ui-widget": "object-rows",
                    "minItems": 1,
                    "maxItems": 32,
                    "items": FIELD_SCHEMA,
                },
            },
        },
        capability_tags=("ui.preview", "response.body"),
    ),
    handler=_handler,
)
