"""workflow 图执行器测试。"""

from __future__ import annotations

from threading import Event
from time import sleep

import pytest

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_IMPLEMENTATION_CUSTOM,
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
from backend.service.application.errors import (
    InvalidRequestError,
    OperationTimeoutError,
    ServiceConfigurationError,
)
from backend.service.application.workflows.execution.node_pack_timeout import (
    NodePackExecutionTimeoutPolicy,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeExecutionRequest,
    WorkflowNodeRuntimeRegistry,
)


def test_node_pack_handler_receives_deadline_and_emits_lifecycle() -> None:
    """Node Pack 直接调用保持数据面不变，仅发送 started/ended 控制消息。"""

    definition, template = _build_custom_passthrough_graph()
    registry = WorkflowNodeRuntimeRegistry()
    cancellation_event = Event()
    requests: list[WorkflowNodeExecutionRequest] = []
    lifecycle: list[dict[str, object]] = []

    def handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
        requests.append(request)
        return {"result": request.input_values["value"]}

    registry.register_python_callable(definition, handler)
    result = WorkflowGraphExecutor(
        registry=registry,
        node_pack_timeout_policies={
            ("test-pack", "1.0.0"): NodePackExecutionTimeoutPolicy(
                default_seconds=10.0,
                kill_grace_seconds=2.0,
            )
        },
        node_cancellation_event=cancellation_event,
        node_lifecycle_callback=lifecycle.append,
    ).execute(
        template=template,
        input_values={"source": {"value": "ok"}},
        execution_metadata={"workflow_run_id": "run-1"},
    )

    assert result.outputs["output"] == {"value": "ok"}
    assert len(requests) == 1
    assert requests[0].node_cancellation_event is cancellation_event
    assert requests[0].node_deadline_monotonic is not None
    assert requests[0].node_invocation_id is not None
    assert len(requests[0].node_invocation_id or "") == 32
    assert [item["message_type"] for item in lifecycle] == [
        "node-started",
        "node-ended",
    ]
    assert lifecycle[0]["node_invocation_id"] == lifecycle[1]["node_invocation_id"]
    assert lifecycle[1]["outcome"] == "succeeded"


def test_optional_app_entry_fails_only_when_required_node_consumes_it() -> None:
    """optional 模板输入可不提交，但实际消费它的必需节点端口必须明确失败。"""

    definition = NodeDefinition(
        node_type_id="core.test.required-input",
        display_name="Required Input",
        category="test",
        description="验证 optional App Entry 与 required 节点端口的边界。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
                required=True,
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
    )
    template = WorkflowGraphTemplate(
        template_id="optional-entry-required-node",
        template_version="1.0.0",
        display_name="Optional Entry Required Node",
        nodes=(
            WorkflowGraphNode(
                node_id="required-node",
                node_type_id=definition.node_type_id,
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="optional_value",
                display_name="Optional Value",
                payload_type_id="value.v1",
                target_node_id="required-node",
                target_port="value",
                required=False,
            ),
        ),
    )
    registry = WorkflowNodeRuntimeRegistry()
    registry.register_python_callable(
        definition,
        lambda request: {"result": request.input_values["value"]},
    )

    with pytest.raises(InvalidRequestError) as error_info:
        WorkflowGraphExecutor(registry=registry).execute(
            template=template,
            input_values={},
        )

    assert error_info.value.details == {
        "node_id": "required-node",
        "port_name": "value",
    }


def test_preview_node_pack_timeout_is_reported_after_uncooperative_handler_returns() -> None:
    """可信 Preview handler 不被强杀，但返回后必须报告已超过 Node Pack deadline。"""

    definition, template = _build_custom_passthrough_graph()
    registry = WorkflowNodeRuntimeRegistry()

    def slow_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
        sleep(0.02)
        return {"result": request.input_values["value"]}

    registry.register_python_callable(definition, slow_handler)
    with pytest.raises(OperationTimeoutError):
        WorkflowGraphExecutor(
            registry=registry,
            node_pack_timeout_policies={
                ("test-pack", "1.0.0"): NodePackExecutionTimeoutPolicy(
                    default_seconds=0.001,
                    kill_grace_seconds=0.0,
                )
            },
        ).execute(
            template=template,
            input_values={"source": {"value": "late"}},
        )


def _build_custom_passthrough_graph() -> tuple[NodeDefinition, WorkflowGraphTemplate]:
    """构造单 Node Pack 节点图。"""

    definition = NodeDefinition(
        node_type_id="custom.test.passthrough",
        display_name="Custom Passthrough",
        category="test",
        description="Node Pack timeout 测试节点。",
        implementation_kind=NODE_IMPLEMENTATION_CUSTOM,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        node_pack_id="test-pack",
        node_pack_version="1.0.0",
        input_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
    )
    template = WorkflowGraphTemplate(
        template_id="custom-timeout-template",
        template_version="1.0.0",
        display_name="Custom Timeout",
        nodes=(
            WorkflowGraphNode(
                node_id="custom-node",
                node_type_id=definition.node_type_id,
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="source",
                display_name="Source",
                payload_type_id="value.v1",
                target_node_id="custom-node",
                target_port="value",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="output",
                display_name="Output",
                payload_type_id="value.v1",
                source_node_id="custom-node",
                source_port="result",
            ),
        ),
    )
    return definition, template


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
            WorkflowGraphNode(
                node_id="uppercase", node_type_id="core.text.uppercase-worker"
            ),
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
    assert [record.node_id for record in execution_result.node_records] == [
        "normalize",
        "uppercase",
    ]
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
        nodes=(
            WorkflowGraphNode(node_id="worker", node_type_id="core.text.worker-only"),
        ),
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


def test_workflow_graph_executor_ignores_edges_from_disabled_nodes() -> None:
    """验证禁用节点的输出连线不会让下游可选端口误报缺失。"""

    disabled_source_node = NodeDefinition(
        node_type_id="core.test.disabled-source",
        display_name="Disabled Source",
        category="test.execution",
        description="用于验证禁用节点输出不会参与输入解析。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(),
        output_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={"type": "object", "properties": {}},
    )
    target_node = NodeDefinition(
        node_type_id="core.test.optional-input-target",
        display_name="Optional Input Target",
        category="test.execution",
        description="用于验证可选端口在禁用上游时收到 None。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="required_value",
                display_name="Required Value",
                payload_type_id="value.v1",
            ),
            NodePortDefinition(
                name="optional_value",
                display_name="Optional Value",
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
        parameter_schema={"type": "object", "properties": {}},
    )
    template = WorkflowGraphTemplate(
        template_id="disabled-edge-template",
        template_version="1.0.0",
        display_name="Disabled Edge Template",
        nodes=(
            WorkflowGraphNode(
                node_id="disabled_source",
                node_type_id="core.test.disabled-source",
                enabled=False,
            ),
            WorkflowGraphNode(
                node_id="target",
                node_type_id="core.test.optional-input-target",
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-disabled-source-target",
                source_node_id="disabled_source",
                source_port="value",
                target_node_id="target",
                target_port="optional_value",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="required_value",
                display_name="Required Value",
                payload_type_id="value.v1",
                target_node_id="target",
                target_port="required_value",
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

    registry = WorkflowNodeRuntimeRegistry()
    registry.register_python_callable(disabled_source_node, _raise_assertion_handler)
    registry.register_python_callable(target_node, _optional_input_target_handler)
    executor = WorkflowGraphExecutor(registry=registry)

    execution_result = executor.execute(
        template=template,
        input_values={"required_value": {"value": "ok"}},
    )

    assert execution_result.outputs["result"] == {
        "value": "ok",
        "optional_was_none": True,
    }
    assert [record.node_id for record in execution_result.node_records] == ["target"]


def test_workflow_graph_executor_skips_unused_pure_node_branch() -> None:
    """验证纯节点仅连接禁用下游时不会执行，同时不影响可观察节点。"""

    pure_node = NodeDefinition(
        node_type_id="core.test.pure-render",
        display_name="Pure Render",
        category="test.execution",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        output_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
        capability_tags=("execution.pure",),
    )
    preview_node = NodeDefinition(
        node_type_id="core.test.preview",
        display_name="Preview",
        category="test.execution",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="value",
                display_name="Value",
                payload_type_id="value.v1",
            ),
        ),
    )
    observable_node = NodeDefinition(
        node_type_id="core.test.observable",
        display_name="Observable",
        category="test.execution",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        output_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="value.v1",
            ),
        ),
    )
    template = WorkflowGraphTemplate(
        template_id="unused-pure-branch-template",
        template_version="1.0.0",
        display_name="Unused Pure Branch",
        nodes=(
            WorkflowGraphNode(node_id="pure", node_type_id=pure_node.node_type_id),
            WorkflowGraphNode(
                node_id="preview",
                node_type_id=preview_node.node_type_id,
                enabled=False,
            ),
            WorkflowGraphNode(
                node_id="observable", node_type_id=observable_node.node_type_id
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-pure-preview",
                source_node_id="pure",
                source_port="value",
                target_node_id="preview",
                target_port="value",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="result",
                display_name="Result",
                payload_type_id="value.v1",
                source_node_id="observable",
                source_port="result",
            ),
        ),
    )
    registry = WorkflowNodeRuntimeRegistry()
    registry.register_python_callable(pure_node, _raise_assertion_handler)
    registry.register_python_callable(preview_node, _raise_assertion_handler)
    registry.register_python_callable(
        observable_node, lambda request: {"result": {"value": "ok"}}
    )

    execution_result = WorkflowGraphExecutor(registry=registry).execute(
        template=template,
        input_values={},
    )

    assert execution_result.outputs["result"] == {"value": "ok"}
    assert [record.node_id for record in execution_result.node_records] == [
        "observable"
    ]


def _normalize_text_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """去除输入文本两端空白。"""

    raw_payload = request.input_values["text"]
    raw_text = (
        str(raw_payload.get("value") or "")
        if isinstance(raw_payload, dict)
        else str(raw_payload)
    )
    return {"text": {"value": raw_text.strip()}}


def _uppercase_text_worker(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """模拟 worker-task 处理函数，把文本转换为大写。"""

    raw_payload = request.input_values["text"]
    raw_text = (
        str(raw_payload.get("value") or "")
        if isinstance(raw_payload, dict)
        else str(raw_payload)
    )
    return {"result": {"value": raw_text.upper()}}


def _raise_assertion_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """用于验证节点失败定位的测试处理函数。"""

    raise AssertionError("boom")


def _optional_input_target_handler(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """返回必填输入值，并标记可选输入是否为空。"""

    required_payload = request.input_values["required_value"]
    required_value = (
        required_payload.get("value")
        if isinstance(required_payload, dict)
        else required_payload
    )
    return {
        "result": {
            "value": required_value,
            "optional_was_none": request.input_values["optional_value"] is None,
        }
    }
