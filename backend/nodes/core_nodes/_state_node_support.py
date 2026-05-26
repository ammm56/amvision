"""workflow 变量状态类 core nodes 共享 helper。"""

from __future__ import annotations

from backend.nodes.core_nodes._logic_node_support import build_value_payload
from backend.service.application.errors import InvalidRequestError


WORKFLOW_VARIABLE_STORE_KEY = "workflow_variables"


def require_workflow_variable_name(raw_name: object, *, field_name: str = "name") -> str:
    """校验变量名称参数。

    参数：
    - raw_name：待校验的变量名称。
    - field_name：错误消息中使用的字段名。

    返回：
    - str：去除两端空白后的变量名称。
    """

    if not isinstance(raw_name, str) or not raw_name.strip():
        raise InvalidRequestError(f"{field_name} 必须是非空字符串")
    return raw_name.strip()


def read_workflow_variable(
    execution_metadata: dict[str, object],
    *,
    name: str,
) -> tuple[bool, object | None]:
    """读取 workflow 执行级变量。

    参数：
    - execution_metadata：当前图执行共享 metadata。
    - name：变量名称。

    返回：
    - tuple[bool, object | None]：是否存在，以及读取到的变量值。
    """

    variable_store = _read_workflow_variable_store(execution_metadata)
    if name not in variable_store:
        return False, None
    return True, variable_store[name]


def write_workflow_variable(
    execution_metadata: dict[str, object],
    *,
    name: str,
    value: object,
) -> object:
    """写入 workflow 执行级变量。

    参数：
    - execution_metadata：当前图执行共享 metadata。
    - name：变量名称。
    - value：待写入的变量值。

    返回：
    - object：规范化后实际写入的变量值。
    """

    variable_store = _ensure_workflow_variable_store(execution_metadata)
    normalized_value = build_value_payload(value)["value"]
    variable_store[name] = normalized_value
    return normalized_value


def delete_workflow_variable(
    execution_metadata: dict[str, object],
    *,
    name: str,
) -> tuple[bool, object | None]:
    """删除 workflow 执行级变量。

    参数：
    - execution_metadata：当前图执行共享 metadata。
    - name：变量名称。

    返回：
    - tuple[bool, object | None]：变量删除前是否存在，以及删除前的变量值。
    """

    variable_store = _read_workflow_variable_store(execution_metadata)
    if name not in variable_store:
        return False, None
    deleted_value = variable_store[name]
    _ensure_workflow_variable_store(execution_metadata).pop(name, None)
    return True, deleted_value


def restore_workflow_variable(
    execution_metadata: dict[str, object],
    *,
    name: str,
    existed: bool,
    value: object | None,
) -> None:
    """恢复变量在进入某段执行前的状态。

    参数：
    - execution_metadata：当前图执行共享 metadata。
    - name：变量名称。
    - existed：恢复前变量是否存在。
    - value：恢复前变量值。
    """

    variable_store = _ensure_workflow_variable_store(execution_metadata)
    if existed:
        variable_store[name] = value
        return
    variable_store.pop(name, None)


def _read_workflow_variable_store(execution_metadata: dict[str, object]) -> dict[str, object]:
    """以只读方式读取 workflow 变量存储。"""

    raw_store = execution_metadata.get(WORKFLOW_VARIABLE_STORE_KEY)
    if raw_store is None:
        return {}
    if not isinstance(raw_store, dict):
        raise InvalidRequestError(
            "workflow_variables 必须是对象",
            details={"metadata_key": WORKFLOW_VARIABLE_STORE_KEY},
        )
    return raw_store


def _ensure_workflow_variable_store(execution_metadata: dict[str, object]) -> dict[str, object]:
    """确保 execution_metadata 中存在可写的 workflow 变量存储。"""

    raw_store = execution_metadata.get(WORKFLOW_VARIABLE_STORE_KEY)
    if raw_store is None:
        raw_store = {}
        execution_metadata[WORKFLOW_VARIABLE_STORE_KEY] = raw_store
    if not isinstance(raw_store, dict):
        raise InvalidRequestError(
            "workflow_variables 必须是对象",
            details={"metadata_key": WORKFLOW_VARIABLE_STORE_KEY},
        )
    return raw_store