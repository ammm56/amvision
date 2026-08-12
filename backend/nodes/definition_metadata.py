"""统一补齐节点定义中的参数和端口说明。"""

from __future__ import annotations

import json
import re

from backend.contracts.workflows.workflow_graph import (
    NodeDefinition,
    NodeParameterUiField,
    NodeParameterUiGroup,
    NodeParameterUiSchema,
    NodePortDefinition,
)

_PARAMETER_TITLES = {
    "url": "请求地址",
    "method": "请求方法",
    "headers": "请求头",
    "body": "请求体",
    "timeout": "超时时间",
    "timeout_seconds": "超时时间（秒）",
    "poll_interval_seconds": "轮询间隔（秒）",
    "confidence": "置信度",
    "confidence_threshold": "置信度阈值",
    "iou_threshold": "IoU 阈值",
    "device": "运行设备",
    "model_path": "模型路径",
    "input_path": "输入路径",
    "output_path": "输出路径",
    "overwrite": "覆盖已有文件",
    "encoding": "文本编码",
    "format": "数据格式",
    "mode": "运行模式",
    "enabled": "是否启用",
}

_TYPE_NAMES = {
    "array": "数组",
    "boolean": "布尔值",
    "integer": "整数",
    "null": "空值",
    "number": "数值",
    "object": "对象",
    "string": "字符串",
}


def enrich_node_definition_metadata(definition: NodeDefinition) -> NodeDefinition:
    """补齐节点、参数、UI 字段和端口说明，保留已有人工元数据。"""

    parameter_schema = _enrich_schema_node(definition.parameter_schema)
    parameter_ui_schema = _enrich_parameter_ui_schema(
        definition.parameter_ui_schema,
        parameter_schema=parameter_schema,
    )
    return definition.model_copy(
        update={
            "description": definition.description.strip()
            or f"执行“{definition.display_name}”节点功能。",
            "input_ports": tuple(
                _enrich_port(port, direction="输入") for port in definition.input_ports
            ),
            "output_ports": tuple(
                _enrich_port(port, direction="输出") for port in definition.output_ports
            ),
            "parameter_schema": parameter_schema,
            "parameter_ui_schema": parameter_ui_schema,
        }
    )


def _enrich_port(port: NodePortDefinition, *, direction: str) -> NodePortDefinition:
    """补齐单个端口说明。"""

    if port.description.strip():
        return port
    requirement = "必需" if port.required else "可选"
    multiplicity = "，允许多个上游连接" if port.multiple else ""
    return port.model_copy(
        update={
            "description": (
                f"{requirement}{direction}“{port.display_name}”，"
                f"数据契约为 {port.payload_type_id}{multiplicity}。"
            )
        }
    )


def _enrich_schema_node(
    schema: dict[str, object],
    *,
    field_name: str | None = None,
    required: bool = False,
) -> dict[str, object]:
    """递归复制 JSON Schema，并补齐其中每个参数属性的标题和说明。"""

    enriched = {key: _copy_schema_value(value) for key, value in schema.items()}
    if field_name is not None:
        title = _read_non_empty_text(enriched.get("title")) or _parameter_title(field_name)
        enriched["title"] = title
        if not _read_non_empty_text(enriched.get("description")):
            enriched["description"] = _build_parameter_description(
                title=title,
                schema=enriched,
                required=required,
            )

    raw_required = enriched.get("required")
    required_names = (
        {value for value in raw_required if isinstance(value, str)}
        if isinstance(raw_required, list)
        else set()
    )
    properties = enriched.get("properties")
    if isinstance(properties, dict):
        enriched["properties"] = {
            name: _enrich_schema_node(
                value,
                field_name=name,
                required=name in required_names,
            )
            if isinstance(name, str) and isinstance(value, dict)
            else value
            for name, value in properties.items()
        }

    items = enriched.get("items")
    if isinstance(items, dict):
        enriched["items"] = _enrich_schema_node(items)
    for composition_key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        variants = enriched.get(composition_key)
        if isinstance(variants, list):
            enriched[composition_key] = [
                _enrich_schema_node(variant) if isinstance(variant, dict) else variant
                for variant in variants
            ]
    return enriched


def _copy_schema_value(value: object) -> object:
    """复制 JSON Schema 值，避免修改节点包加载得到的原始字典。"""

    if isinstance(value, dict):
        return {key: _copy_schema_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_schema_value(item) for item in value]
    return value


def _enrich_parameter_ui_schema(
    ui_schema: NodeParameterUiSchema | None,
    *,
    parameter_schema: dict[str, object],
) -> NodeParameterUiSchema | None:
    """让显式 UI schema 与已补齐的参数 schema 保持一致。"""

    if ui_schema is None:
        return None
    properties = parameter_schema.get("properties")
    property_schemas = properties if isinstance(properties, dict) else {}
    fields = tuple(
        _enrich_parameter_ui_field(field, property_schemas=property_schemas)
        for field in ui_schema.fields
    )
    groups = tuple(_enrich_parameter_ui_group(group) for group in ui_schema.groups)
    return ui_schema.model_copy(update={"fields": fields, "groups": groups})


def _enrich_parameter_ui_field(
    field: NodeParameterUiField,
    *,
    property_schemas: dict[object, object],
) -> NodeParameterUiField:
    """补齐单个参数 UI 字段说明。"""

    if field.description.strip():
        return field
    property_schema = property_schemas.get(field.parameter_name)
    description = (
        _read_non_empty_text(property_schema.get("description"))
        if isinstance(property_schema, dict)
        else None
    )
    return field.model_copy(
        update={"description": description or f"配置节点的{field.display_name}。"}
    )


def _enrich_parameter_ui_group(group: NodeParameterUiGroup) -> NodeParameterUiGroup:
    """补齐单个参数 UI 分组说明。"""

    if group.description.strip():
        return group
    return group.model_copy(update={"description": f"{group.display_name}相关参数。"})


def _parameter_title(field_name: str) -> str:
    """生成稳定、直观的参数显示名称。"""

    known_title = _PARAMETER_TITLES.get(field_name.lower())
    if known_title is not None:
        return known_title
    words = [word for word in re.split(r"[_\-\s]+", field_name.strip()) if word]
    return " ".join(_format_title_word(word) for word in words) or field_name


def _format_title_word(word: str) -> str:
    """保留常见技术缩写，其余英文词使用首字母大写。"""

    if word.lower() in {"api", "fps", "gpu", "http", "id", "iou", "nms", "roi", "url"}:
        return word.upper()
    return word[:1].upper() + word[1:]


def _build_parameter_description(
    *,
    title: str,
    schema: dict[str, object],
    required: bool,
) -> str:
    """根据 JSON Schema 约束生成可操作的参数说明。"""

    details: list[str] = ["必填参数" if required else "可选参数"]
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        details.append(f"类型为{_TYPE_NAMES.get(schema_type, schema_type)}")
    elif isinstance(schema_type, list):
        type_names = [
            _TYPE_NAMES.get(item, item) for item in schema_type if isinstance(item, str)
        ]
        if type_names:
            details.append(f"类型为{'或'.join(type_names)}")

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        details.append(f"可选值：{', '.join(_format_schema_value(value) for value in enum_values)}")
    if "default" in schema:
        details.append(f"默认值：{_format_schema_value(schema['default'])}")

    minimum = schema.get("minimum", schema.get("exclusiveMinimum"))
    maximum = schema.get("maximum", schema.get("exclusiveMaximum"))
    if minimum is not None and maximum is not None:
        details.append(f"范围：{_format_schema_value(minimum)} 至 {_format_schema_value(maximum)}")
    elif minimum is not None:
        details.append(f"最小值：{_format_schema_value(minimum)}")
    elif maximum is not None:
        details.append(f"最大值：{_format_schema_value(maximum)}")
    return f"配置节点的{title}；{'；'.join(details)}。"


def _format_schema_value(value: object) -> str:
    """把 schema 值压缩为适合节点面板显示的短文本。"""

    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= 120 else f"{text[:117]}..."


def _read_non_empty_text(value: object) -> str | None:
    """读取非空字符串。"""

    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
