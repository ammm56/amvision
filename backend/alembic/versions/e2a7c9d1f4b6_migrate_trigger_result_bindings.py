"""migrate Workflow Trigger result bindings

Revision ID: e2a7c9d1f4b6
Revises: d8e4f6a1b3c7
Create Date: 2026-08-24 18:00:00.000000
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "e2a7c9d1f4b6"
down_revision = "d8e4f6a1b3c7"
branch_labels = None
depends_on = None


_TABLE = "workflow_trigger_sources"


def upgrade() -> None:
    """把开发期单 binding 结构原子收敛为有序 binding 列表。"""

    bind = op.get_bind()
    inspector = inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    table = sa.table(
        _TABLE,
        sa.column("trigger_source_id", sa.String()),
        sa.column("result_mode", sa.String()),
        sa.column("result_mapping_json", sa.JSON()),
    )
    for trigger_source_id, result_mode, raw_mapping in bind.execute(
        sa.select(
            table.c.trigger_source_id,
            table.c.result_mode,
            table.c.result_mapping_json,
        )
    ):
        mapping = _read_mapping(raw_mapping)
        if result_mode == "event-only":
            bindings = []
        elif "result_bindings" in mapping:
            bindings = _normalize_bindings(mapping.get("result_bindings"))
        else:
            binding = mapping.get("result_binding")
            bindings = [binding.strip()] if isinstance(binding, str) and binding.strip() else []
        bind.execute(
            sa.update(table)
            .where(table.c.trigger_source_id == trigger_source_id)
            .values(result_mapping_json={"result_bindings": bindings})
        )


def downgrade() -> None:
    """为数据库回退保留第一个 binding；运行时代码不提供双读兼容。"""

    bind = op.get_bind()
    inspector = inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    table = sa.table(
        _TABLE,
        sa.column("trigger_source_id", sa.String()),
        sa.column("result_mapping_json", sa.JSON()),
    )
    for trigger_source_id, raw_mapping in bind.execute(
        sa.select(table.c.trigger_source_id, table.c.result_mapping_json)
    ):
        bindings = _normalize_bindings(_read_mapping(raw_mapping).get("result_bindings"))
        bind.execute(
            sa.update(table)
            .where(table.c.trigger_source_id == trigger_source_id)
            .values(
                result_mapping_json={
                    "result_binding": bindings[0] if bindings else "workflow_result"
                }
            )
        )


def _read_mapping(value: object) -> dict[str, object]:
    """兼容 Alembic driver 返回 dict 或 JSON 字符串。"""

    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(decoded) if isinstance(decoded, dict) else {}
    return {}


def _normalize_bindings(value: object) -> list[str]:
    """规范化并保持 binding 顺序。"""

    if not isinstance(value, list | tuple):
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or item.strip() in result:
            continue
        result.append(item.strip())
    return result
