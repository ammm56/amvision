"""value-field-extract 节点的缺失字段策略测试。"""

from __future__ import annotations

import pytest

from backend.nodes.core_nodes.logic.value.value_field_extract import (
    _value_field_extract_handler,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def test_value_field_extract_uses_default_for_empty_list_path() -> None:
    """验证空推理列表可以映射为业务默认值而不是流程失败。"""

    result = _value_field_extract_handler(
        _build_request(
            parameters={
                "path": "items.0.score",
                "missing_policy": "default",
                "default_value": 0.0,
            }
        )
    )

    assert result == {"value": {"value": 0.0}}


def test_value_field_extract_can_return_null_for_missing_path() -> None:
    """验证 null 策略会稳定返回 JSON null。"""

    result = _value_field_extract_handler(
        _build_request(
            parameters={"path": "items.0.class_name", "missing_policy": "null"}
        )
    )

    assert result == {"value": {"value": None}}


def test_value_field_extract_keeps_error_as_default_policy() -> None:
    """验证未声明策略时仍对缺失路径给出明确错误。"""

    with pytest.raises(InvalidRequestError, match="列表下标越界"):
        _value_field_extract_handler(
            _build_request(parameters={"path": "items.0.score"})
        )


def _build_request(*, parameters: dict[str, object]) -> WorkflowNodeExecutionRequest:
    """构造空 items 输入的节点请求。"""

    return WorkflowNodeExecutionRequest(
        node_id="extract-optional-field",
        node_definition=object(),
        parameters=parameters,
        input_values={
            "value": {
                "payload_type_id": "value.v1",
                "value": {"count": 0, "items": []},
            }
        },
        execution_metadata={},
    )
