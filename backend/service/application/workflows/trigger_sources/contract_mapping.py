"""Workflow TriggerSource 结果映射与公开契约的共享语义。"""

from __future__ import annotations

from collections.abc import Collection


def find_unknown_result_bindings(
    *,
    output_binding_ids: Collection[str],
    result_mapping: dict[str, object],
    result_mode: str,
) -> tuple[str, ...]:
    """返回需交付结果中选择、但公开契约不存在的 binding id。"""

    if result_mode == "event-only":
        return ()
    raw_bindings = result_mapping.get("result_bindings")
    if not isinstance(raw_bindings, list | tuple):
        return ()
    return tuple(
        binding_id
        for raw_binding_id in raw_bindings
        if isinstance(raw_binding_id, str)
        and (binding_id := raw_binding_id.strip())
        and binding_id not in output_binding_ids
    )
