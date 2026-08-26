"""fill local shared TriggerSource timeout

Revision ID: b4d6f8a2c5e1
Revises: e2a7c9d1f4b6
Create Date: 2026-08-26 15:00:00.000000
"""

from __future__ import annotations

from hashlib import sha256
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "b4d6f8a2c5e1"
down_revision = "e2a7c9d1f4b6"
branch_labels = None
depends_on = None


_TABLE = "workflow_trigger_sources"
_DEFAULT_REPLY_TIMEOUT_SECONDS = 30


def upgrade() -> None:
    """只为 local-shared-memory sync source 填入唯一具体 timeout。"""

    bind = op.get_bind()
    inspector = inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    table = sa.table(
        _TABLE,
        sa.column("trigger_source_id", sa.String()),
        sa.column("trigger_kind", sa.String()),
        sa.column("submit_mode", sa.String()),
        sa.column("reply_timeout_seconds", sa.Integer()),
        sa.column("metadata_json", sa.JSON()),
    )
    bind.execute(
        sa.update(table)
        .where(table.c.trigger_kind == "local-shared-memory")
        .where(table.c.submit_mode == "sync")
        .where(table.c.reply_timeout_seconds.is_(None))
        .values(reply_timeout_seconds=_DEFAULT_REPLY_TIMEOUT_SECONDS)
    )
    rows = bind.execute(
        sa.select(
            table.c.trigger_source_id,
            table.c.reply_timeout_seconds,
            table.c.metadata_json,
        )
        .where(table.c.trigger_kind == "local-shared-memory")
        .where(table.c.submit_mode == "sync")
    )
    for trigger_source_id, reply_timeout_seconds, raw_metadata in rows:
        metadata = _read_json_object(raw_metadata)
        raw_plan = metadata.get("trigger_response_plan")
        if not isinstance(raw_plan, dict):
            continue
        plan = dict(raw_plan)
        plan["reply_timeout_seconds"] = int(
            reply_timeout_seconds or _DEFAULT_REPLY_TIMEOUT_SECONDS
        )
        plan["response_ack_timeout_seconds"] = 30.0
        plan["plan_generation"] = max(1, int(plan.get("plan_generation") or 1)) + 1
        plan.pop("plan_fingerprint", None)
        plan["plan_fingerprint"] = _fingerprint(plan)
        metadata["trigger_response_plan"] = plan
        bind.execute(
            sa.update(table)
            .where(table.c.trigger_source_id == trigger_source_id)
            .values(metadata_json=metadata)
        )


def downgrade() -> None:
    """数据规范化不可区分历史空值与用户显式 30 秒，回退不破坏数据。"""


def _read_json_object(value: object) -> dict[str, object]:
    """读取跨 SQLite/MySQL/PostgreSQL 返回形态一致的 JSON 对象。"""

    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _fingerprint(payload: dict[str, object]) -> str:
    """按运行时相同规则计算稳定 response plan fingerprint。"""

    normalized = dict(payload)
    normalized.pop("plan_fingerprint", None)
    return sha256(
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
