"""本地数据库输出节点数据库访问和 upsert 构造。"""

from __future__ import annotations

from math import ceil
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.errors import InvalidRequestError
from custom_nodes.output_local_db_nodes.backend.runtime.types import DatabaseKind


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

    if parsed_url.drivername.split("+", 1)[
        0
    ].lower() != "sqlite" or parsed_url.database in (None, ":memory:"):
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
            inspector.get_pk_constraint(table_name, schema=schema_name).get(
                "constrained_columns"
            )
            or ()
        ),
        expected_columns=key_columns,
    ):
        return
    for unique_constraint in inspector.get_unique_constraints(
        table_name, schema=schema_name
    ):
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
        details={
            "table_name": table_name,
            "schema_name": schema_name,
            "key_columns": list(key_columns),
        },
    )


def _columns_match(
    *, candidate_columns: tuple[str, ...], expected_columns: tuple[str, ...]
) -> bool:
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
            set_={
                column_name: insert_statement.excluded[column_name]
                for column_name in update_columns
            },
        )
    if database_kind == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as postgresql_insert

        insert_statement = postgresql_insert(table).values(**row_payload)
        return insert_statement.on_conflict_do_update(
            index_elements=[table.c[column_name] for column_name in key_columns],
            set_={
                column_name: insert_statement.excluded[column_name]
                for column_name in update_columns
            },
        )
    if database_kind == "mysql":
        from sqlalchemy.dialects.mysql import insert as mysql_insert

        insert_statement = mysql_insert(table).values(**row_payload)
        return insert_statement.on_duplicate_key_update(
            **{
                column_name: insert_statement.inserted[column_name]
                for column_name in update_columns
            }
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
