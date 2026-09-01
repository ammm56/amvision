"""Workflow 节点运行时参数输入解析。"""

from __future__ import annotations

from copy import deepcopy

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from backend.contracts.workflows.workflow_graph import NodeDefinition
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)


def resolve_node_parameters(
    *,
    node_id: str,
    node_definition: NodeDefinition,
    static_parameters: dict[str, object],
    input_values: dict[str, object],
) -> dict[str, object]:
    """按连接输入、固定参数和 schema 默认值构建节点最终参数。

    参数：
    - node_id：当前节点实例 id。
    - node_definition：当前节点定义。
    - static_parameters：WorkflowGraphNode 保存的固定参数。
    - input_values：已经解析完成的节点输入端口 payload。

    返回：
    - dict[str, object]：供节点 handler 只读使用的最终参数副本。
    """

    effective_parameters = dict(static_parameters)
    if not node_definition.parameter_input_bindings:
        return effective_parameters
    raw_properties = node_definition.parameter_schema.get("properties")
    if not isinstance(raw_properties, dict):
        raise ServiceConfigurationError(
            "节点动态参数 schema 配置无效",
            details={
                "node_id": node_id,
                "node_type_id": node_definition.node_type_id,
                "schema_path": ["properties"],
            },
        )
    required_parameters = _read_required_parameter_names(
        node_id=node_id,
        node_definition=node_definition,
    )
    for binding in node_definition.parameter_input_bindings:
        parameter_name = binding.parameter_name
        input_port_name = binding.input_port_name
        parameter_schema = raw_properties.get(parameter_name)
        if not isinstance(parameter_schema, dict):
            raise ServiceConfigurationError(
                "节点动态参数属性 schema 配置无效",
                details={
                    "node_id": node_id,
                    "node_type_id": node_definition.node_type_id,
                    "parameter_name": parameter_name,
                    "input_port_name": input_port_name,
                    "schema_path": ["properties", parameter_name],
                },
            )
        input_payload = input_values.get(input_port_name)
        if input_payload is not None:
            parameter_value = _read_value_payload(
                node_id=node_id,
                node_definition=node_definition,
                parameter_name=parameter_name,
                input_port_name=input_port_name,
                input_payload=input_payload,
            )
            value_source = "input"
            effective_parameters[parameter_name] = parameter_value
        elif parameter_name in effective_parameters:
            parameter_value = effective_parameters[parameter_name]
            value_source = "parameter"
        elif "default" in parameter_schema:
            parameter_value = deepcopy(parameter_schema["default"])
            value_source = "default"
            effective_parameters[parameter_name] = parameter_value
        elif parameter_name in required_parameters:
            raise InvalidRequestError(
                "节点缺少必需的动态参数",
                details={
                    "node_id": node_id,
                    "node_type_id": node_definition.node_type_id,
                    "parameter_name": parameter_name,
                    "input_port_name": input_port_name,
                    "value_source": "missing",
                },
            )
        else:
            continue
        _validate_parameter_value(
            node_id=node_id,
            node_definition=node_definition,
            parameter_name=parameter_name,
            input_port_name=input_port_name,
            parameter_schema=parameter_schema,
            parameter_value=parameter_value,
            value_source=value_source,
        )
    return effective_parameters


def _read_required_parameter_names(
    *,
    node_id: str,
    node_definition: NodeDefinition,
) -> frozenset[str]:
    """读取并校验参数 schema 的 required 名称列表。"""

    raw_required = node_definition.parameter_schema.get("required", ())
    if raw_required is None:
        return frozenset()
    if not isinstance(raw_required, (list, tuple)) or not all(
        isinstance(item, str) and item for item in raw_required
    ):
        raise ServiceConfigurationError(
            "节点参数 schema 的 required 配置无效",
            details={
                "node_id": node_id,
                "node_type_id": node_definition.node_type_id,
                "schema_path": ["required"],
            },
        )
    return frozenset(raw_required)


def _read_value_payload(
    *,
    node_id: str,
    node_definition: NodeDefinition,
    parameter_name: str,
    input_port_name: str,
    input_payload: object,
) -> object:
    """读取参数输入端口中的 ``value.v1`` 内部值。"""

    if not isinstance(input_payload, dict) or "value" not in input_payload:
        raise InvalidRequestError(
            "节点动态参数输入必须是有效的 value.v1",
            details={
                "node_id": node_id,
                "node_type_id": node_definition.node_type_id,
                "parameter_name": parameter_name,
                "input_port_name": input_port_name,
                "value_source": "input",
                "payload_path": ["value"],
                "reason": "value field is missing",
            },
        )
    return input_payload["value"]


def _validate_parameter_value(
    *,
    node_id: str,
    node_definition: NodeDefinition,
    parameter_name: str,
    input_port_name: str,
    parameter_schema: dict[str, object],
    parameter_value: object,
    value_source: str,
) -> None:
    """使用参数属性的 Draft 2020-12 schema 校验最终值。"""

    try:
        Draft202012Validator.check_schema(parameter_schema)
        validator = Draft202012Validator(parameter_schema)
        errors = sorted(
            validator.iter_errors(parameter_value),
            key=lambda item: (
                tuple(str(path_item) for path_item in item.absolute_path),
                tuple(str(path_item) for path_item in item.absolute_schema_path),
            ),
        )
    except SchemaError as exc:
        raise ServiceConfigurationError(
            "节点动态参数属性 schema 配置无效",
            details={
                "node_id": node_id,
                "node_type_id": node_definition.node_type_id,
                "parameter_name": parameter_name,
                "input_port_name": input_port_name,
                "schema_path": ["properties", parameter_name],
                "reason": exc.message,
            },
        ) from exc
    if not errors:
        return
    error: ValidationError = errors[0]
    raise InvalidRequestError(
        "节点动态参数不符合参数 schema",
        details={
            "node_id": node_id,
            "node_type_id": node_definition.node_type_id,
            "parameter_name": parameter_name,
            "input_port_name": input_port_name,
            "value_source": value_source,
            "payload_path": [str(item) for item in error.absolute_path],
            "schema_path": [str(item) for item in error.absolute_schema_path],
            "reason": error.message,
        },
    )
