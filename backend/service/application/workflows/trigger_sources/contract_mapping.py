"""Workflow TriggerSource 结果映射与公开契约的共享语义。"""

from __future__ import annotations

from collections.abc import Collection


WORKFLOW_RESULT_FALLBACK_BINDING = "workflow_result"


def find_unknown_result_binding(
    *,
    output_binding_ids: Collection[str],
    result_mapping: dict[str, object],
    result_mode: str,
) -> str | None:
    """返回需要契约输出、但契约中不存在的 result binding。

    `workflow_result` 是 ResultDispatcher 的历史全 outputs fallback 标记，并不对应
    公开输出 binding。`accepted-then-query` 和 `event-only` 不读取 result binding，
    因此也不应由一个未使用的配置阻断 Trigger 恢复或 Runtime 选版。
    """

    if result_mode != "sync-reply":
        return None
    result_binding = result_mapping.get("result_binding")
    if not isinstance(result_binding, str) or not result_binding.strip():
        return None
    if result_binding == WORKFLOW_RESULT_FALLBACK_BINDING:
        return None
    if result_binding in output_binding_ids:
        return None
    return result_binding
