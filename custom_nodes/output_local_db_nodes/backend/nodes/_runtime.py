"""本地数据库输出节点运行时实现。"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Literal

from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.nodes.core_nodes._logic_node_support import (
    build_value_payload,
    require_value_payload,
    try_extract_value_by_path,
)
from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


SourceKind = Literal["result", "workflow_result", "summary", "request", "literal"]
OnMissingPolicy = Literal["error", "skip", "null"]
DatabaseKind = Literal["sqlite", "postgresql", "mysql"]


@dataclass(frozen=True)
class ColumnMappingConfig:
    """描述单个数据库列映射。"""

    column_name: str
    source_kind: SourceKind
    source_path: str | None
    literal_value: object | None
    on_missing: OnMissingPolicy | None


def execute_local_db_upsert_node(
    *,
    request: WorkflowNodeExecutionRequest,
    node_name: str,
) -> dict[str, object]:
    """执行第一阶段受限本地数据库 upsert。"""

    primary_source_kind, source_roots = _read_source_roots(
        request=request,
        node_name=node_name,
    )
    database_url = _read_required_non_empty_string(
        raw_value=request.parameters.get("database_url"),
        node_name=node_name,
        field_name="database_url",
    )
    database_kind = _read_database_kind(
        database_url=database_url,
        node_name=node_name,
    )
    table_name = _read_required_non_empty_string(
        raw_value=request.parameters.get("table_name"),
        node_name=node_name,
        field_name="table_name",
    )
    schema_name = _read_optional_non_empty_string(
        raw_value=request.parameters.get("schema_name"),
        node_name=node_name,
        field_name="schema_name",
    )
    key_columns = _read_required_string_list(
        raw_value=request.parameters.get("key_columns"),
        node_name=node_name,
        field_name="key_columns",
        require_non_empty=True,
    )
    default_on_missing = _read_on_missing_policy(
        raw_value=request.parameters.get("on_missing"),
        node_name=node_name,
        field_name="on_missing",
        default_value="error",
    )
    row_template = _read_optional_object_parameter(
        raw_value=request.parameters.get("row_template"),
        node_name=node_name,
        field_name="row_template",
    )
    static_fields = _read_optional_object_parameter(
        raw_value=request.parameters.get("static_fields"),
        node_name=node_name,
        field_name="static_fields",
    )
    column_mappings = _read_column_mappings(
        raw_value=request.parameters.get("column_mappings"),
        node_name=node_name,
    )
    if not column_mappings:
        raise InvalidRequestError(f"{node_name} 的 column_mappings 至少需要 1 项")
    update_columns_parameter = _read_optional_string_list(
        raw_value=request.parameters.get("update_columns"),
        node_name=node_name,
        field_name="update_columns",
    )
    skip_if_no_update_columns = _read_boolean_parameter(
        raw_value=request.parameters.get("skip_if_no_update_columns"),
        node_name=node_name,
        field_name="skip_if_no_update_columns",
        default_value=False,
    )
    connect_timeout_seconds = _read_optional_positive_float(
        raw_value=request.parameters.get("connect_timeout_seconds"),
        node_name=node_name,
        field_name="connect_timeout_seconds",
    )
    statement_timeout_seconds = _read_optional_positive_float(
        raw_value=request.parameters.get("statement_timeout_seconds"),
        node_name=node_name,
        field_name="statement_timeout_seconds",
    )
    if request.parameters.get("echo_sql") is not None:
        raise InvalidRequestError(f"{node_name} 当前不支持 echo_sql")

    row_payload = _build_row_payload(
        row_template=row_template,
        static_fields=static_fields,
        mappings=column_mappings,
        source_roots=source_roots,
        default_on_missing=default_on_missing,
        node_name=node_name,
    )
    _validate_key_column_values_present(
        row_payload=row_payload,
        key_columns=key_columns,
        node_name=node_name,
    )

    engine = _create_engine_for_database_url(
        database_url=database_url,
        database_kind=database_kind,
        connect_timeout_seconds=connect_timeout_seconds,
    )
    try:
        with Session(bind=engine, autoflush=False, expire_on_commit=False) as session:
            _apply_statement_timeout(
                session=session,
                database_kind=database_kind,
                statement_timeout_seconds=statement_timeout_seconds,
                node_name=node_name,
            )
            table = _reflect_target_table(
                session=session,
                table_name=table_name,
                schema_name=schema_name,
                key_columns=key_columns,
                row_payload=row_payload,
                node_name=node_name,
            )
            _validate_conflict_target_columns(
                engine=engine,
                table_name=table_name,
                schema_name=schema_name,
                key_columns=key_columns,
                node_name=node_name,
            )
            update_columns = _resolve_update_columns(
                row_payload=row_payload,
                key_columns=key_columns,
                update_columns_parameter=update_columns_parameter,
                skip_if_no_update_columns=skip_if_no_update_columns,
                table=table,
                node_name=node_name,
            )
            if update_columns is None:
                return _build_skip_result(
                    database_kind=database_kind,
                    table_name=table_name,
                    schema_name=schema_name,
                    key_columns=key_columns,
                    primary_source_kind=primary_source_kind,
                    row_payload=row_payload,
                    node_name=node_name,
                )
            statement = _build_upsert_statement(
                database_kind=database_kind,
                table=table,
                row_payload=row_payload,
                key_columns=key_columns,
                update_columns=update_columns,
                node_name=node_name,
            )
            execution_result = session.execute(statement)
            session.commit()
            affected_row_count = execution_result.rowcount
            if not isinstance(affected_row_count, int) or affected_row_count < 0:
                affected_row_count = None
    except SQLAlchemyError as exc:
        raise ServiceError(
            "本地数据库 upsert 失败",
            code="local_db_upsert_failed",
            status_code=502,
            details={
                "node_id": request.node_id,
                "table_name": table_name,
                "schema_name": schema_name,
                "database_kind": database_kind,
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
            },
        ) from exc
    finally:
        engine.dispose()

    return {
        "result": build_value_payload(
            {
                "database_kind": database_kind,
                "table_name": table_name,
                "schema_name": schema_name,
                "key_columns": list(key_columns),
                "update_columns": list(update_columns),
                "row_source": primary_source_kind,
                "affected_row_count": affected_row_count,
                "skipped": False,
                "written_row": row_payload,
                "operation": "upsert_attempted",
            }
        ),
        "prepared_row": build_value_payload(row_payload),
    }


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
            details={"provided_sources": [source_kind for source_kind, _ in primary_sources]},
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
        raise InvalidRequestError(f"{node_name} 的输入 {input_name} 必须是对象 value payload")
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
    exists, resolved_value = try_extract_value_by_path(root=source_root, path=source_path)
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


def _read_column_mappings(*, raw_value: object, node_name: str) -> tuple[ColumnMappingConfig, ...]:
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
        raise InvalidRequestError(f"{node_name} 的 column_mappings[{mapping_index}] 必须是对象")
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
        raise InvalidRequestError(f"{node_name} 的 {field_prefix}.literal_value 不能为空")
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


def _read_source_kind(*, raw_value: object, node_name: str, field_name: str) -> SourceKind:
    """读取来源域。"""

    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"result", "workflow_result", "summary", "request", "literal"}:
        raise InvalidRequestError(
            f"{node_name} 的 {field_name} 不支持当前取值",
            details={"source_kind": raw_value},
        )
    return normalized_value  # type: ignore[return-value]


def _read_database_kind(*, database_url: str, node_name: str) -> DatabaseKind:
    """按 URL 识别目标数据库类型。"""

    try:
        parsed_url = make_url(database_url)
    except Exception as exc:
        raise InvalidRequestError(
            f"{node_name} 的 database_url 不是有效的 SQLAlchemy URL",
            details={"database_url": database_url},
        ) from exc

    normalized_driver_name = parsed_url.drivername.split("+", 1)[0].lower()
    if normalized_driver_name == "sqlite":
        return "sqlite"
    if normalized_driver_name == "postgresql":
        return "postgresql"
    if normalized_driver_name == "mysql":
        return "mysql"
    raise InvalidRequestError(
        f"{node_name} 当前仅支持 SQLite / PostgreSQL / MySQL",
        details={"drivername": parsed_url.drivername},
    )


def _create_engine_for_database_url(
    *,
    database_url: str,
    database_kind: DatabaseKind,
    connect_timeout_seconds: float | None,
) -> Engine:
    """按受限规则创建 SQLAlchemy Engine。"""

    parsed_url: URL = make_url(database_url)
    _prepare_sqlite_parent_directory(parsed_url=parsed_url)

    engine_options: dict[str, object] = {"future": True}
    connect_args: dict[str, object] = {}
    if database_kind == "sqlite":
        connect_args["check_same_thread"] = False
        if connect_timeout_seconds is not None:
            connect_args["timeout"] = connect_timeout_seconds
        if parsed_url.database in (None, ":memory:"):
            engine_options["poolclass"] = StaticPool
    elif connect_timeout_seconds is not None:
        connect_args["connect_timeout"] = max(1, int(ceil(connect_timeout_seconds)))

    if connect_args:
        engine_options["connect_args"] = connect_args
    return create_engine(database_url, **engine_options)


def _prepare_sqlite_parent_directory(*, parsed_url: URL) -> None:
    """为 SQLite 文件数据库预创建父目录。"""

    if parsed_url.drivername.split("+", 1)[0].lower() != "sqlite" or parsed_url.database in (None, ":memory:"):
        return
    database_path = Path(parsed_url.database)
    database_path.parent.mkdir(parents=True, exist_ok=True)


def _apply_statement_timeout(
    *,
    session: Session,
    database_kind: DatabaseKind,
    statement_timeout_seconds: float | None,
    node_name: str,
) -> None:
    """按 dialect 尝试设置语句超时。"""

    if statement_timeout_seconds is None:
        return
    if database_kind != "postgresql":
        raise InvalidRequestError(
            f"{node_name} 当前仅在 PostgreSQL 支持 statement_timeout_seconds",
            details={"database_kind": database_kind},
        )
    timeout_milliseconds = max(1, int(ceil(statement_timeout_seconds * 1000)))
    session.execute(
        text("SET LOCAL statement_timeout = :timeout_ms"),
        {"timeout_ms": timeout_milliseconds},
    )


def _reflect_target_table(
    *,
    session: Session,
    table_name: str,
    schema_name: str | None,
    key_columns: tuple[str, ...],
    row_payload: dict[str, object],
    node_name: str,
) -> Table:
    """校验并反射目标表。"""

    bind = session.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(table_name, schema=schema_name):
        raise InvalidRequestError(
            f"{node_name} 的目标表不存在",
            details={"table_name": table_name, "schema_name": schema_name},
        )
    metadata = MetaData()
    table = Table(
        table_name,
        metadata,
        schema=schema_name,
        autoload_with=bind,
    )
    table_column_names = set(table.columns.keys())
    for key_column in key_columns:
        if key_column not in table_column_names:
            raise InvalidRequestError(
                f"{node_name} 的 key_columns 包含不存在的列",
                details={"column_name": key_column, "table_name": table_name},
            )
    for column_name in row_payload:
        if column_name not in table_column_names:
            raise InvalidRequestError(
                f"{node_name} 的行记录包含目标表中不存在的列",
                details={"column_name": column_name, "table_name": table_name},
            )
    return table


def _validate_conflict_target_columns(
    *,
    engine: Engine,
    table_name: str,
    schema_name: str | None,
    key_columns: tuple[str, ...],
    node_name: str,
) -> None:
    """校验 key_columns 对应真实唯一键或主键。"""

    inspector = inspect(engine)
    if _columns_match(
        candidate_columns=tuple(
            inspector.get_pk_constraint(table_name, schema=schema_name).get("constrained_columns") or ()
        ),
        expected_columns=key_columns,
    ):
        return
    for unique_constraint in inspector.get_unique_constraints(table_name, schema=schema_name):
        if _columns_match(
            candidate_columns=tuple(unique_constraint.get("column_names") or ()),
            expected_columns=key_columns,
        ):
            return
    for index_metadata in inspector.get_indexes(table_name, schema=schema_name):
        if not index_metadata.get("unique"):
            continue
        if _columns_match(
            candidate_columns=tuple(index_metadata.get("column_names") or ()),
            expected_columns=key_columns,
        ):
            return
    raise InvalidRequestError(
        f"{node_name} 的 key_columns 必须对应目标表中的主键或唯一约束",
        details={"table_name": table_name, "schema_name": schema_name, "key_columns": list(key_columns)},
    )


def _columns_match(*, candidate_columns: tuple[str, ...], expected_columns: tuple[str, ...]) -> bool:
    """判断两组列是否表示同一组唯一键。"""

    if not candidate_columns or len(candidate_columns) != len(expected_columns):
        return False
    return set(candidate_columns) == set(expected_columns)


def _resolve_update_columns(
    *,
    row_payload: dict[str, object],
    key_columns: tuple[str, ...],
    update_columns_parameter: tuple[str, ...] | None,
    skip_if_no_update_columns: bool,
    table: Table,
    node_name: str,
) -> tuple[str, ...] | None:
    """解析最终允许更新的列集合。"""

    allowed_column_names = set(table.columns.keys())
    key_column_names = set(key_columns)
    if update_columns_parameter is None:
        update_columns = tuple(
            column_name
            for column_name in row_payload.keys()
            if column_name not in key_column_names
        )
    else:
        update_columns = update_columns_parameter

    normalized_columns: list[str] = []
    for column_name in update_columns:
        if column_name not in allowed_column_names:
            raise InvalidRequestError(
                f"{node_name} 的 update_columns 包含目标表中不存在的列",
                details={"column_name": column_name},
            )
        if column_name not in row_payload:
            raise InvalidRequestError(
                f"{node_name} 的 update_columns 包含当前行记录中不存在的列",
                details={"column_name": column_name},
            )
        if column_name in key_column_names:
            raise InvalidRequestError(
                f"{node_name} 的 update_columns 不能包含 key_columns",
                details={"column_name": column_name},
            )
        if column_name not in normalized_columns:
            normalized_columns.append(column_name)

    if normalized_columns:
        return tuple(normalized_columns)
    if skip_if_no_update_columns:
        return None
    raise InvalidRequestError(f"{node_name} 缺少可更新列")


def _build_upsert_statement(
    *,
    database_kind: DatabaseKind,
    table: Table,
    row_payload: dict[str, object],
    key_columns: tuple[str, ...],
    update_columns: tuple[str, ...],
    node_name: str,
) -> object:
    """按 dialect 构造受限 upsert 语句。"""

    if database_kind == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        insert_statement = sqlite_insert(table).values(**row_payload)
        return insert_statement.on_conflict_do_update(
            index_elements=[table.c[column_name] for column_name in key_columns],
            set_={column_name: insert_statement.excluded[column_name] for column_name in update_columns},
        )
    if database_kind == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as postgresql_insert

        insert_statement = postgresql_insert(table).values(**row_payload)
        return insert_statement.on_conflict_do_update(
            index_elements=[table.c[column_name] for column_name in key_columns],
            set_={column_name: insert_statement.excluded[column_name] for column_name in update_columns},
        )
    if database_kind == "mysql":
        from sqlalchemy.dialects.mysql import insert as mysql_insert

        insert_statement = mysql_insert(table).values(**row_payload)
        return insert_statement.on_duplicate_key_update(
            **{column_name: insert_statement.inserted[column_name] for column_name in update_columns}
        )
    raise InvalidRequestError(
        f"{node_name} 当前不支持指定数据库类型",
        details={"database_kind": database_kind},
    )


def _build_skip_result(
    *,
    database_kind: DatabaseKind,
    table_name: str,
    schema_name: str | None,
    key_columns: tuple[str, ...],
    primary_source_kind: str,
    row_payload: dict[str, object],
    node_name: str,
) -> dict[str, object]:
    """构造无可更新列时的跳过结果。"""

    return {
        "result": build_value_payload(
            {
                "database_kind": database_kind,
                "table_name": table_name,
                "schema_name": schema_name,
                "key_columns": list(key_columns),
                "row_source": primary_source_kind,
                "affected_row_count": 0,
                "skipped": True,
                "skip_reason": "no_update_columns",
                "written_row": row_payload,
                "operation": "upsert_skipped",
                "node_name": node_name,
            }
        ),
        "prepared_row": build_value_payload(row_payload),
    }


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


def _normalize_row_cell_value(*, raw_value: object, node_name: str, field_name: str) -> object:
    """把列值限制到第一阶段允许的标量范围。"""

    if raw_value is None or isinstance(raw_value, (str, int, float, bool)):
        return raw_value
    raise InvalidRequestError(
        f"{node_name} 的 {field_name} 当前只支持标量或 null",
        details={"value_type": raw_value.__class__.__name__},
    )


def _read_on_missing_policy(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
    default_value: OnMissingPolicy,
) -> OnMissingPolicy:
    """读取缺失策略，未提供时使用默认值。"""

    if raw_value is None:
        return default_value
    return _read_optional_on_missing_policy(
        raw_value=raw_value,
        node_name=node_name,
        field_name=field_name,
    ) or default_value


def _read_optional_on_missing_policy(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> OnMissingPolicy | None:
    """读取可选缺失策略。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"error", "skip", "null"}:
        raise InvalidRequestError(
            f"{node_name} 的 {field_name} 不支持当前取值",
            details={"on_missing": raw_value},
        )
    return normalized_value  # type: ignore[return-value]


def _read_optional_object_parameter(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> dict[str, object]:
    """读取可选对象参数。"""

    if raw_value is None:
        return {}
    normalized_value = build_value_payload(raw_value)["value"]
    if not isinstance(normalized_value, dict):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是对象")
    return normalized_value


def _read_required_non_empty_string(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> str:
    """读取必填非空字符串。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是非空字符串")
    return raw_value.strip()


def _read_optional_non_empty_string(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> str | None:
    """读取可选非空字符串。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是字符串")
    normalized_value = raw_value.strip()
    return normalized_value or None


def _read_required_string_list(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
    require_non_empty: bool,
) -> tuple[str, ...]:
    """读取必填字符串列表。"""

    values = _read_optional_string_list(
        raw_value=raw_value,
        node_name=node_name,
        field_name=field_name,
    )
    if values is None or (require_non_empty and not values):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 至少需要 1 项")
    return values


def _read_optional_string_list(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> tuple[str, ...] | None:
    """读取可选字符串列表。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, list):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是数组")
    normalized_values: list[str] = []
    for index, item in enumerate(raw_value):
        if not isinstance(item, str) or not item.strip():
            raise InvalidRequestError(
                f"{node_name} 的 {field_name}[{index}] 必须是非空字符串"
            )
        normalized_item = item.strip()
        if normalized_item not in normalized_values:
            normalized_values.append(normalized_item)
    return tuple(normalized_values)


def _read_boolean_parameter(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
    default_value: bool,
) -> bool:
    """读取布尔参数。"""

    if raw_value is None:
        return default_value
    if not isinstance(raw_value, bool):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是布尔值")
    return raw_value


def _read_optional_positive_float(
    *,
    raw_value: object,
    node_name: str,
    field_name: str,
) -> float | None:
    """读取可选正浮点参数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须是数字")
    normalized_value = float(raw_value)
    if normalized_value <= 0:
        raise InvalidRequestError(f"{node_name} 的 {field_name} 必须大于 0")
    return normalized_value
