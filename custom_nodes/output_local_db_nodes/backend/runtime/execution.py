"""本地数据库输出节点执行入口。"""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.output_local_db_nodes.backend.runtime.database import (
    _apply_statement_timeout,
    _build_skip_result,
    _build_upsert_statement,
    _create_engine_for_database_url,
    _read_database_kind,
    _reflect_target_table,
    _resolve_update_columns,
    _validate_conflict_target_columns,
)
from custom_nodes.output_local_db_nodes.backend.runtime.parameters import (
    _read_boolean_parameter,
    _read_on_missing_policy,
    _read_optional_non_empty_string,
    _read_optional_object_parameter,
    _read_optional_positive_float,
    _read_optional_string_list,
    _read_required_non_empty_string,
    _read_required_string_list,
)
from custom_nodes.output_local_db_nodes.backend.runtime.payloads import (
    _build_row_payload,
    _read_column_mappings,
    _read_source_roots,
    _validate_key_column_values_present,
)


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
