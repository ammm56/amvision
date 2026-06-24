"""本地数据库输出节点输入来源和行 payload 构造。"""

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
from custom_nodes.output_local_db_nodes.backend.runtime.parameters import (
    _read_optional_non_empty_string,
    _read_optional_on_missing_policy,
    _read_required_non_empty_string,
)
from custom_nodes.output_local_db_nodes.backend.runtime.types import (
    ColumnMappingConfig,
    OnMissingPolicy,
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


def _build_row_payload(
    *,
    row_template: dict[str, object],
    static_fields: dict[str, object],
    mappings: tuple[ColumnMappingConfig, ...],
    source_roots: dict[SourceKind, dict[str, object] | None],
    default_on_missing: OnMissingPolicy,
    node_name: str,
) -> dict[str, object]:
    """组装待写入的单行记录。"""

    row_payload = _clone_json_object(row_template)
    _deep_merge_into(
        target=row_payload,
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
            field_name=f"column_mappings[{mapping_index}]",
        )
        if skip_mapping:
            continue
        row_payload[mapping.column_name] = _normalize_row_cell_value(
            raw_value=resolved_value,
            node_name=node_name,
            field_name=f"column_mappings[{mapping_index}]",
        )
    return row_payload


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


def _read_column_mappings(
    *, raw_value: object, node_name: str
) -> tuple[ColumnMappingConfig, ...]:
    """读取数据库列映射配置。"""

    if raw_value is None:
        return ()
    if not isinstance(raw_value, list):
        raise InvalidRequestError(f"{node_name} 的 column_mappings 必须是数组")
    return tuple(
        _build_column_mapping_config(
            raw_mapping=raw_mapping,
            mapping_index=mapping_index,
            node_name=node_name,
        )
        for mapping_index, raw_mapping in enumerate(raw_value)
    )


def _build_column_mapping_config(
    *,
    raw_mapping: object,
    mapping_index: int,
    node_name: str,
) -> ColumnMappingConfig:
    """构造单个数据库列映射。"""

    if not isinstance(raw_mapping, dict):
        raise InvalidRequestError(
            f"{node_name} 的 column_mappings[{mapping_index}] 必须是对象"
        )
    field_prefix = f"column_mappings[{mapping_index}]"
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
    return ColumnMappingConfig(
        column_name=_read_required_non_empty_string(
            raw_value=raw_mapping.get("column_name"),
            node_name=node_name,
            field_name=f"{field_prefix}.column_name",
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


def _normalize_row_cell_value(
    *, raw_value: object, node_name: str, field_name: str
) -> object:
    """把列值限制到第一阶段允许的标量范围。"""

    if raw_value is None or isinstance(raw_value, (str, int, float, bool)):
        return raw_value
    raise InvalidRequestError(
        f"{node_name} 的 {field_name} 当前只支持标量或 null",
        details={"value_type": raw_value.__class__.__name__},
    )


def _validate_key_column_values_present(
    *,
    row_payload: dict[str, object],
    key_columns: tuple[str, ...],
    node_name: str,
) -> None:
    """校验 key 列在行记录中已经具备非空值。"""

    for key_column in key_columns:
        if key_column not in row_payload:
            raise InvalidRequestError(
                f"{node_name} 的 key_columns 缺少对应行值",
                details={"column_name": key_column},
            )
        if row_payload[key_column] is None:
            raise InvalidRequestError(
                f"{node_name} 的 key_columns 不能写入 null",
                details={"column_name": key_column},
            )
