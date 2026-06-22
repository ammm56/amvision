"""workflow 图执行变量存储辅助函数。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError


def read_workflow_variable_snapshot(
    *,
    execution_metadata: dict[str, object],
    name: str,
) -> tuple[bool, object | None]:
    """从 execution_metadata 中读取变量当前快照。"""

    variable_store = require_workflow_variable_store(execution_metadata)
    if name not in variable_store:
        return False, None
    return True, variable_store[name]


def write_workflow_variable_value(
    *,
    execution_metadata: dict[str, object],
    name: str,
    value: object,
) -> None:
    """把变量值写入 execution_metadata 中的 workflow_variables。"""

    require_workflow_variable_store(execution_metadata)[name] = value


def restore_workflow_variable_value(
    *,
    execution_metadata: dict[str, object],
    name: str,
    existed: bool,
    value: object | None,
) -> None:
    """把变量恢复为进入当前执行段之前的状态。"""

    variable_store = require_workflow_variable_store(execution_metadata)
    if existed:
        variable_store[name] = value
        return
    variable_store.pop(name, None)


def require_workflow_variable_store(execution_metadata: dict[str, object]) -> dict[str, object]:
    """确保 execution_metadata 中存在 workflow_variables 存储。"""

    raw_store = execution_metadata.get("workflow_variables")
    if raw_store is None:
        raw_store = {}
        execution_metadata["workflow_variables"] = raw_store
    if not isinstance(raw_store, dict):
        raise InvalidRequestError(
            "workflow_variables 必须是对象",
            details={"metadata_key": "workflow_variables"},
        )
    return raw_store
