"""目录窗口参数读取 helper。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import require_value_payload
from backend.service.application.errors import InvalidRequestError


def read_batch_size(
    *,
    input_payload: object,
    parameter_value: object,
    node_name: str,
) -> int:
    """读取批次大小，优先使用运行时输入。"""

    raw_value = read_runtime_scalar(
        input_payload,
        field_name="batch_size",
        node_name=node_name,
    )
    if raw_value is None:
        raw_value = parameter_value
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{node_name} 的 batch_size 必须是整数")
    if raw_value <= 0:
        raise InvalidRequestError(f"{node_name} 的 batch_size 必须大于 0")
    return raw_value


def read_start_index(
    *,
    input_payload: object,
    parameter_value: object,
    node_name: str,
) -> int:
    """读取批次起始索引，优先使用运行时输入。"""

    raw_value = read_runtime_scalar(
        input_payload,
        field_name="start_index",
        node_name=node_name,
    )
    if raw_value is None:
        raw_value = parameter_value
    if raw_value is None:
        return 0
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{node_name} 的 start_index 必须是整数")
    if raw_value < 0:
        raise InvalidRequestError(f"{node_name} 的 start_index 不能小于 0")
    return raw_value


def read_runtime_scalar(
    input_payload: object,
    *,
    field_name: str,
    node_name: str,
) -> object:
    """读取可选的运行时 value.v1 标量输入。"""

    if input_payload is None:
        return None
    try:
        return require_value_payload(input_payload, field_name=field_name)["value"]
    except InvalidRequestError as exc:
        raise InvalidRequestError(
            f"{node_name} 的 {field_name} 输入必须是 value.v1",
            details=getattr(exc, "details", None),
        ) from exc
