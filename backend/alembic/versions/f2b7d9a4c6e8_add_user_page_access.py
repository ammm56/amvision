"""增加账号页面权限，保留旧账号兼容模式。"""

from alembic import op
import sqlalchemy as sa

revision = "f2b7d9a4c6e8"
down_revision = "e7a9b1c3d5f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """新增可空 JSON 字段，旧数据保持 SQL NULL。"""
    # 初始基线通过当前 ORM create_all 建表；全新发行库可能已包含该列。
    columns = sa.inspect(op.get_bind()).get_columns("auth_users")
    existing = next((column for column in columns if column["name"] == "allowed_pages_json"), None)
    if existing is not None:
        if not isinstance(existing["type"], sa.JSON) or not existing["nullable"]:
            raise RuntimeError("账号页面权限字段结构不一致")
        return
    op.add_column(
        "auth_users",
        sa.Column("allowed_pages_json", sa.JSON(none_as_null=True), nullable=True),
    )


def downgrade() -> None:
    """存在显式页面授权时拒绝丢弃限制。"""
    users = sa.table(
        "auth_users", sa.column("allowed_pages_json", sa.JSON(none_as_null=True))
    )
    if (
        op.get_bind()
        .execute(
            sa.select(users.c.allowed_pages_json)
            .where(users.c.allowed_pages_json.is_not(None))
            .limit(1)
        )
        .first()
        is not None
    ):
        raise RuntimeError("存在显式页面权限，不能降级删除授权字段")
    op.drop_column("auth_users", "allowed_pages_json")
