"""Workflow 字符串、标量和日期时间节点测试。"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.contracts.workflows.workflow_graph import (
    NODE_CONCURRENCY_THREAD_SAFE,
    WorkflowGraphEdge,
    WorkflowGraphInput,
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


def _build_executor(
    tmp_path: Path,
) -> tuple[WorkflowGraphExecutor, NodeCatalogRegistry]:
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


def test_string_processing_nodes_publish_explicit_value_contracts(
    tmp_path: Path,
) -> None:
    """验证三个新节点只通过明确的 value.v1 端口组合。"""

    _, catalog_registry = _build_executor(tmp_path)
    definitions = {
        item.node_type_id: item
        for item in catalog_registry.get_workflow_node_definitions()
    }

    concat = definitions["core.logic.string-concat"]
    assert [(port.name, port.payload_type_id) for port in concat.input_ports] == [
        ("left", "value.v1"),
        ("right", "value.v1"),
    ]
    assert concat.concurrency_policy == NODE_CONCURRENCY_THREAD_SAFE

    scalar = definitions["core.logic.scalar-to-string"]
    assert [(port.name, port.payload_type_id) for port in scalar.input_ports] == [
        ("value", "value.v1")
    ]
    assert scalar.concurrency_policy == NODE_CONCURRENCY_THREAD_SAFE

    date_time = definitions["core.logic.format-date-time"]
    assert [(port.name, port.required) for port in date_time.input_ports] == [
        ("template", False)
    ]
    assert [
        (binding.parameter_name, binding.input_port_name)
        for binding in date_time.parameter_input_bindings
    ] == [("template", "template")]


def test_request_text_can_build_save_image_file_name_without_hidden_formatting(
    tmp_path: Path,
) -> None:
    """验证 request_text 可以与日期模板文本直接拼接且保留大括号。"""

    executor, _ = _build_executor(tmp_path)
    template = WorkflowGraphTemplate(
        template_id="request-text-file-name-template",
        template_version="1.0.0",
        display_name="Request Text File Name Template",
        nodes=(
            WorkflowGraphNode(
                node_id="text_input",
                node_type_id="core.io.template-input.text",
            ),
            WorkflowGraphNode(
                node_id="text_to_value",
                node_type_id="core.logic.text-to-value",
            ),
            WorkflowGraphNode(
                node_id="suffix",
                node_type_id="core.logic.string-value",
                parameters={"value": "-{YYYYMMDDhhmmss}.jpg"},
            ),
            WorkflowGraphNode(
                node_id="concat",
                node_type_id="core.logic.string-concat",
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="input-to-value",
                source_node_id="text_input",
                source_port="text",
                target_node_id="text_to_value",
                target_port="text",
            ),
            WorkflowGraphEdge(
                edge_id="value-to-left",
                source_node_id="text_to_value",
                source_port="value",
                target_node_id="concat",
                target_port="left",
            ),
            WorkflowGraphEdge(
                edge_id="suffix-to-right",
                source_node_id="suffix",
                source_port="value",
                target_node_id="concat",
                target_port="right",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_text",
                display_name="Request Text",
                payload_type_id="text.v1",
                target_node_id="text_input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="file_name",
                display_name="File Name",
                payload_type_id="value.v1",
                source_node_id="concat",
                source_port="value",
            ),
        ),
    )

    result = executor.execute(
        template=template,
        input_values={
            "request_text": {
                "text": "lot-3570",
                "media_type": "text/plain",
                "charset": "utf-8",
            }
        },
    )

    assert result.outputs["file_name"] == {
        "value": "lot-3570-{YYYYMMDDhhmmss}.jpg"
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("station", "station"),
        (3570, "3570"),
        (2.5, "2.5"),
        (True, "true"),
        (False, "false"),
    ),
)
def test_scalar_to_string_uses_stable_explicit_representations(
    tmp_path: Path,
    value: object,
    expected: str,
) -> None:
    """验证 JSON 标量转换不依赖 Python 对象调试字符串。"""

    executor, _ = _build_executor(tmp_path)
    template = _build_scalar_template()

    result = executor.execute(
        template=template,
        input_values={"request_value": {"value": value}},
    )

    assert result.outputs["string"] == {"value": expected}


@pytest.mark.parametrize(
    "value",
    (None, {"station": 2}, [1, 2], float("nan"), float("inf"), float("-inf")),
)
def test_scalar_to_string_rejects_non_scalar_or_null_values(
    tmp_path: Path,
    value: object,
) -> None:
    """验证 null、对象和数组必须走其他显式转换节点。"""

    executor, _ = _build_executor(tmp_path)

    with pytest.raises(InvalidRequestError):
        executor.execute(
            template=_build_scalar_template(),
            input_values={"request_value": {"value": value}},
        )


def test_format_date_time_supports_static_and_dynamic_templates(
    tmp_path: Path,
) -> None:
    """验证日期节点固定参数和动态参数端口使用同一公共解析器。"""

    executor, _ = _build_executor(tmp_path)
    static_result = executor.execute(
        template=WorkflowGraphTemplate(
            template_id="static-date-time-template",
            template_version="1.0.0",
            display_name="Static Date Time Template",
            nodes=(
                WorkflowGraphNode(
                    node_id="date_time",
                    node_type_id="core.logic.format-date-time",
                    parameters={"template": "prefix-{YYYY}-{MM}-{DD}-{hh}{mm}{ss}{SSS}"},
                ),
            ),
            template_outputs=(
                WorkflowGraphOutput(
                    output_id="value",
                    display_name="Value",
                    payload_type_id="value.v1",
                    source_node_id="date_time",
                    source_port="value",
                ),
            ),
        ),
        input_values={},
    )
    assert re.fullmatch(
        r"prefix-\d{4}-\d{2}-\d{2}-\d{9}",
        str(static_result.outputs["value"]["value"]),
    )

    dynamic_result = executor.execute(
        template=WorkflowGraphTemplate(
            template_id="dynamic-date-time-template",
            template_version="1.0.0",
            display_name="Dynamic Date Time Template",
            nodes=(
                WorkflowGraphNode(
                    node_id="template_value",
                    node_type_id="core.logic.string-value",
                    parameters={"value": "{YY}/{M}/{D}"},
                ),
                WorkflowGraphNode(
                    node_id="date_time",
                    node_type_id="core.logic.format-date-time",
                    parameters={"template": "fallback"},
                ),
            ),
            edges=(
                WorkflowGraphEdge(
                    edge_id="dynamic-template",
                    source_node_id="template_value",
                    source_port="value",
                    target_node_id="date_time",
                    target_port="template",
                ),
            ),
            template_outputs=(
                WorkflowGraphOutput(
                    output_id="value",
                    display_name="Value",
                    payload_type_id="value.v1",
                    source_node_id="date_time",
                    source_port="value",
                ),
            ),
        ),
        input_values={},
    )
    assert re.fullmatch(
        r"\d{2}/\d{1,2}/\d{1,2}",
        str(dynamic_result.outputs["value"]["value"]),
    )


def test_concat_strings_rejects_implicit_number_conversion(tmp_path: Path) -> None:
    """验证字符串拼接不会把数字静默转换为文本。"""

    executor, _ = _build_executor(tmp_path)
    template = WorkflowGraphTemplate(
        template_id="invalid-concat-template",
        template_version="1.0.0",
        display_name="Invalid Concat Template",
        nodes=(
            WorkflowGraphNode(
                node_id="left",
                node_type_id="core.logic.number-value",
                parameters={"value": 3570},
            ),
            WorkflowGraphNode(
                node_id="right",
                node_type_id="core.logic.string-value",
                parameters={"value": ".jpg"},
            ),
            WorkflowGraphNode(
                node_id="concat",
                node_type_id="core.logic.string-concat",
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="left-edge",
                source_node_id="left",
                source_port="value",
                target_node_id="concat",
                target_port="left",
            ),
            WorkflowGraphEdge(
                edge_id="right-edge",
                source_node_id="right",
                source_port="value",
                target_node_id="concat",
                target_port="right",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="value",
                display_name="Value",
                payload_type_id="value.v1",
                source_node_id="concat",
                source_port="value",
            ),
        ),
    )

    with pytest.raises(InvalidRequestError):
        executor.execute(template=template, input_values={})


def test_request_json_supports_dynamic_path_and_dynamic_format_template(
    tmp_path: Path,
) -> None:
    """验证 request_json 可以驱动路径提取并作为命名格式对象使用。"""

    executor, _ = _build_executor(tmp_path)
    template = WorkflowGraphTemplate(
        template_id="request-json-processing-template",
        template_version="1.0.0",
        display_name="Request JSON Processing Template",
        nodes=(
            WorkflowGraphNode(
                node_id="json_input",
                node_type_id="core.io.template-input.object",
            ),
            WorkflowGraphNode(
                node_id="path",
                node_type_id="core.logic.string-value",
                parameters={"value": "station.id"},
            ),
            WorkflowGraphNode(
                node_id="extract",
                node_type_id="core.logic.value-field-extract",
                parameters={"path": "fallback"},
            ),
            WorkflowGraphNode(
                node_id="scalar",
                node_type_id="core.logic.scalar-to-string",
            ),
            WorkflowGraphNode(
                node_id="template",
                node_type_id="core.logic.string-value",
                parameters={"value": "{recipe}-{{YYYYMMDD}}.jpg"},
            ),
            WorkflowGraphNode(
                node_id="format",
                node_type_id="core.logic.format-string",
                parameters={"template": "fallback"},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="json-to-extract",
                source_node_id="json_input",
                source_port="value",
                target_node_id="extract",
                target_port="value",
            ),
            WorkflowGraphEdge(
                edge_id="path-to-extract",
                source_node_id="path",
                source_port="value",
                target_node_id="extract",
                target_port="path",
            ),
            WorkflowGraphEdge(
                edge_id="extract-to-scalar",
                source_node_id="extract",
                source_port="value",
                target_node_id="scalar",
                target_port="value",
            ),
            WorkflowGraphEdge(
                edge_id="json-to-format",
                source_node_id="json_input",
                source_port="value",
                target_node_id="format",
                target_port="values",
            ),
            WorkflowGraphEdge(
                edge_id="template-to-format",
                source_node_id="template",
                source_port="value",
                target_node_id="format",
                target_port="template",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_json",
                display_name="Request JSON",
                payload_type_id="value.v1",
                target_node_id="json_input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="station",
                display_name="Station",
                payload_type_id="value.v1",
                source_node_id="scalar",
                source_port="value",
            ),
            WorkflowGraphOutput(
                output_id="formatted",
                display_name="Formatted",
                payload_type_id="value.v1",
                source_node_id="format",
                source_port="value",
            ),
        ),
    )

    result = executor.execute(
        template=template,
        input_values={
            "request_json": {
                "value": {
                    "recipe": "3570",
                    "station": {"id": 2},
                }
            }
        },
    )

    assert result.outputs["station"] == {"value": "2"}
    assert result.outputs["formatted"] == {"value": "3570-{YYYYMMDD}.jpg"}


def _build_scalar_template() -> WorkflowGraphTemplate:
    """构造任意 value 输入到 Scalar To String 的最小模板。"""

    return WorkflowGraphTemplate(
        template_id="scalar-to-string-template",
        template_version="1.0.0",
        display_name="Scalar To String Template",
        nodes=(
            WorkflowGraphNode(
                node_id="input",
                node_type_id="core.io.template-input.value",
            ),
            WorkflowGraphNode(
                node_id="scalar",
                node_type_id="core.logic.scalar-to-string",
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="input-to-scalar",
                source_node_id="input",
                source_port="value",
                target_node_id="scalar",
                target_port="value",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_value",
                display_name="Request Value",
                payload_type_id="value.v1",
                target_node_id="input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="string",
                display_name="String",
                payload_type_id="value.v1",
                source_node_id="scalar",
                source_port="value",
            ),
        ),
    )
