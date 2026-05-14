"""Hello World 节点包的 backend entrypoint。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from backend.service.application.workflows.runtime_registry_loader import (
    NodePackEntrypointRegistrationContext,
)


NODE_TYPE_ID = "custom.hello-world.message"


def _handle_hello_world_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """根据输入 name 或默认参数生成问候消息。

    参数：
    - request：当前 workflow 节点执行请求。

    返回：
    - dict[str, object]：包含 greeting 输出的 value.v1 payload。
    """

    greeting = _read_non_empty_string_parameter(
        request.parameters.get("greeting"),
        field_name="greeting",
        default_value="Hello",
    )
    default_name = _read_non_empty_string_parameter(
        request.parameters.get("default_name"),
        field_name="default_name",
        default_value="World",
    )
    resolved_name = _read_optional_name_input(request.input_values.get("name")) or default_name
    return {
        "greeting": {
            "value": f"{greeting}, {resolved_name}!",
        }
    }


def _read_optional_name_input(payload: object) -> str | None:
    """读取可选的 name 输入值。

    参数：
    - payload：输入端口上的 value.v1 payload。

    返回：
    - str | None：规范化后的 name；没有提供时返回 None。
    """

    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise InvalidRequestError("hello-world 节点的 name 输入必须是 value.v1 对象")
    raw_value = payload.get("value")
    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError("hello-world 节点的 name 输入必须是非空字符串")
    return raw_value.strip()


def _read_non_empty_string_parameter(raw_value: object, *, field_name: str, default_value: str) -> str:
    """读取非空字符串参数。

    参数：
    - raw_value：原始参数值。
    - field_name：参数名。
    - default_value：缺省时返回的默认值。

    返回：
    - str：规范化后的参数字符串。
    """

    if raw_value is None:
        return default_value
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"hello-world 节点的 {field_name} 参数必须是非空字符串")
    return raw_value.strip()


def register(context: NodePackEntrypointRegistrationContext) -> None:
    """注册 Hello World 节点包中的 python-callable 节点。

    参数：
    - context：当前 node pack 的注册上下文。
    """

    context.register_python_callable(NODE_TYPE_ID, _handle_hello_world_node)