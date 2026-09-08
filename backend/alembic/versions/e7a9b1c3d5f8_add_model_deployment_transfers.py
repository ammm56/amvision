"""新增部署包操作和导入模型归属；历史模型保持原归属。"""

from alembic import op
import sqlalchemy as sa

revision = "e7a9b1c3d5f8"
down_revision = "d6f8a0b2c4e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """仅添加表，ModelVersion.source_kind 为既有字符串列。"""
    inspector = sa.inspect(op.get_bind())
    expected = {
        "model_deployment_transfers": {"operation_id", "project_id", "direction", "state", "payload_json", "created_at", "updated_at"},
        "imported_model_artifacts": {"artifact_id", "project_id", "model_version_id", "model_build_id", "object_prefix", "fingerprint", "provenance_json"},
    }
    if all(inspector.has_table(name) for name in expected):
        # 接管历史 create_all 数据库时两表已存在，必须核对后再接纳。
        for name, columns in expected.items():
            if {c["name"] for c in inspector.get_columns(name)} != columns:
                raise RuntimeError(f"模型传递表结构不一致：{name}")
        return
    op.create_table("model_deployment_transfers",
        sa.Column("operation_id", sa.String(128), primary_key=True),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.String(64), nullable=False))
    for column in ("project_id", "state", "updated_at"):
        op.create_index(f"ix_model_deployment_transfers_{column}", "model_deployment_transfers", [column])
    op.create_table("imported_model_artifacts",
        sa.Column("artifact_id", sa.String(128), primary_key=True),
        sa.Column("project_id", sa.String(128), nullable=False),
        sa.Column("model_version_id", sa.String(128), sa.ForeignKey("model_versions.model_version_id", ondelete="CASCADE"), unique=True),
        sa.Column("model_build_id", sa.String(128), sa.ForeignKey("model_builds.model_build_id", ondelete="CASCADE"), unique=True),
        sa.Column("object_prefix", sa.String(1024), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.CheckConstraint("(model_version_id IS NOT NULL AND model_build_id IS NULL) OR (model_version_id IS NULL AND model_build_id IS NOT NULL)", name="ck_imported_model_artifact_one_owner"))
    op.create_index("ix_imported_model_artifacts_project_id", "imported_model_artifacts", ["project_id"])


def downgrade() -> None:
    """存在导入模型或未清理操作时禁止丢弃归属。"""
    connection = op.get_bind()
    for name in ("imported_model_artifacts", "model_deployment_transfers"):
        table = sa.table(name, sa.column("project_id"))
        if connection.execute(sa.select(table.c.project_id).limit(1)).first():
            raise RuntimeError("请先清理导入模型和传递操作，再降级数据库")
    op.drop_table("imported_model_artifacts")
    op.drop_table("model_deployment_transfers")
