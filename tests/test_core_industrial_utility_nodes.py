"""工业视觉实施阶段 1 的 Core 通用节点测试。"""

from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest

from backend.nodes.core_nodes.io.output.storage.text_save_local import (
    _text_save_local_handler,
)
from backend.nodes.core_nodes.logic.control.delay import _delay_handler
from backend.nodes.core_nodes.logic.numeric.number_function import (
    _number_function_handler,
)
from backend.nodes.core_nodes.logic.numeric.number_operation import (
    _number_operation_handler,
)
from backend.nodes.core_nodes.logic.numeric.unit_convert import _unit_convert_handler
from backend.nodes.core_nodes.logic.value.format_string import _format_string_handler
from backend.service.application.errors import (
    InvalidRequestError,
    OperationCancelledError,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


def _request(
    *,
    parameters: dict[str, object] | None = None,
    input_values: dict[str, object] | None = None,
    **kwargs: object,
) -> WorkflowNodeExecutionRequest:
    """构造轻量节点执行请求。"""

    return WorkflowNodeExecutionRequest(
        node_id="test-node",
        node_definition=object(),
        parameters=dict(parameters or {}),
        input_values=dict(input_values or {}),
        **kwargs,
    )


@pytest.mark.parametrize(
    ("operation", "expected"),
    (("add", 10.0), ("subtract", 4.0), ("multiply", 21.0), ("divide", 7 / 3)),
)
def test_number_operation_supports_four_explicit_operations(
    operation: str,
    expected: float,
) -> None:
    """验证四类二元运算不做字符串隐式转换。"""

    output = _number_operation_handler(
        _request(
            parameters={"operation": operation},
            input_values={"left": {"value": 7}, "right": {"value": 3}},
        )
    )

    assert output["value"]["value"] == pytest.approx(expected)


def test_number_nodes_reject_division_by_zero_nan_and_invalid_clamp() -> None:
    """验证数值节点对退化输入快速失败。"""

    with pytest.raises(InvalidRequestError, match="除数为 0"):
        _number_operation_handler(
            _request(
                parameters={"operation": "divide"},
                input_values={"left": {"value": 1}, "right": {"value": 0}},
            )
        )
    with pytest.raises(InvalidRequestError, match="有限数值"):
        _number_operation_handler(
            _request(
                parameters={"operation": "add"},
                input_values={"left": {"value": float("nan")}, "right": {"value": 1}},
            )
        )
    with pytest.raises(InvalidRequestError, match="minimum 不能大于 maximum"):
        _number_function_handler(
            _request(
                parameters={"function": "clamp", "minimum": 5, "maximum": 1},
                input_values={"value": {"value": 3}},
            )
        )


def test_number_function_uses_explicit_decimal_rounding_modes() -> None:
    """验证 Round 的 half-even 与 half-up 语义不同且稳定。"""

    half_even = _number_function_handler(
        _request(
            parameters={
                "function": "round",
                "decimals": 0,
                "rounding_mode": "half-even",
            },
            input_values={"value": {"value": 2.5}},
        )
    )
    half_up = _number_function_handler(
        _request(
            parameters={
                "function": "round",
                "decimals": 0,
                "rounding_mode": "half-up",
            },
            input_values={"value": {"value": 2.5}},
        )
    )

    assert half_even["value"]["value"] == 2.0
    assert half_up["value"]["value"] == 3.0


def test_numeric_and_format_nodes_apply_catalog_defaults_at_runtime() -> None:
    """验证保存的空 parameters 也使用目录声明的稳定默认值。"""

    addition = _number_operation_handler(
        _request(
            input_values={"left": {"value": 2}, "right": {"value": 3}},
        )
    )
    absolute = _number_function_handler(_request(input_values={"value": {"value": -4}}))
    converted = _unit_convert_handler(_request(input_values={"value": {"value": 1000}}))
    formatted = _format_string_handler(
        _request(input_values={"values": {"value": {"value": "ok"}}})
    )

    assert addition["value"] == {"value": 5}
    assert absolute["value"] == {"value": 4}
    assert converted["value"] == {"value": 1.0}
    assert formatted["value"] == {"value": "ok"}


def test_unit_convert_rejects_cross_dimension_conversion() -> None:
    """验证单位换算只允许同量纲。"""

    output = _unit_convert_handler(
        _request(
            parameters={"source_unit": "millimeter", "target_unit": "meter"},
            input_values={"value": {"value": 1250}},
        )
    )
    assert output["value"]["value"] == pytest.approx(1.25)
    with pytest.raises(InvalidRequestError, match="跨量纲"):
        _unit_convert_handler(
            _request(
                parameters={"source_unit": "meter", "target_unit": "second"},
                input_values={"value": {"value": 1}},
            )
        )


def test_format_string_allows_named_fields_but_rejects_expression_access() -> None:
    """验证格式化节点不能通过字段访问执行表达式。"""

    output = _format_string_handler(
        _request(
            parameters={"template": "x={x:.2f}, label={label}"},
            input_values={"values": {"value": {"x": 1.25, "label": "OK"}}},
        )
    )
    assert output["value"]["value"] == "x=1.25, label=OK"
    with pytest.raises(InvalidRequestError, match="简单命名占位符"):
        _format_string_handler(
            _request(
                parameters={"template": "{value.__class__}"},
                input_values={"values": {"value": {"value": "x"}}},
            )
        )


def test_delay_responds_to_cancellation_without_sleeping_full_duration() -> None:
    """验证 Delay 使用现有可中断执行控制。"""

    cancellation_event = Event()
    cancellation_event.set()
    with pytest.raises(OperationCancelledError):
        _delay_handler(
            _request(
                parameters={"seconds": 3600},
                node_cancellation_event=cancellation_event,
            )
        )


def test_text_save_supports_overwrite_append_and_idempotent_replay(
    tmp_path: Path,
) -> None:
    """验证文本追加受路径锁保护，并按 invocation 避免重复副作用。"""

    output_path = tmp_path / "result.txt"
    overwrite_request = _request(
        parameters={
            "save_directory": str(output_path.parent),
            "file_name": output_path.name,
            "mode": "overwrite",
        },
        input_values={"value": {"value": "first"}},
        node_invocation_id="overwrite-1",
    )
    _text_save_local_handler(overwrite_request)
    append_request = _request(
        parameters={
            "save_directory": str(output_path.parent),
            "file_name": output_path.name,
            "mode": "append",
            "ensure_trailing_newline": True,
        },
        input_values={"value": {"value": "-second"}},
        node_invocation_id="append-1",
    )
    first_append = _text_save_local_handler(append_request)
    replay = _text_save_local_handler(append_request)

    assert output_path.read_text(encoding="utf-8") == "first-second\n"
    assert first_append["summary"]["value"]["idempotent_replay"] is False
    assert replay["summary"]["value"]["idempotent_replay"] is True


def test_text_save_supports_object_store_relative_location(tmp_path: Path) -> None:
    """验证文本保存沿用相对 ObjectStore 与绝对本机路径双语义。"""

    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "objects"))
    )
    output = _text_save_local_handler(
        _request(
            parameters={
                "save_directory": "workflow/results",
                "file_name": "result.txt",
                "mode": "overwrite",
            },
            input_values={"value": {"value": "结果"}},
            execution_metadata={"dataset_storage": storage},
        )
    )

    assert (
        storage.resolve("workflow/results/result.txt").read_text(encoding="utf-8")
        == "结果"
    )
    assert output["summary"]["value"]["saved_output"] == {
        "kind": "object-store",
        "object_key": "workflow/results/result.txt",
    }
