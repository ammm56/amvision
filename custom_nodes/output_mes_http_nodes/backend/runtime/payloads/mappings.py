"""MES HTTP 字段映射配置解析。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from custom_nodes.output_mes_http_nodes.backend.runtime.parameters import (
    _read_optional_non_empty_string,
    _read_optional_on_missing_policy,
    _read_required_non_empty_string,
)
from custom_nodes.output_mes_http_nodes.backend.runtime.types import (
    FieldMappingConfig,
    QueryMappingConfig,
    SourceKind,
)


def _read_query_mappings(
    *, raw_value: object, node_name: str
) -> tuple[QueryMappingConfig, ...]:
    """读取 query 字段映射配置。"""

    if raw_value is None:
        return ()
    if not isinstance(raw_value, list):
        raise InvalidRequestError(f"{node_name} 的 query_mappings 必须是数组")
    return tuple(
        _build_query_mapping_config(
            raw_mapping=raw_mapping,
            mapping_index=mapping_index,
            node_name=node_name,
        )
        for mapping_index, raw_mapping in enumerate(raw_value)
    )


def _read_field_mappings(
    *, raw_value: object, node_name: str
) -> tuple[FieldMappingConfig, ...]:
    """读取 body 字段映射配置。"""

    if raw_value is None:
        return ()
    if not isinstance(raw_value, list):
        raise InvalidRequestError(f"{node_name} 的 field_mappings 必须是数组")
    return tuple(
        _build_field_mapping_config(
            raw_mapping=raw_mapping,
            mapping_index=mapping_index,
            node_name=node_name,
        )
        for mapping_index, raw_mapping in enumerate(raw_value)
    )


def _build_query_mapping_config(
    *,
    raw_mapping: object,
    mapping_index: int,
    node_name: str,
) -> QueryMappingConfig:
    """构造单个 query 映射配置。"""

    if not isinstance(raw_mapping, dict):
        raise InvalidRequestError(
            f"{node_name} 的 query_mappings[{mapping_index}] 必须是对象"
        )
    field_prefix = f"query_mappings[{mapping_index}]"
    source_kind = _read_source_kind(
        raw_value=raw_mapping.get("source_kind"),
        node_name=node_name,
        field_name=f"{field_prefix}.source_kind",
    )
    source_path = _read_optional_non_empty_string(
        raw_value=raw_mapping.get("source_path"),
        node_name=node_name,
        field_name=f"{field_prefix}.source_path",
    )
    if source_kind != "literal" and source_path is None:
        raise InvalidRequestError(f"{node_name} 的 {field_prefix}.source_path 不能为空")

    literal_value = None
    if "literal_value" in raw_mapping:
        literal_value = build_value_payload(raw_mapping.get("literal_value"))["value"]
    if source_kind == "literal" and "literal_value" not in raw_mapping:
        raise InvalidRequestError(
            f"{node_name} 的 {field_prefix}.literal_value 不能为空"
        )
    return QueryMappingConfig(
        target_name=_read_required_non_empty_string(
            raw_value=raw_mapping.get("target_name"),
            node_name=node_name,
            field_name=f"{field_prefix}.target_name",
        ),
        source_kind=source_kind,
        source_path=source_path,
        literal_value=literal_value,
        on_missing=_read_optional_on_missing_policy(
            raw_value=raw_mapping.get("on_missing"),
            node_name=node_name,
            field_name=f"{field_prefix}.on_missing",
        ),
    )


def _build_field_mapping_config(
    *,
    raw_mapping: object,
    mapping_index: int,
    node_name: str,
) -> FieldMappingConfig:
    """构造单个 body 字段映射配置。"""

    if not isinstance(raw_mapping, dict):
        raise InvalidRequestError(
            f"{node_name} 的 field_mappings[{mapping_index}] 必须是对象"
        )
    field_prefix = f"field_mappings[{mapping_index}]"
    source_kind = _read_source_kind(
        raw_value=raw_mapping.get("source_kind"),
        node_name=node_name,
        field_name=f"{field_prefix}.source_kind",
    )
    source_path = _read_optional_non_empty_string(
        raw_value=raw_mapping.get("source_path"),
        node_name=node_name,
        field_name=f"{field_prefix}.source_path",
    )
    if source_kind != "literal" and source_path is None:
        raise InvalidRequestError(f"{node_name} 的 {field_prefix}.source_path 不能为空")

    literal_value = None
    if "literal_value" in raw_mapping:
        literal_value = build_value_payload(raw_mapping.get("literal_value"))["value"]
    if source_kind == "literal" and "literal_value" not in raw_mapping:
        raise InvalidRequestError(
            f"{node_name} 的 {field_prefix}.literal_value 不能为空"
        )
    return FieldMappingConfig(
        target_path=_read_required_non_empty_string(
            raw_value=raw_mapping.get("target_path"),
            node_name=node_name,
            field_name=f"{field_prefix}.target_path",
        ),
        source_kind=source_kind,
        source_path=source_path,
        literal_value=literal_value,
        on_missing=_read_optional_on_missing_policy(
            raw_value=raw_mapping.get("on_missing"),
            node_name=node_name,
            field_name=f"{field_prefix}.on_missing",
        ),
    )


def _read_source_kind(
    *, raw_value: object, node_name: str, field_name: str
) -> SourceKind:
    """读取映射来源域。"""

    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {
        "result",
        "workflow_result",
        "summary",
        "request",
        "literal",
    }:
        raise InvalidRequestError(
            f"{node_name} 的 {field_name} 不支持当前取值",
            details={"source_kind": raw_value},
        )
    return normalized_value  # type: ignore[return-value]
