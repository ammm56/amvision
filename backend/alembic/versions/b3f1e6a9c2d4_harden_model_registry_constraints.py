"""harden model registry constraints

Revision ID: b3f1e6a9c2d4
Revises: a1c7e9d4f2b6
Create Date: 2026-08-13 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
import re
import warnings

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.exc import SAWarning


revision = "b3f1e6a9c2d4"
down_revision = "a1c7e9d4f2b6"
branch_labels = None
depends_on = None


def _constraint_names(table_name: str, kind: str) -> set[str]:
    """读取指定表中给定类型的具名约束。"""

    inspector = inspect(op.get_bind())
    if kind == "foreign_key" and op.get_bind().dialect.name == "sqlite":
        table_sql = op.get_bind().execute(
            sa.text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = :table_name"
            ),
            {"table_name": table_name},
        ).scalar_one_or_none()
        if not isinstance(table_sql, str):
            return set()
        return set(
            re.findall(
                r"CONSTRAINT\s+[\"`\[]?([A-Za-z0-9_]+)[\"`\]]?\s+FOREIGN\s+KEY",
                table_sql,
                flags=re.IGNORECASE,
            )
        )
    readers = {
        "unique": inspector.get_unique_constraints,
        "check": inspector.get_check_constraints,
        "foreign_key": inspector.get_foreign_keys,
    }
    with _suppress_sqlite_fk_name_warning():
        rows = readers[kind](table_name)
    return {str(row["name"]) for row in rows if row.get("name")}


@contextmanager
def _suppress_sqlite_fk_name_warning() -> Iterator[None]:
    """忽略 SQLite 无法从 PRAGMA 返回具名 FK 时的已知反射提示。"""

    if op.get_bind().dialect.name != "sqlite":
        yield
        return
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=(
                r"WARNING: SQL-parsed foreign key constraint .* "
                r"could not be located in PRAGMA foreign_keys.*"
            ),
            category=SAWarning,
        )
        yield


def _index_names(table_name: str) -> set[str]:
    """读取指定表中的具名索引。"""

    return {
        str(row["name"])
        for row in inspect(op.get_bind()).get_indexes(table_name)
        if row.get("name")
    }


def _foreign_key_signatures(
    table_name: str,
) -> set[tuple[tuple[str, ...], str, tuple[str, ...], str | None]]:
    """按字段、目标和删除动作读取外键，不依赖 SQLite 约束名反射。"""

    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        rows = connection.execute(
            sa.text(f'PRAGMA foreign_key_list("{table_name}")')
        ).mappings()
        grouped: dict[int, list[dict[str, object]]] = {}
        for row in rows:
            grouped.setdefault(int(row["id"]), []).append(dict(row))
        return {
            (
                tuple(
                    str(item["from"])
                    for item in sorted(items, key=lambda item: int(item["seq"]))
                ),
                str(items[0]["table"]),
                tuple(
                    str(item["to"])
                    for item in sorted(items, key=lambda item: int(item["seq"]))
                ),
                _normalize_foreign_key_action(items[0].get("on_delete")),
            )
            for items in grouped.values()
        }

    signatures = set()
    for item in inspect(connection).get_foreign_keys(table_name):
        signatures.add(
            (
                tuple(str(value) for value in item.get("constrained_columns") or ()),
                str(item["referred_table"]),
                tuple(str(value) for value in item.get("referred_columns") or ()),
                _normalize_foreign_key_action(
                    (item.get("options") or {}).get("ondelete")
                ),
            )
        )
    return signatures


def _normalize_foreign_key_action(value: object) -> str | None:
    """把数据库返回的默认 NO ACTION 统一为空动作。"""

    normalized = str(value or "").strip().upper()
    return None if normalized in {"", "NO ACTION"} else normalized


def _column_names(table_name: str) -> set[str]:
    """读取指定表中的字段名。"""

    return {
        str(row["name"])
        for row in inspect(op.get_bind()).get_columns(table_name)
    }


def _reject_duplicates(
    table_name: str,
    columns: Iterable[str],
    non_null_column: str | None = None,
) -> None:
    """创建唯一约束前拒绝既有重复数据，避免静默丢失。"""

    column_list = tuple(columns)
    group_columns = ", ".join(column_list)
    where_clause = (
        f"WHERE {non_null_column} IS NOT NULL" if non_null_column else ""
    )
    query = sa.text(
        f"SELECT {group_columns} FROM {table_name} {where_clause} "
        f"GROUP BY {group_columns} HAVING COUNT(*) > 1"
    )
    if op.get_bind().execute(query).first() is not None:
        raise RuntimeError(
            f"{table_name} 存在重复数据，无法安全增加唯一约束: {column_list!r}"
        )


def _upgrade_models() -> None:
    """增加跨数据库一致的 Model owner_key 和自然键约束。"""

    if "owner_key" not in _column_names("models"):
        op.add_column(
            "models",
            sa.Column("owner_key", sa.String(length=128), nullable=True),
        )
    op.get_bind().execute(
        sa.text(
            "UPDATE models SET owner_key = CASE "
            "WHEN project_id IS NULL THEN '__platform__' ELSE project_id END "
            "WHERE owner_key IS NULL OR owner_key = ''"
        )
    )
    natural_key = (
        "scope_kind",
        "owner_key",
        "model_name",
        "task_type",
        "model_scale",
    )
    _reject_duplicates(table_name="models", columns=natural_key)

    unique_names = _constraint_names("models", "unique")
    check_names = _constraint_names("models", "check")
    owner_column = next(
        row
        for row in inspect(op.get_bind()).get_columns("models")
        if row["name"] == "owner_key"
    )
    with _suppress_sqlite_fk_name_warning():
        with op.batch_alter_table("models") as batch_op:
            if bool(owner_column["nullable"]):
                batch_op.alter_column(
                    "owner_key",
                    existing_type=sa.String(length=128),
                    nullable=False,
                )
            if "ck_models_owner_key_matches_project" not in check_names:
                batch_op.create_check_constraint(
                    "ck_models_owner_key_matches_project",
                    "(project_id IS NULL AND owner_key = '__platform__') OR "
                    "(project_id IS NOT NULL AND owner_key = project_id)",
                )
            if "uq_models_owner_name_task_scale" not in unique_names:
                batch_op.create_unique_constraint(
                    "uq_models_owner_name_task_scale",
                    list(natural_key),
                )

    if "ix_models_catalog_lookup" not in _index_names("models"):
        op.create_index(
            "ix_models_catalog_lookup",
            "models",
            ["scope_kind", "owner_key", "task_type", "model_name", "model_scale"],
        )


def _upgrade_model_versions() -> None:
    """约束训练任务和父版本引用。"""

    _reject_duplicates(
        table_name="model_versions",
        columns=("training_task_id",),
        non_null_column="training_task_id",
    )
    unique_names = _constraint_names("model_versions", "unique")
    foreign_keys = _foreign_key_signatures("model_versions")
    with _suppress_sqlite_fk_name_warning():
        with op.batch_alter_table("model_versions") as batch_op:
            if "uq_model_versions_training_task" not in unique_names:
                batch_op.create_unique_constraint(
                    "uq_model_versions_training_task",
                    ["training_task_id"],
                )
            if (
                ("parent_version_id",),
                "model_versions",
                ("model_version_id",),
                "SET NULL",
            ) not in foreign_keys:
                batch_op.create_foreign_key(
                    "fk_model_versions_parent_version_id",
                    "model_versions",
                    ["parent_version_id"],
                    ["model_version_id"],
                    ondelete="SET NULL",
                )

    indexes = _index_names("model_versions")
    for name, columns in (
        ("ix_model_versions_training_task_id", ["training_task_id"]),
        ("ix_model_versions_parent_version_id", ["parent_version_id"]),
        ("ix_model_versions_model_source", ["model_id", "source_kind"]),
    ):
        if name not in indexes:
            op.create_index(name, "model_versions", columns)


def _upgrade_model_builds() -> None:
    """约束同一转换任务目标只登记一个 Build。"""

    target_columns = (
        "conversion_task_id",
        "build_format",
        "runtime_backend",
        "runtime_precision",
    )
    _reject_duplicates(
        table_name="model_builds",
        columns=target_columns,
        non_null_column="conversion_task_id",
    )
    unique_names = _constraint_names("model_builds", "unique")
    foreign_keys = _foreign_key_signatures("model_builds")
    with _suppress_sqlite_fk_name_warning():
        with op.batch_alter_table("model_builds") as batch_op:
            if "uq_model_builds_conversion_target" not in unique_names:
                batch_op.create_unique_constraint(
                    "uq_model_builds_conversion_target",
                    list(target_columns),
                )
            if (
                ("source_model_version_id",),
                "model_versions",
                ("model_version_id",),
                "CASCADE",
            ) not in foreign_keys:
                batch_op.create_foreign_key(
                    "fk_model_builds_source_model_version_id",
                    "model_versions",
                    ["source_model_version_id"],
                    ["model_version_id"],
                    ondelete="CASCADE",
                )

    indexes = _index_names("model_builds")
    for name, columns in (
        ("ix_model_builds_conversion_task_id", ["conversion_task_id"]),
        (
            "ix_model_builds_source_runtime",
            ["source_model_version_id", "runtime_backend", "runtime_precision"],
        ),
    ):
        if name not in indexes:
            op.create_index(name, "model_builds", columns)


def _upgrade_model_files() -> None:
    """约束版本或 Build 下文件逻辑名唯一和 Model 归属。"""

    _reject_duplicates(
        table_name="model_files",
        columns=("model_version_id", "file_type", "logical_name"),
        non_null_column="model_version_id",
    )
    _reject_duplicates(
        table_name="model_files",
        columns=("model_build_id", "file_type", "logical_name"),
        non_null_column="model_build_id",
    )
    unique_names = _constraint_names("model_files", "unique")
    check_names = _constraint_names("model_files", "check")
    foreign_keys = _foreign_key_signatures("model_files")
    with _suppress_sqlite_fk_name_warning():
        with op.batch_alter_table("model_files") as batch_op:
            if "ck_model_files_single_artifact_owner" not in check_names:
                batch_op.create_check_constraint(
                    "ck_model_files_single_artifact_owner",
                    "model_version_id IS NULL OR model_build_id IS NULL",
                )
            if "uq_model_files_version_logical_name" not in unique_names:
                batch_op.create_unique_constraint(
                    "uq_model_files_version_logical_name",
                    ["model_version_id", "file_type", "logical_name"],
                )
            if "uq_model_files_build_logical_name" not in unique_names:
                batch_op.create_unique_constraint(
                    "uq_model_files_build_logical_name",
                    ["model_build_id", "file_type", "logical_name"],
                )
            if (
                ("model_id",),
                "models",
                ("model_id",),
                "CASCADE",
            ) not in foreign_keys:
                batch_op.create_foreign_key(
                    "fk_model_files_model_id",
                    "models",
                    ["model_id"],
                    ["model_id"],
                    ondelete="CASCADE",
                )

    if "ix_model_files_model_type" not in _index_names("model_files"):
        op.create_index(
            "ix_model_files_model_type",
            "model_files",
            ["model_id", "file_type"],
        )


def upgrade() -> None:
    """加固 Model、ModelVersion、ModelBuild 和 ModelFile 约束。"""

    _upgrade_models()
    _upgrade_model_versions()
    _upgrade_model_builds()
    _upgrade_model_files()


def downgrade() -> None:
    """移除本 revision 增加的约束、索引和 owner_key。"""

    for table_name, index_names in (
        ("model_files", ("ix_model_files_model_type",)),
        (
            "model_builds",
            ("ix_model_builds_conversion_task_id", "ix_model_builds_source_runtime"),
        ),
        (
            "model_versions",
            (
                "ix_model_versions_training_task_id",
                "ix_model_versions_parent_version_id",
                "ix_model_versions_model_source",
            ),
        ),
        ("models", ("ix_models_catalog_lookup",)),
    ):
        existing = _index_names(table_name)
        for index_name in index_names:
            if index_name in existing:
                op.drop_index(index_name, table_name=table_name)

    model_file_foreign_keys = _constraint_names("model_files", "foreign_key")
    model_build_foreign_keys = _constraint_names("model_builds", "foreign_key")
    model_version_foreign_keys = _constraint_names("model_versions", "foreign_key")
    with _suppress_sqlite_fk_name_warning():
        with op.batch_alter_table("model_files") as batch_op:
            if "fk_model_files_model_id" in model_file_foreign_keys:
                batch_op.drop_constraint(
                    "fk_model_files_model_id",
                    type_="foreignkey",
                )
            batch_op.drop_constraint(
                "uq_model_files_build_logical_name",
                type_="unique",
            )
            batch_op.drop_constraint(
                "uq_model_files_version_logical_name",
                type_="unique",
            )
            batch_op.drop_constraint(
                "ck_model_files_single_artifact_owner",
                type_="check",
            )
        with op.batch_alter_table("model_builds") as batch_op:
            if (
                "fk_model_builds_source_model_version_id"
                in model_build_foreign_keys
            ):
                batch_op.drop_constraint(
                    "fk_model_builds_source_model_version_id",
                    type_="foreignkey",
                )
            batch_op.drop_constraint(
                "uq_model_builds_conversion_target",
                type_="unique",
            )
        with op.batch_alter_table("model_versions") as batch_op:
            if "fk_model_versions_parent_version_id" in model_version_foreign_keys:
                batch_op.drop_constraint(
                    "fk_model_versions_parent_version_id",
                    type_="foreignkey",
                )
            batch_op.drop_constraint(
                "uq_model_versions_training_task",
                type_="unique",
            )
        with op.batch_alter_table("models") as batch_op:
            batch_op.drop_constraint(
                "uq_models_owner_name_task_scale",
                type_="unique",
            )
            batch_op.drop_constraint(
                "ck_models_owner_key_matches_project",
                type_="check",
            )
            batch_op.drop_column("owner_key")
