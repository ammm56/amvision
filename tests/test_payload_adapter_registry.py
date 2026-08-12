"""Payload Adapter registry 与现有桥接节点测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.nodes.core_nodes.logic.value.payload_to_value import (
    _payload_to_value_handler,
)
from backend.nodes.payload_adapters import PayloadAdapterRegistry
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.workflows.execution.contracts import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.basic.backend.nodes.payload_to_value import (
    handle_node as handle_opencv_payload_to_value,
)


def _request(*, input_values: dict[str, object]) -> WorkflowNodeExecutionRequest:
    """构造 adapter 节点请求。"""

    return WorkflowNodeExecutionRequest(
        node_id="adapter-node",
        node_definition=SimpleNamespace(node_type_id="adapter"),
        input_values=input_values,
    )


def test_payload_adapter_registry_rejects_duplicate_pair() -> None:
    """同一 source/target contract 不能被静默覆盖。"""

    registry = PayloadAdapterRegistry()
    registry.register("source.v1", "target.v1", lambda payload, request: payload)

    with pytest.raises(ServiceConfigurationError):
        registry.register(
            "source.v1",
            "target.v1",
            lambda payload, request: payload,
        )


def test_payload_adapter_registry_rejects_unknown_conversion() -> None:
    """registry 禁止猜测或隐式链式转换。"""

    with pytest.raises(InvalidRequestError):
        PayloadAdapterRegistry().resolve("source.v1", "target.v1")


def test_core_payload_to_value_uses_registered_boolean_adapter() -> None:
    """核心桥接节点应通过 registry 解包 boolean.v1。"""

    output = _payload_to_value_handler(
        _request(input_values={"boolean": {"value": True}})
    )

    assert output == {"value": {"value": True}}


def test_opencv_payload_to_value_uses_registered_object_adapter() -> None:
    """OpenCV 桥接节点应通过同一 registry 复制结构化 payload。"""

    output = handle_opencv_payload_to_value(
        _request(input_values={"contours": {"items": [], "count": 0}})
    )

    assert output["value"]["value"] == {"items": [], "count": 0}
