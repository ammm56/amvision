"""Workflow 节点动态参数输入测试。"""

from __future__ import annotations

import pytest

from backend.contracts.workflows.workflow_graph import (
    NODE_CONCURRENCY_SERIALIZED,
    NODE_CONCURRENCY_THREAD_SAFE,
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodeParameterInputBinding,
    NodePortDefinition,
    WorkflowGraphEdge,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.nodes.core_nodes.logic.control.for_each_end import (
    CORE_NODE_SPEC as FOR_EACH_END_NODE_SPEC,
)
from backend.nodes.core_nodes.logic.control.for_each_start import (
    CORE_NODE_SPEC as FOR_EACH_START_NODE_SPEC,
)
from backend.nodes.core_nodes.logic.control.parallel_end import (
    CORE_NODE_SPEC as PARALLEL_END_NODE_SPEC,
)
from backend.nodes.core_nodes.logic.control.parallel_start import (
    CORE_NODE_SPEC as PARALLEL_START_NODE_SPEC,
)
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.workflows.execution.parameters import (
    resolve_node_parameters,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeExecutionRequest,
    WorkflowNodeRuntimeRegistry,
)


def _build_parameter_definition(
    *,
    parameter_schema: dict[str, object] | None = None,
    concurrency_policy: str = NODE_CONCURRENCY_SERIALIZED,
) -> NodeDefinition:
    """构造带动态 threshold 参数的测试节点。"""

    return NodeDefinition(
        node_type_id="core.test.dynamic-threshold",
        display_name="Dynamic Threshold",
        category="test",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        concurrency_policy=concurrency_policy,
        input_ports=(
            NodePortDefinition(
                name="threshold",
                display_name="Threshold",
                payload_type_id="value.v1",
                required=False,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema=parameter_schema
        or {
            "type": "object",
            "properties": {
                "threshold": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "default": 0.5,
                }
            },
        },
        parameter_input_bindings=(
            NodeParameterInputBinding(
                parameter_name="threshold",
                input_port_name="threshold",
            ),
        ),
    )


def test_dynamic_parameter_input_overrides_static_parameter() -> None:
    """验证连接输入优先于节点保存的固定参数。"""

    static_parameters = {"threshold": 0.25, "other": "kept"}

    resolved = resolve_node_parameters(
        node_id="target",
        node_definition=_build_parameter_definition(),
        static_parameters=static_parameters,
        input_values={"threshold": {"value": 0.75}},
    )

    assert resolved == {"threshold": 0.75, "other": "kept"}
    assert static_parameters == {"threshold": 0.25, "other": "kept"}


def test_dynamic_parameter_uses_static_value_then_schema_default() -> None:
    """验证未连接时依次使用固定参数和 schema default。"""

    definition = _build_parameter_definition()

    assert resolve_node_parameters(
        node_id="target",
        node_definition=definition,
        static_parameters={"threshold": 0.2},
        input_values={"threshold": None},
    )["threshold"] == 0.2
    assert resolve_node_parameters(
        node_id="target",
        node_definition=definition,
        static_parameters={},
        input_values={"threshold": None},
    )["threshold"] == 0.5


def test_connected_null_is_not_treated_as_missing_input() -> None:
    """验证 value=null 会按目标 schema 校验，而不是回退固定参数。"""

    with pytest.raises(InvalidRequestError) as error_info:
        resolve_node_parameters(
            node_id="target",
            node_definition=_build_parameter_definition(),
            static_parameters={"threshold": 0.2},
            input_values={"threshold": {"value": None}},
        )

    assert error_info.value.details["value_source"] == "input"
    assert error_info.value.details["parameter_name"] == "threshold"


def test_dynamic_parameter_reports_required_missing_and_invalid_payload() -> None:
    """验证必填缺失和错误 value.v1 结构具有明确错误上下文。"""

    definition = _build_parameter_definition(
        parameter_schema={
            "type": "object",
            "properties": {"threshold": {"type": "number"}},
            "required": ["threshold"],
        }
    )
    with pytest.raises(InvalidRequestError, match="缺少必需") as missing_error:
        resolve_node_parameters(
            node_id="target",
            node_definition=definition,
            static_parameters={},
            input_values={"threshold": None},
        )
    assert missing_error.value.details["value_source"] == "missing"

    with pytest.raises(InvalidRequestError, match="value.v1") as payload_error:
        resolve_node_parameters(
            node_id="target",
            node_definition=definition,
            static_parameters={},
            input_values={"threshold": {"wrong": 0.5}},
        )
    assert payload_error.value.details["payload_path"] == ["value"]


@pytest.mark.parametrize("value", (-0.1, 1.1, "0.5", True))
def test_dynamic_parameter_rejects_values_outside_property_schema(value: object) -> None:
    """验证动态值完整遵守目标参数属性 schema。"""

    with pytest.raises(InvalidRequestError) as error_info:
        resolve_node_parameters(
            node_id="target",
            node_definition=_build_parameter_definition(),
            static_parameters={},
            input_values={"threshold": {"value": value}},
        )

    assert error_info.value.details["parameter_name"] == "threshold"
    assert error_info.value.details["value_source"] == "input"
    assert error_info.value.details["schema_path"]


def test_dynamic_parameter_rejects_invalid_property_schema() -> None:
    """验证无效属性 schema 被识别为节点配置错误。"""

    definition = _build_parameter_definition(
        parameter_schema={
            "type": "object",
            "properties": {"threshold": {"type": "unknown-json-type"}},
        }
    )

    with pytest.raises(ServiceConfigurationError, match="schema 配置无效"):
        resolve_node_parameters(
            node_id="target",
            node_definition=definition,
            static_parameters={"threshold": 0.5},
            input_values={"threshold": None},
        )


def test_graph_executor_passes_effective_parameters_to_handler() -> None:
    """验证 Graph Executor 在统一 handler 入口完成参数覆盖。"""

    source_definition = NodeDefinition(
        node_type_id="core.test.parameter-source",
        display_name="Parameter Source",
        category="test",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        output_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
    )
    target_definition = _build_parameter_definition()
    observed_requests: list[WorkflowNodeExecutionRequest] = []
    registry = WorkflowNodeRuntimeRegistry()
    registry.register_python_callable(
        source_definition,
        lambda request: {"value": {"value": 0.8}},
    )

    def target_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
        observed_requests.append(request)
        return {"result": {"value": request.parameters["threshold"]}}

    registry.register_python_callable(target_definition, target_handler)
    template = WorkflowGraphTemplate(
        template_id="dynamic-parameter-graph",
        template_version="1.0.0",
        display_name="Dynamic Parameter Graph",
        nodes=(
            WorkflowGraphNode(
                node_id="source",
                node_type_id=source_definition.node_type_id,
            ),
            WorkflowGraphNode(
                node_id="target",
                node_type_id=target_definition.node_type_id,
                parameters={"threshold": 0.2},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="source-to-threshold",
                source_node_id="source",
                source_port="value",
                target_node_id="target",
                target_port="threshold",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="result",
                display_name="Result",
                payload_type_id="value.v1",
                source_node_id="target",
                source_port="result",
            ),
        ),
    )

    result = WorkflowGraphExecutor(registry=registry).execute(
        template=template,
        input_values={},
    )

    assert result.outputs["result"] == {"value": 0.8}
    assert observed_requests[0].parameters["threshold"] == 0.8
    assert observed_requests[0].input_values["threshold"] == {"value": 0.8}


def test_parallel_branches_resolve_their_dynamic_parameters() -> None:
    """验证 Parallel 子图通过统一 handler 入口解析动态参数。"""

    target_definition = _build_parameter_definition(
        concurrency_policy=NODE_CONCURRENCY_THREAD_SAFE,
    )
    registry = WorkflowNodeRuntimeRegistry()
    for spec in (PARALLEL_START_NODE_SPEC, PARALLEL_END_NODE_SPEC):
        registry.register_python_callable(spec.node_definition, spec.handler)
    observed_parameters: list[float] = []

    def target_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
        value = float(request.parameters["threshold"])
        observed_parameters.append(value)
        return {"result": {"value": value}}

    registry.register_python_callable(target_definition, target_handler)
    template = WorkflowGraphTemplate(
        template_id="parallel-dynamic-parameters",
        template_version="1.0.0",
        display_name="Parallel Dynamic Parameters",
        nodes=(
            WorkflowGraphNode(
                node_id="parallel_start",
                node_type_id=PARALLEL_START_NODE_SPEC.node_definition.node_type_id,
                parameters={"max_concurrency": 2},
            ),
            WorkflowGraphNode(
                node_id="branch_1",
                node_type_id=target_definition.node_type_id,
                parameters={"threshold": 0.1},
            ),
            WorkflowGraphNode(
                node_id="branch_2",
                node_type_id=target_definition.node_type_id,
                parameters={"threshold": 0.2},
            ),
            WorkflowGraphNode(
                node_id="parallel_end",
                node_type_id=PARALLEL_END_NODE_SPEC.node_definition.node_type_id,
                parameters={"mode": "collect"},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="start-to-branch-1",
                source_node_id="parallel_start",
                source_port="value",
                target_node_id="branch_1",
                target_port="threshold",
            ),
            WorkflowGraphEdge(
                edge_id="start-to-branch-2",
                source_node_id="parallel_start",
                source_port="value",
                target_node_id="branch_2",
                target_port="threshold",
            ),
            WorkflowGraphEdge(
                edge_id="branch-1-to-end",
                source_node_id="branch_1",
                source_port="result",
                target_node_id="parallel_end",
                target_port="results",
            ),
            WorkflowGraphEdge(
                edge_id="branch-2-to-end",
                source_node_id="branch_2",
                source_port="result",
                target_node_id="parallel_end",
                target_port="results",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="threshold",
                display_name="Threshold",
                payload_type_id="value.v1",
                target_node_id="parallel_start",
                target_port="value",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="results",
                display_name="Results",
                payload_type_id="value.v1",
                source_node_id="parallel_end",
                source_port="results",
            ),
        ),
    )

    result = WorkflowGraphExecutor(registry=registry).execute(
        template=template,
        input_values={"threshold": {"value": 0.7}},
    )

    assert result.outputs["results"] == {"value": [0.7, 0.7]}
    assert sorted(observed_parameters) == [0.7, 0.7]


def test_for_each_resolves_dynamic_parameter_for_each_item() -> None:
    """验证 ForEach 每轮使用当前 item 解析目标节点参数。"""

    target_definition = _build_parameter_definition()
    registry = WorkflowNodeRuntimeRegistry()
    for spec in (FOR_EACH_START_NODE_SPEC, FOR_EACH_END_NODE_SPEC):
        registry.register_python_callable(spec.node_definition, spec.handler)
    observed_parameters: list[float] = []

    def target_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
        value = float(request.parameters["threshold"])
        observed_parameters.append(value)
        return {"result": {"value": value}}

    registry.register_python_callable(target_definition, target_handler)
    template = WorkflowGraphTemplate(
        template_id="for-each-dynamic-parameters",
        template_version="1.0.0",
        display_name="For Each Dynamic Parameters",
        nodes=(
            WorkflowGraphNode(
                node_id="for_each_start",
                node_type_id=FOR_EACH_START_NODE_SPEC.node_definition.node_type_id,
            ),
            WorkflowGraphNode(
                node_id="target",
                node_type_id=target_definition.node_type_id,
                parameters={"threshold": 0.1},
            ),
            WorkflowGraphNode(
                node_id="for_each_end",
                node_type_id=FOR_EACH_END_NODE_SPEC.node_definition.node_type_id,
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="item-to-threshold",
                source_node_id="for_each_start",
                source_port="item",
                target_node_id="target",
                target_port="threshold",
            ),
            WorkflowGraphEdge(
                edge_id="target-to-end",
                source_node_id="target",
                source_port="result",
                target_node_id="for_each_end",
                target_port="result",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="items",
                display_name="Items",
                payload_type_id="value.v1",
                target_node_id="for_each_start",
                target_port="items",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="results",
                display_name="Results",
                payload_type_id="value.v1",
                source_node_id="for_each_end",
                source_port="results",
            ),
        ),
    )

    result = WorkflowGraphExecutor(registry=registry).execute(
        template=template,
        input_values={"items": {"value": [0.2, 0.4, 0.6]}},
    )

    assert result.outputs["results"] == {"value": [0.2, 0.4, 0.6]}
    assert observed_parameters == [0.2, 0.4, 0.6]
