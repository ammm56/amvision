"""添加与业务记录独立的资源删除恢复清单。"""

from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone

revision = "c5e7f9a1b3d6"
down_revision = "b4d6f8a2c5e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """新表不修改既有业务数据。"""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if not inspector.has_table("resource_deletions"):
        op.create_table(
            "resource_deletions",
            sa.Column("operation_id", sa.String(128), primary_key=True),
            sa.Column("project_id", sa.String(128), nullable=False),
            sa.Column("state", sa.String(32), nullable=False),
            sa.Column("plan_json", sa.JSON(), nullable=False),
            sa.Column("error", sa.String(2048), nullable=True),
            sa.Column("updated_at", sa.String(64), nullable=False),
        )

    # 开发热重载可能已创建不含回执时间的早期表；create_all 不会补列。
    # 通过默认值回填既有行，保留未完成删除清单，不重建或清空该表。
    column_names = {
        column["name"]
        for column in sa.inspect(connection).get_columns("resource_deletions")
    }
    if "updated_at" not in column_names:
        op.add_column(
            "resource_deletions",
            sa.Column(
                "updated_at",
                sa.String(64),
                nullable=False,
                server_default=sa.literal(datetime.now(timezone.utc).isoformat()),
            ),
        )

    # 初始迁移使用当前 metadata 创建新库，因此新表可能已提前存在；
    # 这里只补齐缺失索引，兼容新库与从旧 revision 升级的数据库。
    index_names = {
        str(index["name"])
        for index in sa.inspect(connection).get_indexes("resource_deletions")
        if index.get("name") is not None
    }
    if "ix_resource_deletions_project_id" not in index_names:
        op.create_index(
            "ix_resource_deletions_project_id", "resource_deletions", ["project_id"]
        )
    if "ix_resource_deletions_state" not in index_names:
        op.create_index("ix_resource_deletions_state", "resource_deletions", ["state"])
    if "ix_resource_deletions_updated_at" not in index_names:
        op.create_index(
            "ix_resource_deletions_updated_at", "resource_deletions", ["updated_at"]
        )


def downgrade() -> None:
    """未完成的物理删除清单不可随降级丢失。"""
    connection = op.get_bind()
    table = sa.table("resource_deletions", sa.column("operation_id"))
    if connection.execute(sa.select(table.c.operation_id).limit(1)).first():
        raise RuntimeError("仍有待完成资源删除，不能降级数据库")
    op.drop_table("resource_deletions")
