"""删除持久化 PreviewRun；编辑器预览改为有界内存会话。"""

from alembic import op
import sqlalchemy as sa

revision = "a8d6c4e2b019"
down_revision = "f2b7d9a4c6e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """不触及正式 Runtime/Run；旧策略保留参数，统一为 runtime-default。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("workflow_preview_runs"):
        op.drop_table("workflow_preview_runs")
    if inspector.has_table("workflow_execution_policies"):
        policies = sa.table("workflow_execution_policies", sa.column("policy_kind", sa.String))
        bind.execute(policies.update().where(policies.c.policy_kind == "preview-default").values(policy_kind="runtime-default"))


def downgrade() -> None:
    """仅恢复旧表结构；已删除的临时运行数据需从迁移备份恢复。"""
    if sa.inspect(op.get_bind()).has_table("workflow_preview_runs"):
        return
    op.create_table("workflow_preview_runs",
        sa.Column("preview_run_id", sa.String(128), primary_key=True),
        sa.Column("project_id", sa.String(128), nullable=False, index=True),
        sa.Column("application_id", sa.String(128), nullable=False, index=True),
        sa.Column("source_kind", sa.String(64), nullable=False),
        sa.Column("application_snapshot_object_key", sa.String(1024), nullable=False),
        sa.Column("template_snapshot_object_key", sa.String(1024), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, index=True),
        sa.Column("created_at", sa.String(64), nullable=False, index=True),
        sa.Column("started_at", sa.String(64)), sa.Column("finished_at", sa.String(64)),
        sa.Column("created_by", sa.String(128)), sa.Column("timeout_seconds", sa.Integer, nullable=False),
        sa.Column("outputs_json", sa.JSON, nullable=False), sa.Column("template_outputs_json", sa.JSON, nullable=False),
        sa.Column("node_records_json", sa.JSON, nullable=False), sa.Column("metadata_json", sa.JSON, nullable=False),
        sa.Column("error_message", sa.String(2048)), sa.Column("retention_until", sa.String(64)))
