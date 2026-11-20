"""添加训练、转换任务提交回执。"""

import sqlalchemy as sa
from alembic import op

revision = "90ab3916f4cb"
down_revision = "c0f3e7a5b129"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建独立回执表，兼容已由服务初始化的开发数据库。"""
    if sa.inspect(op.get_bind()).has_table("model_submission_receipts"):
        return
    op.create_table(
        "model_submission_receipts",
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("principal_id", sa.String(128), nullable=False),
        sa.Column("submission_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(128), nullable=True),
        sa.PrimaryKeyConstraint("project_id", "principal_id", "submission_id"),
    )


def downgrade() -> None:
    """移除回执表，不改动任务和产物。"""
    op.drop_table("model_submission_receipts")
