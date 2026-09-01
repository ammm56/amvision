"""workflow 确定性对象与列表结构节点测试。"""

from __future__ import annotations

import pytest

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphEdge,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.nodes.core_nodes import get_core_node_specs
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeRuntimeRegistry,
)


def test_object_and_list_builders_ignore_template_storage_order() -> None:
    """验证对象键和列表 index 显式绑定后，边与模板输入排列不影响结果。"""

    executor = _build_core_executor()
    template = _build_deterministic_structure_template()
    input_values = {
        "alpha": {"value": "A"},
        "beta": {"value": "B"},
        "list_zero": {"value": "zero"},
        "list_one": {"value": "one"},
    }

    expected_outputs: dict[str, object] | None = None
    for candidate in (
        template,
        template.model_copy(
            update={
                "edges": tuple(reversed(template.edges)),
                "template_inputs": tuple(reversed(template.template_inputs)),
            }
        ),
    ):
        result = executor.execute(
            template=candidate,
            input_values=input_values,
            execution_metadata={},
        )
        outputs = dict(result.outputs)
        if expected_outputs is None:
            expected_outputs = outputs
        assert outputs == expected_outputs

    assert expected_outputs == {
        "object": {"value": {"alpha": "A", "beta": "B", "source": "test"}},
        "list": {"value": ["zero", "one"]},
    }


def test_object_builder_rejects_duplicate_explicit_keys() -> None:
    """验证重复对象字段不会按输入先后静默覆盖。"""

    executor = _build_core_executor()
    template = _build_deterministic_structure_template(duplicate_object_key=True)

    with pytest.raises(InvalidRequestError) as exc_info:
        executor.execute(
            template=template,
            input_values={
                "alpha": {"value": "A"},
                "beta": {"value": "B"},
                "list_zero": {"value": "zero"},
                "list_one": {"value": "one"},
            },
            execution_metadata={},
        )

    assert exc_info.value.details["field_name"] == "alpha"


def test_object_field_rejects_key_whitespace_instead_of_silently_trimming() -> None:
    """验证字段名首尾空白明确失败，不暗中改写公开对象 key。"""

    source_template = _build_deterministic_structure_template()
    template = source_template.model_copy(
        update={
            "nodes": tuple(
                node.model_copy(update={"parameters": {"key": " alpha "}})
                if node.node_id == "alpha_field"
                else node
                for node in source_template.nodes
            )
        }
    )

    with pytest.raises(InvalidRequestError, match="首尾空白"):
        _build_core_executor().execute(
            template=template,
            input_values={
                "alpha": {"value": "A"},
                "beta": {"value": "B"},
                "list_zero": {"value": "zero"},
                "list_one": {"value": "one"},
            },
            execution_metadata={},
        )


def test_list_builder_rejects_duplicate_or_non_contiguous_indices() -> None:
    """验证显式列表 index 重复或不连续时确定性失败。"""

    executor = _build_core_executor()
    duplicate_template = _build_deterministic_structure_template(
        second_list_index=0,
    )
    missing_template = _build_deterministic_structure_template(
        second_list_index=2,
    )
    input_values = {
        "alpha": {"value": "A"},
        "beta": {"value": "B"},
        "list_zero": {"value": "zero"},
        "list_one": {"value": "one"},
    }

    with pytest.raises(InvalidRequestError, match="重复 index"):
        executor.execute(
            template=duplicate_template,
            input_values=input_values,
            execution_metadata={},
        )
    with pytest.raises(InvalidRequestError, match="从 0 开始且连续"):
        executor.execute(
            template=missing_template,
            input_values=input_values,
            execution_metadata={},
        )


def test_legacy_structure_nodes_are_explicitly_hidden_and_replaced() -> None:
    """验证旧位置语义节点只保留兼容执行信息，不会伪装成新节点。"""

    definition_index = {
        spec.node_definition.node_type_id: spec.node_definition
        for spec in get_core_node_specs()
    }
    expected_replacements = {
        "core.logic.object-create": "core.logic.object-build",
        "core.logic.object-update": "core.logic.object-set-path",
        "core.logic.object-merge": "core.logic.object-merge-pair",
        "core.logic.list-create": "core.logic.list-build",
    }

    for legacy_node_type_id, replacement_node_type_id in expected_replacements.items():
        definition = definition_index[legacy_node_type_id]
        assert definition.metadata["deprecated"] is True
        assert definition.metadata["palette_hidden"] is True
        assert definition.metadata["replacement_node_type_id"] == replacement_node_type_id
        assert replacement_node_type_id in definition_index


def test_legacy_object_create_remains_executable_for_published_snapshots() -> None:
    """验证隐藏旧节点仍能执行既有发布快照，而不是只保留 Catalog 占位。"""

    template = WorkflowGraphTemplate(
        template_id="legacy-object-create-template",
        template_version="1.0.0",
        display_name="Legacy Object Create Template",
        nodes=(
            WorkflowGraphNode(
                node_id="legacy_create",
                node_type_id="core.logic.object-create",
                parameters={"keys": ["left", "right"]},
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="left",
                display_name="Left",
                payload_type_id="value.v1",
                target_node_id="legacy_create",
                target_port="values",
            ),
            WorkflowGraphInput(
                input_id="right",
                display_name="Right",
                payload_type_id="value.v1",
                target_node_id="legacy_create",
                target_port="values",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="object",
                display_name="Object",
                payload_type_id="value.v1",
                source_node_id="legacy_create",
                source_port="value",
            ),
        ),
    )

    result = _build_core_executor().execute(
        template=template,
        input_values={"left": {"value": "L"}, "right": {"value": "R"}},
        execution_metadata={},
    )

    assert result.outputs == {"object": {"value": {"left": "L", "right": "R"}}}


def _build_core_executor() -> WorkflowGraphExecutor:
    """构造包含全部 core 节点的执行器。"""

    registry = WorkflowNodeRuntimeRegistry()
    for spec in get_core_node_specs():
        spec.register_handler(registry)
    return WorkflowGraphExecutor(registry=registry)


def _build_deterministic_structure_template(
    *,
    duplicate_object_key: bool = False,
    second_list_index: int = 1,
) -> WorkflowGraphTemplate:
    """构造显式字段和显式列表 index 的最小模板。"""

    return WorkflowGraphTemplate(
        template_id="deterministic-structure-template",
        template_version="1.0.0",
        display_name="Deterministic Structure Template",
        nodes=(
            WorkflowGraphNode(
                node_id="alpha_field",
                node_type_id="core.logic.object-field",
                parameters={"key": "alpha"},
            ),
            WorkflowGraphNode(
                node_id="beta_field",
                node_type_id="core.logic.object-field",
                parameters={"key": "alpha" if duplicate_object_key else "beta"},
            ),
            WorkflowGraphNode(
                node_id="build_object",
                node_type_id="core.logic.object-build",
                parameters={"fields": {"source": "test"}},
            ),
            WorkflowGraphNode(
                node_id="zero_item",
                node_type_id="core.logic.list-item",
                parameters={"index": 0},
            ),
            WorkflowGraphNode(
                node_id="one_item",
                node_type_id="core.logic.list-item",
                parameters={"index": second_list_index},
            ),
            WorkflowGraphNode(
                node_id="build_list",
                node_type_id="core.logic.list-build",
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="z-beta-field-object",
                source_node_id="beta_field",
                source_port="field",
                target_node_id="build_object",
                target_port="entries",
            ),
            WorkflowGraphEdge(
                edge_id="a-alpha-field-object",
                source_node_id="alpha_field",
                source_port="field",
                target_node_id="build_object",
                target_port="entries",
            ),
            WorkflowGraphEdge(
                edge_id="z-zero-item-list",
                source_node_id="zero_item",
                source_port="item",
                target_node_id="build_list",
                target_port="entries",
            ),
            WorkflowGraphEdge(
                edge_id="a-one-item-list",
                source_node_id="one_item",
                source_port="item",
                target_node_id="build_list",
                target_port="entries",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="beta",
                display_name="Beta",
                payload_type_id="value.v1",
                target_node_id="beta_field",
                target_port="value",
            ),
            WorkflowGraphInput(
                input_id="alpha",
                display_name="Alpha",
                payload_type_id="value.v1",
                target_node_id="alpha_field",
                target_port="value",
            ),
            WorkflowGraphInput(
                input_id="list_one",
                display_name="List One",
                payload_type_id="value.v1",
                target_node_id="one_item",
                target_port="value",
            ),
            WorkflowGraphInput(
                input_id="list_zero",
                display_name="List Zero",
                payload_type_id="value.v1",
                target_node_id="zero_item",
                target_port="value",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="object",
                display_name="Object",
                payload_type_id="value.v1",
                source_node_id="build_object",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="list",
                display_name="List",
                payload_type_id="value.v1",
                source_node_id="build_list",
                source_port="value",
            ),
        ),
    )
