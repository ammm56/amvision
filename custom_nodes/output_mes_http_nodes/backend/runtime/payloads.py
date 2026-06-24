"""MES HTTP 输出节点输入来源、query 和 body payload 构造。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import (
    build_value_payload,
    require_value_payload,
    try_extract_value_by_path,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.output_mes_http_nodes.backend.runtime.parameters import (
    _read_optional_non_empty_string,
    _read_optional_on_missing_policy,
    _read_required_non_empty_string,
)
from custom_nodes.output_mes_http_nodes.backend.runtime.types import (
    FieldMappingConfig,
    OnMissingPolicy,
    QueryMappingConfig,
    SourceKind,
)


def _read_source_roots(
    *,
    request: WorkflowNodeExecutionRequest,
    node_name: str,
) -> tuple[str, dict[SourceKind, dict[str, object] | None]]:
    """读取并校验主业务输入与 request 上下文。"""

    result_payload = _read_optional_inline_object_input(
        request=request,
        input_name="result",
        node_name=node_name,
    )
    workflow_result_payload = _read_optional_inline_object_input(
        request=request,
        input_name="workflow_result",
        node_name=node_name,
    )
    summary_payload = _read_optional_value_object_input(
        request=request,
        input_name="summary",
        node_name=node_name,
    )
    request_payload = _read_optional_value_object_input(
        request=request,
        input_name="request",
        node_name=node_name,
    )
    primary_sources = tuple(
        (source_kind, source_value)
        for source_kind, source_value in (
            ("result", result_payload),
            ("workflow_result", workflow_result_payload),
            ("summary", summary_payload),
        )
        if source_value is not None
    )
    if not primary_sources:
        raise InvalidRequestError(
            f"{node_name} 缺少主业务输入，必须提供 result / workflow_result / summary 之一"
        )
    if len(primary_sources) > 1:
        raise InvalidRequestError(
            f"{node_name} 的 result / workflow_result / summary 只能同时提供一个",
            details={
                "provided_sources": [source_kind for source_kind, _ in primary_sources]
            },
        )
    primary_source_kind = primary_sources[0][0]
    source_roots: dict[SourceKind, dict[str, object] | None] = {
        "result": result_payload,
        "workflow_result": workflow_result_payload,
        "summary": summary_payload,
        "request": request_payload,
        "literal": None,
    }
    return primary_source_kind, source_roots


def _read_optional_inline_object_input(
    *,
    request: WorkflowNodeExecutionRequest,
    input_name: str,
    node_name: str,
) -> dict[str, object] | None:
    """读取可选 inline-json 对象输入。"""

    raw_payload = request.input_values.get(input_name)
    if raw_payload is None:
        return None
    normalized_value = build_value_payload(raw_payload)["value"]
    if not isinstance(normalized_value, dict):
        raise InvalidRequestError(f"{node_name} 的输入 {input_name} 必须是对象 payload")
    return normalized_value


def _read_optional_value_object_input(
    *,
    request: WorkflowNodeExecutionRequest,
    input_name: str,
    node_name: str,
) -> dict[str, object] | None:
    """读取可选 value.v1 对象输入。"""

    raw_payload = request.input_values.get(input_name)
    if raw_payload is None:
        return None
    object_value = require_value_payload(raw_payload, field_name=input_name)["value"]
    if not isinstance(object_value, dict):
        raise InvalidRequestError(
            f"{node_name} 的输入 {input_name} 必须是对象 value payload"
        )
    return object_value


def _build_query_payload(
    *,
    template: dict[str, object],
    mappings: tuple[QueryMappingConfig, ...],
    source_roots: dict[SourceKind, dict[str, object] | None],
    default_on_missing: OnMissingPolicy,
    node_name: str,
) -> dict[str, object]:
    """组装 query 参数对象。"""

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
    """组装 JSON body 对象。"""

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
    """构造单个 query 映射。"""

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
    """构造单个 body 字段映射。"""

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
    """读取来源域。"""

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
