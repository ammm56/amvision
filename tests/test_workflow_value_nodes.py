"""通用 String、Number、Boolean Value 节点测试。"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)


def _build_executor(tmp_path: Path) -> tuple[WorkflowGraphExecutor, NodeCatalogRegistry]:
    """构建只加载正式 Core Node 的隔离执行器。"""

    node_pack_loader = LocalNodePackLoader(tmp_path / "custom_nodes")
    node_pack_loader.refresh()
    catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()
    return (
        WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry()),
        catalog_registry,
    )


def test_value_nodes_publish_clear_value_v1_contracts(tmp_path: Path) -> None:
    """验证三种基础节点无输入且只输出标准 value.v1。"""

    _, catalog_registry = _build_executor(tmp_path)
    definition_index = {
        item.node_type_id: item
        for item in catalog_registry.get_workflow_node_definitions()
    }

    for node_type_id, schema_type, default_value in (
        ("core.logic.string-value", "string", ""),
        ("core.logic.number-value", "number", 0),
        ("core.logic.boolean-value", "boolean", False),
    ):
        definition = definition_index[node_type_id]
        assert definition.input_ports == ()
        assert tuple(port.payload_type_id for port in definition.output_ports) == (
            "value.v1",
        )
        value_schema = definition.parameter_schema["properties"]["value"]
        assert value_schema["type"] == schema_type
        assert value_schema["default"] == default_value


def test_value_nodes_execute_as_independent_general_sources(tmp_path: Path) -> None:
    """验证三种节点在同一图中独立执行并保持值类型。"""

    executor, _ = _build_executor(tmp_path)
    template = WorkflowGraphTemplate(
        template_id="primitive-value-source-template",
        template_version="1.0.0",
        display_name="Primitive Value Source Template",
        nodes=(
            WorkflowGraphNode(
                node_id="string_value",
                node_type_id="core.logic.string-value",
                parameters={"value": "lot-20260901"},
            ),
            WorkflowGraphNode(
                node_id="number_value",
                node_type_id="core.logic.number-value",
                parameters={"value": 3570.5},
            ),
            WorkflowGraphNode(
                node_id="boolean_value",
                node_type_id="core.logic.boolean-value",
                parameters={"value": True},
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="string",
                display_name="String",
                payload_type_id="value.v1",
                source_node_id="string_value",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="number",
                display_name="Number",
                payload_type_id="value.v1",
                source_node_id="number_value",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="boolean",
                display_name="Boolean",
                payload_type_id="value.v1",
                source_node_id="boolean_value",
                source_port="value",
            ),
        ),
    )

    result = executor.execute(template=template, input_values={})

    assert result.outputs == {
        "string": {"value": "lot-20260901"},
        "number": {"value": 3570.5},
        "boolean": {"value": True},
    }


@pytest.mark.parametrize(
    ("node_type_id", "invalid_value"),
    (
        ("core.logic.string-value", 1),
        ("core.logic.number-value", math.inf),
        ("core.logic.boolean-value", "true"),
    ),
)
def test_value_nodes_reject_implicit_type_conversion(
    tmp_path: Path,
    node_type_id: str,
    invalid_value: object,
) -> None:
    """验证基础节点不猜测或隐式转换输入类型。"""

    executor, _ = _build_executor(tmp_path)
    template = WorkflowGraphTemplate(
        template_id="invalid-primitive-value-template",
        template_version="1.0.0",
        display_name="Invalid Primitive Value Template",
        nodes=(
            WorkflowGraphNode(
                node_id="value",
                node_type_id=node_type_id,
                parameters={"value": invalid_value},
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="value",
                display_name="Value",
                payload_type_id="value.v1",
                source_node_id="value",
                source_port="value",
            ),
        ),
    )

    with pytest.raises(InvalidRequestError):
        executor.execute(template=template, input_values={})
