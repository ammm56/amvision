"""custom node 可信直调契约测试。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CUSTOM,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
)
from backend.service.application.workflows.execution.contracts import (
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.execution.registry import (
    WorkflowNodeRuntimeRegistry,
)


def _custom_definition() -> NodeDefinition:
    """构造测试使用的 custom node 定义。"""

    return NodeDefinition(
        node_type_id="custom.test.direct-probe",
        display_name="Direct Probe",
        category="test.runtime.direct",
        implementation_kind=NODE_IMPLEMENTATION_CUSTOM,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        version="12.1.0",
        node_pack_id="test.nodes",
        node_pack_version="9.4.1",
    )


def test_registry_invokes_custom_handler_directly() -> None:
    """验证 custom handler 无权限包装和隔离层，直接接收原请求。"""

    registry = WorkflowNodeRuntimeRegistry()
    definition = _custom_definition()
    observed_requests: list[WorkflowNodeExecutionRequest] = []

    def handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
        observed_requests.append(request)
        return {"ok": True, "node_id": request.node_id}

    registry.register_python_callable(definition, handler)
    resolved_handler = registry.resolve_handler(node_definition=definition)
    request = WorkflowNodeExecutionRequest(node_id="probe", node_definition=definition)

    assert resolved_handler is handler
    assert resolved_handler(request) == {"ok": True, "node_id": "probe"}
    assert observed_requests == [request]


def test_registry_invokes_custom_model_provider_directly() -> None:
    """验证 custom model provider 直接登记，不依赖权限策略对象。"""

    registry = WorkflowNodeRuntimeRegistry()
    provider = object()
    definition = _custom_definition().model_copy(
        update={"node_type_id": "custom.test.model"}
    )
    registry.register_node_definition(definition)

    registry.register_model_session_provider("custom.test.model", provider)  # type: ignore[arg-type]

    assert registry.get_model_session_provider("custom.test.model") is provider
