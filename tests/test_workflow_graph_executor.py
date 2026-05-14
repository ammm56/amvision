"""workflow 图执行器测试。"""

from __future__ import annotations

import pytest

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NODE_RUNTIME_WORKER_TASK,
    NodeDefinition,
    NodePortDefinition,
    WorkflowGraphEdge,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeExecutionRequest,
    WorkflowNodeRuntimeRegistry,
)


def test_workflow_graph_executor_runs_python_callable_and_worker_task_nodes() -> None:
    """验证最小图执行器可以按拓扑顺序执行 python-callable 与 worker-task 节点。"""

    normalize_node = NodeDefinition(
        node_type_id="core.text.normalize",
        display_name="Normalize Text",
        category="utility.text",
        description="去除输入文本两端空白。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="text",
                display_name="Text",
                payload_type_id="text.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="text",
                display_name="Text",
                payload_type_id="text.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
    )
    uppercase_node = NodeDefinition(
        node_type_id="core.text.uppercase-worker",
        display_name="Uppercase Worker",
        category="worker.text",
        description="模拟通过 worker-task 把文本转换为大写。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_WORKER_TASK,
        input_ports=(
            NodePortDefinition(
                name="text",
                display_name="Text",
                payload_type_id="text.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="text.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
    )
    template = WorkflowGraphTemplate(
        template_id="text-pipeline",
        template_version="1.0.0",
        display_name="Text Pipeline",
        nodes=(
            WorkflowGraphNode(node_id="normalize", node_type_id="core.text.normalize"),
            WorkflowGraphNode(node_id="uppercase", node_type_id="core.text.uppercase-worker"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-normalize-uppercase",
                source_node_id="normalize",
                source_port="text",
                target_node_id="uppercase",
                target_port="text",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="source_text",
                display_name="Source Text",
                payload_type_id="text.v1",
                target_node_id="normalize",
                target_port="text",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="final_text",
                display_name="Final Text",
                payload_type_id="text.v1",
                source_node_id="uppercase",
                source_port="result",
            ),
        ),
    )

    registry = WorkflowNodeRuntimeRegistry()
    registry.register_python_callable(normalize_node, _normalize_text_handler)
    registry.register_worker_task(uppercase_node, _uppercase_text_worker)
    executor = WorkflowGraphExecutor(registry=registry)

    execution_result = executor.execute(
        template=template,
        input_values={"source_text": {"value": "  hello workflow  "}},
        execution_metadata={"request_id": "req-1"},
    )

    assert execution_result.outputs["final_text"]["value"] == "HELLO WORKFLOW"
    assert [record.node_id for record in execution_result.node_records] == ["normalize", "uppercase"]
    assert execution_result.node_records[1].runtime_kind == "worker-task"


def test_workflow_graph_executor_requires_registered_handler() -> None:
    """验证缺少处理函数时图执行器会返回明确配置错误。"""

    worker_node = NodeDefinition(
        node_type_id="core.text.worker-only",
        display_name="Worker Only",
        category="worker.text",
        description="仅用于验证缺少 handler 的错误路径。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_WORKER_TASK,
        input_ports=(
            NodePortDefinition(
                name="text",
                display_name="Text",
                payload_type_id="text.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="text.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
    )
    template = WorkflowGraphTemplate(
        template_id="missing-handler-template",
        template_version="1.0.0",
        display_name="Missing Handler Template",
        nodes=(WorkflowGraphNode(node_id="worker", node_type_id="core.text.worker-only"),),
        template_inputs=(
            WorkflowGraphInput(
                input_id="source_text",
                display_name="Source Text",
                payload_type_id="text.v1",
                target_node_id="worker",
                target_port="text",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="final_text",
                display_name="Final Text",
                payload_type_id="text.v1",
                source_node_id="worker",
                source_port="result",
            ),
        ),
    )

    registry = WorkflowNodeRuntimeRegistry()
    registry.register_node_definition(worker_node)
    executor = WorkflowGraphExecutor(registry=registry)

    with pytest.raises(ServiceConfigurationError, match="worker-task"):
        executor.execute(
            template=template,
            input_values={"source_text": {"value": "test"}},
        )


def test_workflow_graph_executor_reports_failed_node_details() -> None:
    """验证节点执行异常时会返回可定位的失败节点细节。"""

    failing_node = NodeDefinition(
        node_type_id="core.test.raise-assertion",
        display_name="Raise Assertion",
        category="test.failure",
        description="用于验证节点失败定位信息。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="text",
                display_name="Text",
                payload_type_id="text.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="text.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
    )
    template = WorkflowGraphTemplate(
        template_id="failing-node-template",
        template_version="1.0.0",
        display_name="Failing Node Template",
        nodes=(
            WorkflowGraphNode(
                node_id="explode",
                node_type_id="core.test.raise-assertion",
                metadata={"sequence_index": 3},
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="source_text",
                display_name="Source Text",
                payload_type_id="text.v1",
                target_node_id="explode",
                target_port="text",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="final_text",
                display_name="Final Text",
                payload_type_id="text.v1",
                source_node_id="explode",
                source_port="result",
            ),
        ),
    )

    registry = WorkflowNodeRuntimeRegistry()
    registry.register_python_callable(failing_node, _raise_assertion_handler)
    executor = WorkflowGraphExecutor(registry=registry)

    with pytest.raises(ServiceConfigurationError) as caught_error:
        executor.execute(
            template=template,
            input_values={"source_text": {"value": "test"}},
        )

    assert str(caught_error.value) == "workflow 节点执行失败"
    assert caught_error.value.details["node_id"] == "explode"
    assert caught_error.value.details["node_type_id"] == "core.test.raise-assertion"
    assert caught_error.value.details["runtime_kind"] == "python-callable"
    assert caught_error.value.details["execution_index"] == 1
    assert caught_error.value.details["sequence_index"] == 3
    assert caught_error.value.details["error_type"] == "AssertionError"
    assert caught_error.value.details["error_message"] == "boom"


def _normalize_text_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """去除输入文本两端空白。"""

    raw_payload = request.input_values["text"]
    raw_text = str(raw_payload.get("value") or "") if isinstance(raw_payload, dict) else str(raw_payload)
    return {"text": {"value": raw_text.strip()}}


def _uppercase_text_worker(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """模拟 worker-task 处理函数，把文本转换为大写。"""

    raw_payload = request.input_values["text"]
    raw_text = str(raw_payload.get("value") or "") if isinstance(raw_payload, dict) else str(raw_payload)
    return {"result": {"value": raw_text.upper()}}


def _raise_assertion_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """用于验证节点失败定位的测试处理函数。"""

    raise AssertionError("boom")