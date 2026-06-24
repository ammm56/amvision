"""MES HTTP query 和 body payload 构造。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError
from custom_nodes.output_mes_http_nodes.backend.runtime.payloads.values import (
    _clone_json_object,
    _deep_merge_into,
    _resolve_mapping_value,
    _write_object_path_value,
)
from custom_nodes.output_mes_http_nodes.backend.runtime.types import (
    FieldMappingConfig,
    OnMissingPolicy,
    QueryMappingConfig,
    SourceKind,
)


def _build_query_payload(
    *,
    template: dict[str, object],
    mappings: tuple[QueryMappingConfig, ...],
    source_roots: dict[SourceKind, dict[str, object] | None],
    default_on_missing: OnMissingPolicy,
    node_name: str,
) -> dict[str, object]:
    """组装 HTTP query 参数对象。"""

    query_payload: dict[str, object] = {}
    for key, value in template.items():
        query_payload[str(key)] = _normalize_query_parameter_value(
            raw_value=value,
            node_name=node_name,
            field_name=f"query_template.{key}",
        )
    for mapping_index, mapping in enumerate(mappings):
        skip_mapping, resolved_value = _resolve_mapping_value(
            source_kind=mapping.source_kind,
            source_path=mapping.source_path,
            literal_value=mapping.literal_value,
            on_missing=mapping.on_missing or default_on_missing,
            source_roots=source_roots,
            node_name=node_name,
            field_name=f"query_mappings[{mapping_index}]",
        )
        if skip_mapping:
            continue
        query_payload[mapping.target_name] = _normalize_query_parameter_value(
            raw_value=resolved_value,
            node_name=node_name,
            field_name=f"query_mappings[{mapping_index}]",
        )
    return query_payload


def _build_body_payload(
    *,
    body_template: dict[str, object],
    static_fields: dict[str, object],
    mappings: tuple[FieldMappingConfig, ...],
    source_roots: dict[SourceKind, dict[str, object] | None],
    default_on_missing: OnMissingPolicy,
    node_name: str,
) -> dict[str, object]:
    """组装 HTTP JSON body 对象。"""

    body_payload = _clone_json_object(body_template)
    _deep_merge_into(
        target=body_payload,
        incoming=static_fields,
    )
    for mapping_index, mapping in enumerate(mappings):
        skip_mapping, resolved_value = _resolve_mapping_value(
            source_kind=mapping.source_kind,
            source_path=mapping.source_path,
            literal_value=mapping.literal_value,
            on_missing=mapping.on_missing or default_on_missing,
            source_roots=source_roots,
            node_name=node_name,
            field_name=f"field_mappings[{mapping_index}]",
        )
        if skip_mapping:
            continue
        _write_object_path_value(
            target=body_payload,
            target_path=mapping.target_path,
            value=resolved_value,
            node_name=node_name,
            field_name=f"field_mappings[{mapping_index}].target_path",
        )
    return body_payload


def _normalize_query_parameter_value(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> object:
    """把 query 值收敛到 httpx 可接受的受限形态。"""

    if raw_value is None:
        return "null"
    if isinstance(raw_value, bool):
        return "true" if raw_value else "false"
    if isinstance(raw_value, (int, float, str)):
        return str(raw_value)
    if isinstance(raw_value, list):
        return [
            _normalize_query_parameter_value(
                raw_value=item,
                node_name=node_name,
                field_name=f"{field_name}[]",
            )
            for item in raw_value
        ]
    raise InvalidRequestError(
        f"{node_name} 的 {field_name} 只能是标量、null 或标量数组",
        details={"value_type": raw_value.__class__.__name__},
    )
