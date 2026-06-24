"""MES HTTP 字段映射取值和对象路径写入。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import (
    build_value_payload,
    try_extract_value_by_path,
)
from backend.service.application.errors import InvalidRequestError
from custom_nodes.output_mes_http_nodes.backend.runtime.types import (
    OnMissingPolicy,
    SourceKind,
)


def _resolve_mapping_value(
    *,
    source_kind: SourceKind,
    source_path: str | None,
    literal_value: object | None,
    on_missing: OnMissingPolicy,
    source_roots: dict[SourceKind, dict[str, object] | None],
    node_name: str,
    field_name: str,
) -> tuple[bool, object | None]:
    """按来源规则解析单个映射值。"""

    if source_kind == "literal":
        return False, literal_value

    source_root = source_roots.get(source_kind)
    if source_root is None:
        return _handle_missing_mapping_value(
            on_missing=on_missing,
            node_name=node_name,
            field_name=field_name,
            reason="source_scope_missing",
            details={"source_kind": source_kind},
        )
    assert source_path is not None
    exists, resolved_value = try_extract_value_by_path(
        root=source_root, path=source_path
    )
    if not exists:
        return _handle_missing_mapping_value(
            on_missing=on_missing,
            node_name=node_name,
            field_name=field_name,
            reason="source_value_missing",
            details={"source_kind": source_kind, "source_path": source_path},
        )
    return False, resolved_value


def _handle_missing_mapping_value(
    *,
    on_missing: OnMissingPolicy,
    node_name: str,
    field_name: str,
    reason: str,
    details: dict[str, object],
) -> tuple[bool, object | None]:
    """统一处理映射缺失。"""

    if on_missing == "skip":
        return True, None
    if on_missing == "null":
        return False, None
    raise InvalidRequestError(
        f"{node_name} 的 {field_name} 缺少来源值",
        details={"reason": reason, **details},
    )


def _clone_json_object(value: dict[str, object]) -> dict[str, object]:
    """复制 JSON 对象。"""

    normalized_value = build_value_payload(value)["value"]
    assert isinstance(normalized_value, dict)
    return normalized_value


def _deep_merge_into(*, target: dict[str, object], incoming: dict[str, object]) -> None:
    """把 incoming 递归合并到 target。"""

    for key, value in incoming.items():
        existing_value = target.get(key)
        if isinstance(existing_value, dict) and isinstance(value, dict):
            _deep_merge_into(target=existing_value, incoming=value)
            continue
        target[key] = build_value_payload(value)["value"]


def _write_object_path_value(
    *,
    target: dict[str, object],
    target_path: str,
    value: object,
    node_name: str,
    field_name: str,
) -> None:
    """按点路径把值写入对象。"""

    segments = tuple(segment.strip() for segment in target_path.split("."))
    if not segments or any(not segment for segment in segments):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 不能包含空路径段")
    current_object = target
    for segment in segments[:-1]:
        existing_value = current_object.get(segment)
        if existing_value is None:
            next_object: dict[str, object] = {}
            current_object[segment] = next_object
            current_object = next_object
            continue
        if not isinstance(existing_value, dict):
            raise InvalidRequestError(
                f"{node_name} 的 {field_name} 无法写入到非对象路径",
                details={"target_path": target_path, "conflict_segment": segment},
            )
        current_object = existing_value
    current_object[segments[-1]] = build_value_payload(value)["value"]
