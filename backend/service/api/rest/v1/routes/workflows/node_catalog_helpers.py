"""workflow node catalog 路由支撑函数。"""

from __future__ import annotations

import json

from backend.contracts.nodes import NodePackManifest
from backend.contracts.workflows.workflow_graph import (
    NodeDefinition,
    NodeParameterUiEnumOption,
    NodeParameterUiField,
    NodeParameterUiGroup,
    NodeParameterUiSchema,
    WorkflowPayloadContract,
)

from .schemas import WorkflowNodePaletteGroupResponse


_WORKFLOW_PARAMETER_UI_EXTENSION_KEY = "x-amvision-ui"
_WORKFLOW_PARAMETER_DEFAULT_GROUP_ID = "default"

def _build_workflow_node_palette_groups(
    node_definitions: list[NodeDefinition],
) -> list[WorkflowNodePaletteGroupResponse]:
    """把节点定义整理为前端可直接消费的 palette 分组结果。"""

    grouped_nodes: dict[str, list[NodeDefinition]] = {}
    for node_definition in node_definitions:
        grouped_nodes.setdefault(node_definition.category, []).append(node_definition)

    palette_groups: list[WorkflowNodePaletteGroupResponse] = []
    for category in sorted(grouped_nodes):
        grouped_items = sorted(
            grouped_nodes[category],
            key=lambda item: (item.display_name.casefold(), item.node_type_id.casefold()),
        )
        palette_groups.append(
            WorkflowNodePaletteGroupResponse(
                category=category,
                display_name=_build_workflow_palette_group_display_name(category),
                item_count=len(grouped_items),
                node_definitions=grouped_items,
            )
        )
    return palette_groups


def _build_effective_node_definitions(node_definitions: list[NodeDefinition]) -> list[NodeDefinition]:
    """为节点目录响应补齐可直接渲染的 parameter_ui_schema。"""

    return [_with_effective_parameter_ui_schema(item) for item in node_definitions]


def _with_effective_parameter_ui_schema(node_definition: NodeDefinition) -> NodeDefinition:
    """为单个节点定义补齐 parameter_ui_schema。"""

    return node_definition.model_copy(
        update={
            "parameter_ui_schema": _merge_parameter_ui_schema(
                parameter_schema=node_definition.parameter_schema,
                explicit_parameter_ui_schema=node_definition.parameter_ui_schema,
            )
        }
    )


def _merge_parameter_ui_schema(
    *,
    parameter_schema: dict[str, object],
    explicit_parameter_ui_schema: NodeParameterUiSchema | None,
) -> NodeParameterUiSchema:
    """把原始 parameter_schema 和显式 parameter_ui_schema 合并为稳定规则。"""

    derived_parameter_ui_schema = _derive_parameter_ui_schema_from_parameter_schema(parameter_schema)
    if explicit_parameter_ui_schema is None:
        return derived_parameter_ui_schema

    group_index = {item.group_id: item for item in derived_parameter_ui_schema.groups}
    for group in explicit_parameter_ui_schema.groups:
        group_index[group.group_id] = group

    field_index = {item.parameter_name: item for item in derived_parameter_ui_schema.fields}
    for field in explicit_parameter_ui_schema.fields:
        field_index[field.parameter_name] = field

    for field in field_index.values():
        if field.group_id not in group_index:
            group_index[field.group_id] = NodeParameterUiGroup(
                group_id=field.group_id,
                display_name=_humanize_parameter_text(field.group_id),
            )

    return NodeParameterUiSchema(
        groups=tuple(
            sorted(
                group_index.values(),
                key=lambda item: (item.order, item.display_name.casefold(), item.group_id.casefold()),
            )
        ),
        fields=tuple(
            sorted(
                field_index.values(),
                key=lambda item: (item.order, item.display_name.casefold(), item.parameter_name.casefold()),
            )
        ),
    )


def _derive_parameter_ui_schema_from_parameter_schema(
    parameter_schema: dict[str, object],
) -> NodeParameterUiSchema:
    """从 parameter_schema 推导稳定的参数 UI 规则。"""

    if not isinstance(parameter_schema, dict):
        return NodeParameterUiSchema()
    raw_properties = parameter_schema.get("properties")
    if not isinstance(raw_properties, dict) or not raw_properties:
        return NodeParameterUiSchema()

    raw_required_names = parameter_schema.get("required")
    required_names = (
        {
            item.strip()
            for item in raw_required_names
            if isinstance(item, str) and item.strip()
        }
        if isinstance(raw_required_names, list)
        else set()
    )
    root_ui_extension = _read_parameter_ui_extension(parameter_schema)
    group_index = _build_parameter_ui_group_index(root_ui_extension.get("groups"))
    fields: list[NodeParameterUiField] = []

    for fallback_order, (parameter_name, raw_property_schema) in enumerate(raw_properties.items()):
        if not isinstance(parameter_name, str) or not parameter_name.strip():
            continue
        property_schema = dict(raw_property_schema) if isinstance(raw_property_schema, dict) else {}
        property_ui_extension = _read_parameter_ui_extension(property_schema)
        group_id = (
            _read_optional_non_empty_text(property_ui_extension.get("group"))
            or _WORKFLOW_PARAMETER_DEFAULT_GROUP_ID
        )
        if group_id not in group_index:
            group_index[group_id] = NodeParameterUiGroup(
                group_id=group_id,
                display_name=_humanize_parameter_text(group_id),
                order=len(group_index),
            )

        readonly = _read_optional_bool(property_ui_extension.get("readonly"))
        if readonly is None:
            readonly = _read_optional_bool(property_schema.get("readOnly")) or False
        hidden = _read_optional_bool(property_ui_extension.get("hidden")) or False
        field_order = _read_optional_int(property_ui_extension.get("order"))
        fields.append(
            NodeParameterUiField(
                parameter_name=parameter_name,
                display_name=(
                    _read_optional_non_empty_text(property_schema.get("title"))
                    or _humanize_parameter_text(parameter_name)
                ),
                description=_read_optional_non_empty_text(property_schema.get("description")) or "",
                group_id=group_id,
                order=fallback_order if field_order is None else field_order,
                required=parameter_name in required_names,
                hidden=hidden,
                readonly=readonly,
                default_value=property_schema.get("default") if "default" in property_schema else None,
                enum_options=_build_parameter_ui_enum_options(property_schema, property_ui_extension),
                json_schema=_sanitize_parameter_schema_fragment(property_schema),
            )
        )

    return NodeParameterUiSchema(
        groups=tuple(
            sorted(
                group_index.values(),
                key=lambda item: (item.order, item.display_name.casefold(), item.group_id.casefold()),
            )
        ),
        fields=tuple(
            sorted(
                fields,
                key=lambda item: (item.order, item.display_name.casefold(), item.parameter_name.casefold()),
            )
        ),
    )


def _build_parameter_ui_group_index(raw_groups: object) -> dict[str, NodeParameterUiGroup]:
    """把参数 UI 分组配置解析为按 group_id 索引的字典。"""

    group_index: dict[str, NodeParameterUiGroup] = {}
    if isinstance(raw_groups, dict):
        for fallback_order, (raw_group_id, raw_group_config) in enumerate(raw_groups.items()):
            if not isinstance(raw_group_id, str) or not raw_group_id.strip():
                continue
            group_id = raw_group_id.strip()
            group_config = raw_group_config if isinstance(raw_group_config, dict) else {}
            group_index[group_id] = NodeParameterUiGroup(
                group_id=group_id,
                display_name=(
                    _read_optional_non_empty_text(group_config.get("display_name"))
                    or _read_optional_non_empty_text(group_config.get("title"))
                    or _humanize_parameter_text(group_id)
                ),
                description=_read_optional_non_empty_text(group_config.get("description")) or "",
                order=_read_optional_int(group_config.get("order")) or fallback_order,
            )
        return group_index

    if isinstance(raw_groups, list):
        for fallback_order, raw_group_item in enumerate(raw_groups):
            if not isinstance(raw_group_item, dict):
                continue
            group_id = _read_optional_non_empty_text(raw_group_item.get("group_id") or raw_group_item.get("id"))
            if group_id is None:
                continue
            group_index[group_id] = NodeParameterUiGroup(
                group_id=group_id,
                display_name=(
                    _read_optional_non_empty_text(raw_group_item.get("display_name"))
                    or _read_optional_non_empty_text(raw_group_item.get("title"))
                    or _humanize_parameter_text(group_id)
                ),
                description=_read_optional_non_empty_text(raw_group_item.get("description")) or "",
                order=_read_optional_int(raw_group_item.get("order")) or fallback_order,
            )
    return group_index


def _build_parameter_ui_enum_options(
    property_schema: dict[str, object],
    property_ui_extension: dict[str, object],
) -> tuple[NodeParameterUiEnumOption, ...]:
    """从参数 schema 构建稳定的枚举选项展示列表。"""

    raw_enum_values = property_schema.get("enum")
    if not isinstance(raw_enum_values, list):
        return ()
    raw_enum_labels = property_ui_extension.get("enum_labels")
    if raw_enum_labels is None:
        raw_enum_labels = property_schema.get("enumNames")

    options: list[NodeParameterUiEnumOption] = []
    for index, enum_value in enumerate(raw_enum_values):
        label = None
        if isinstance(raw_enum_labels, list) and index < len(raw_enum_labels):
            label = _read_optional_non_empty_text(raw_enum_labels[index])
        elif isinstance(raw_enum_labels, dict):
            label = _read_optional_non_empty_text(raw_enum_labels.get(_stringify_parameter_option_key(enum_value)))
        options.append(
            NodeParameterUiEnumOption(
                value=enum_value,
                label=label or _humanize_parameter_text(_stringify_parameter_option_key(enum_value)),
            )
        )
    return tuple(options)


def _read_parameter_ui_extension(payload: dict[str, object]) -> dict[str, object]:
    """读取 parameter_schema 中预留的 UI 扩展字段。"""

    raw_extension = payload.get(_WORKFLOW_PARAMETER_UI_EXTENSION_KEY)
    return dict(raw_extension) if isinstance(raw_extension, dict) else {}


def _sanitize_parameter_schema_fragment(property_schema: dict[str, object]) -> dict[str, object]:
    """移除仅用于编辑器扩展的保留字段，保留原始 JSON Schema 片段。"""

    return {
        key: value
        for key, value in property_schema.items()
        if key != _WORKFLOW_PARAMETER_UI_EXTENSION_KEY
    }


def _read_optional_non_empty_text(value: object) -> str | None:
    """读取一个可选非空字符串。"""

    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _read_optional_int(value: object) -> int | None:
    """读取一个可选整数。"""

    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _read_optional_bool(value: object) -> bool | None:
    """读取一个可选布尔值。"""

    return value if isinstance(value, bool) else None


def _humanize_parameter_text(value: str) -> str:
    """把参数名或分组名转换为更适合界面展示的文本。"""

    normalized_value = value.replace(".", " ").replace("-", " ").replace("_", " ").strip()
    if not normalized_value:
        return value
    return normalized_value.title()


def _stringify_parameter_option_key(value: object) -> str:
    """把枚举值转换为稳定的字符串键，用于匹配显式标签。"""

    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)


def _build_workflow_palette_group_display_name(category: str) -> str:
    """把节点分类 id 转换为更适合 palette 展示的分组名称。"""

    category_tokens = [token for token in category.replace("-", ".").replace("_", ".").split(".") if token]
    if not category_tokens:
        return category
    return " / ".join(_humanize_palette_token(token) for token in category_tokens)


def _humanize_palette_token(token: str) -> str:
    """把 palette 分类片段转换为展示文本。"""

    token_mapping = {
        "api": "API",
        "cv": "CV",
        "io": "IO",
        "opencv": "OpenCV",
        "plc": "PLC",
        "sdk": "SDK",
        "ui": "UI",
        "zmq": "ZeroMQ",
    }
    normalized_token = token.strip().casefold()
    if normalized_token in token_mapping:
        return token_mapping[normalized_token]
    return token.replace("-", " ").replace("_", " ").title()


def _filter_workflow_node_definitions(
    *,
    node_definitions: tuple[NodeDefinition, ...],
    category: str | None,
    node_pack_id: str | None,
    payload_type_id: str | None,
    keyword: str | None,
) -> list[NodeDefinition]:
    """按查询条件过滤 workflow 节点定义列表。

    参数：
    - node_definitions：待过滤的节点定义列表。
    - category：可选节点分类前缀。
    - node_pack_id：可选节点包 id。
    - payload_type_id：可选端口 payload 类型。
    - keyword：可选关键词。

    返回：
    - list[NodeDefinition]：过滤后的节点定义列表。
    """

    normalized_category = _normalize_optional_filter_text(category)
    normalized_node_pack_id = _normalize_optional_filter_text(node_pack_id)
    normalized_payload_type_id = _normalize_optional_filter_text(payload_type_id)
    normalized_keyword = _normalize_optional_filter_text(keyword)

    filtered_items: list[NodeDefinition] = []
    for node_definition in node_definitions:
        if normalized_category is not None and not node_definition.category.casefold().startswith(normalized_category):
            continue
        if normalized_node_pack_id is not None:
            if node_definition.node_pack_id is None or node_definition.node_pack_id.casefold() != normalized_node_pack_id:
                continue
        if normalized_payload_type_id is not None:
            payload_type_ids = {
                port.payload_type_id.casefold()
                for port in (*node_definition.input_ports, *node_definition.output_ports)
            }
            if normalized_payload_type_id not in payload_type_ids:
                continue
        if normalized_keyword is not None:
            searchable_values = (
                node_definition.node_type_id,
                node_definition.display_name,
                node_definition.description,
                node_definition.category,
            )
            if not any(normalized_keyword in value.casefold() for value in searchable_values if value):
                continue
        filtered_items.append(node_definition)
    return filtered_items


def _filter_workflow_payload_contracts(
    *,
    payload_contracts: tuple[WorkflowPayloadContract, ...],
    node_definitions: list[NodeDefinition],
    payload_type_id: str | None,
    filters_active: bool,
) -> list[WorkflowPayloadContract]:
    """按节点过滤结果裁剪 payload 规则 列表。

    参数：
    - payload_contracts：待过滤的 payload 规则 列表。
    - node_definitions：已经过滤后的节点定义列表。
    - payload_type_id：可选显式 payload 类型过滤条件。
    - filters_active：当前是否存在任何过滤条件。

    返回：
    - list[WorkflowPayloadContract]：过滤后的 payload 规则 列表。
    """

    if not filters_active:
        return list(payload_contracts)

    referenced_payload_type_ids = {
        port.payload_type_id
        for node_definition in node_definitions
        for port in (*node_definition.input_ports, *node_definition.output_ports)
    }
    normalized_payload_type_id = _normalize_optional_filter_text(payload_type_id)
    if normalized_payload_type_id is not None:
        referenced_payload_type_ids.update(
            contract.payload_type_id
            for contract in payload_contracts
            if contract.payload_type_id.casefold() == normalized_payload_type_id
        )

    return [
        contract
        for contract in payload_contracts
        if contract.payload_type_id in referenced_payload_type_ids
    ]


def _filter_node_pack_manifests(
    *,
    node_pack_manifests: tuple[NodePackManifest, ...],
    node_definitions: list[NodeDefinition],
    node_pack_id: str | None,
    filters_active: bool,
) -> list[NodePackManifest]:
    """按节点过滤结果裁剪节点包 manifest 列表。

    参数：
    - node_pack_manifests：待过滤的节点包 manifest 列表。
    - node_definitions：已经过滤后的节点定义列表。
    - node_pack_id：可选显式节点包 id 过滤条件。
    - filters_active：当前是否存在任何过滤条件。

    返回：
    - list[NodePackManifest]：过滤后的节点包 manifest 列表。
    """

    normalized_node_pack_id = _normalize_optional_filter_text(node_pack_id)
    if normalized_node_pack_id is not None:
        return [
            manifest
            for manifest in node_pack_manifests
            if manifest.node_pack_id.casefold() == normalized_node_pack_id
        ]
    if not filters_active:
        return list(node_pack_manifests)

    referenced_node_pack_ids = {
        node_definition.node_pack_id
        for node_definition in node_definitions
        if node_definition.node_pack_id is not None
    }
    return [
        manifest
        for manifest in node_pack_manifests
        if manifest.node_pack_id in referenced_node_pack_ids
    ]


def _normalize_optional_filter_text(value: str | None) -> str | None:
    """规范化可选查询过滤值。

    参数：
    - value：原始过滤值。

    返回：
    - str | None：去除空白并转为小写后的过滤值；空值返回 None。
    """

    if value is None:
        return None
    normalized_value = value.strip()
    if not normalized_value:
        return None
    return normalized_value.casefold()
