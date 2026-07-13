"""workflow 图执行输入解析辅助函数。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import NodeDefinition, WorkflowGraphTemplate
from backend.service.application.errors import InvalidRequestError


def validate_template_inputs(
    *,
    template: WorkflowGraphTemplate,
    input_values: dict[str, object],
) -> None:
    """校验图执行时提供的模板输入集合。"""

    template_input_ids = {item.input_id for item in template.template_inputs}
    required_template_input_ids = {
        item.input_id for item in template.template_inputs if item.required
    }
    provided_input_ids = set(input_values.keys())
    missing_input_ids = sorted(required_template_input_ids - provided_input_ids)
    if missing_input_ids:
        raise InvalidRequestError(
            "图执行缺少必需的模板输入",
            details={"missing_input_ids": missing_input_ids},
        )
    unexpected_input_ids = sorted(provided_input_ids - template_input_ids)
    if unexpected_input_ids:
        raise InvalidRequestError(
            "图执行提供了未声明的模板输入",
            details={"unexpected_input_ids": unexpected_input_ids},
        )


def build_template_input_bindings(
    *,
    template: WorkflowGraphTemplate,
) -> dict[tuple[str, str], list[str]]:
    """构建模板输入到节点输入端口的绑定索引。"""

    bindings: dict[tuple[str, str], list[str]] = {}
    for item in template.template_inputs:
        bindings.setdefault((item.target_node_id, item.target_port), []).append(item.input_id)
    return bindings


def build_edge_bindings(
    *,
    template: WorkflowGraphTemplate,
) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """构建节点输出到节点输入端口的连接索引。"""

    enabled_node_ids = {
        node.node_id
        for node in template.nodes
        if node.enabled is not False
    }
    bindings: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for edge in template.edges:
        if edge.source_node_id not in enabled_node_ids or edge.target_node_id not in enabled_node_ids:
            continue
        bindings.setdefault((edge.target_node_id, edge.target_port), []).append(
            (edge.source_node_id, edge.source_port)
        )
    return bindings


def resolve_node_inputs(
    *,
    node_id: str,
    node_definition: NodeDefinition,
    input_values: dict[str, object],
    template_input_bindings: dict[tuple[str, str], list[str]],
    edge_bindings: dict[tuple[str, str], list[tuple[str, str]]],
    node_output_values: dict[tuple[str, str], object],
) -> dict[str, object]:
    """解析单个节点在当前执行轮次可见的输入值。"""

    resolved_inputs: dict[str, object] = {}
    for port in node_definition.input_ports:
        binding_key = (node_id, port.name)
        resolved_values: list[object] = []
        for template_input_id in template_input_bindings.get(binding_key, []):
            if template_input_id in input_values:
                resolved_values.append(input_values[template_input_id])
        for source_node_id, source_port in edge_bindings.get(binding_key, []):
            source_key = (source_node_id, source_port)
            if source_key not in node_output_values:
                raise InvalidRequestError(
                    "当前节点依赖的上游输出尚未产出",
                    details={
                        "node_id": node_id,
                        "port_name": port.name,
                        "source_node_id": source_node_id,
                        "source_port": source_port,
                    },
                )
            resolved_values.append(node_output_values[source_key])

        if not resolved_values:
            if port.required:
                raise InvalidRequestError(
                    "当前节点缺少必需输入端口",
                    details={"node_id": node_id, "port_name": port.name},
                )
            resolved_inputs[port.name] = () if port.multiple else None
            continue

        resolved_inputs[port.name] = tuple(resolved_values) if port.multiple else resolved_values[0]

    return resolved_inputs
