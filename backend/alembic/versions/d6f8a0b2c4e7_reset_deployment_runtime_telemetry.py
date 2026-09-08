"""重置旧 Deployment runtime 的错误累计值和转换时间。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "d6f8a0b2c4e7"
down_revision = "c5e7f9a1b3d6"
branch_labels = None
depends_on = None

_TABLE = "deployment_runtime_states"


def upgrade() -> None:
    """清空旧轮询逻辑产生的伪累计值，由后续真实状态边沿重新建立。"""

    runtime_states = sa.table(
        _TABLE,
        sa.column("restart_count", sa.Integer()),
        sa.column("last_started_at", sa.String(length=64)),
        sa.column("last_stopped_at", sa.String(length=64)),
    )
    op.execute(
        runtime_states.update().values(
            restart_count=0,
            last_started_at=None,
            last_stopped_at=None,
        )
    )


def downgrade() -> None:
    """旧错误遥测无法可靠恢复，降级只保留升级后的有效观测值。"""
