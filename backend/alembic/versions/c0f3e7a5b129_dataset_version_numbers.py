"""为数据集增加稳定的自动版本序号，不更改已有资源 id 或文件路径。"""

from collections import defaultdict

from alembic import op
import sqlalchemy as sa

revision = "c0f3e7a5b129"
down_revision = "b9e2d6f4a018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """按历史创建时间补齐 v1/v2，并保存不会因版本删除而回退的计数器。"""
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("datasets")}
    if "version_sequence" not in columns:
        op.add_column(
            "datasets",
            sa.Column(
                "version_sequence", sa.Integer(), nullable=False, server_default="0"
            ),
        )
    columns = {c["name"] for c in sa.inspect(bind).get_columns("dataset_versions")}
    new_numbers = "version_number" not in columns
    if new_numbers:
        op.add_column(
            "dataset_versions",
            sa.Column(
                "version_number", sa.Integer(), nullable=False, server_default="1"
            ),
        )
    metadata = sa.MetaData()
    datasets = sa.Table("datasets", metadata, autoload_with=bind)
    versions = sa.Table("dataset_versions", metadata, autoload_with=bind)
    groups = defaultdict(list)
    for row in bind.execute(sa.select(versions)).mappings():
        groups[(row["project_id"], row["dataset_id"])].append(row)
    for (project_id, dataset_id), rows in groups.items():
        rows.sort(
            key=lambda row: (
                str((row["metadata_json"] or {}).get("created_at") or ""),
                row["dataset_version_id"],
            )
        )
        for number, row in enumerate(rows, 1):
            if new_numbers:
                bind.execute(
                    versions.update()
                    .where(versions.c.dataset_version_id == row["dataset_version_id"])
                    .values(version_number=number)
                )
        maximum = (
            len(rows) if new_numbers else max(row["version_number"] for row in rows)
        )
        bind.execute(
            datasets.update()
            .where(
                datasets.c.project_id == project_id,
                datasets.c.dataset_id == dataset_id,
                datasets.c.version_sequence < maximum,
            )
            .values(version_sequence=maximum)
        )
    name = "uq_dataset_version_number"
    indexes = sa.inspect(bind).get_indexes("dataset_versions")
    if name not in {item["name"] for item in indexes}:
        op.create_index(
            name,
            "dataset_versions",
            ["project_id", "dataset_id", "version_number"],
            unique=True,
        )


def downgrade() -> None:
    """仅移除显示序号及计数器，版本内容与引用保持不变。"""
    op.drop_index("uq_dataset_version_number", table_name="dataset_versions")
    with op.batch_alter_table("dataset_versions") as batch:
        batch.drop_column("version_number")
    with op.batch_alter_table("datasets") as batch:
        batch.drop_column("version_sequence")
