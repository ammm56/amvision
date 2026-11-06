"""增加独立数据集信息及样本分页索引，保留现有版本身份和引用。"""

from datetime import datetime, timezone
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "b9e2d6f4a018"
down_revision = "a8d6c4e2b019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """从版本及导入记录补齐目录，不改写任何图片、标注或已有版本。"""
    bind = op.get_bind()
    metadata = sa.MetaData()
    if "datasets" in sa.inspect(bind).get_table_names():
        table = sa.Table("datasets", metadata, autoload_with=bind)
    else:
        table = op.create_table(
            "datasets",
            sa.Column("project_id", sa.String(128), primary_key=True),
            sa.Column("dataset_id", sa.String(128), primary_key=True),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("description", sa.String(2000), nullable=False),
            sa.Column("task_type", sa.String(64), nullable=False),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.Column("updated_at", sa.String(64), nullable=False),
            sa.Column("revision", sa.String(32), nullable=False),
        )
    versions = sa.Table("dataset_versions", metadata, autoload_with=bind)
    imports = sa.Table("dataset_imports", metadata, autoload_with=bind)
    entries = {}
    now = datetime.now(timezone.utc).isoformat()
    for row in bind.execute(sa.select(imports)).mappings():
        key = (row["project_id"], row["dataset_id"])
        entries.setdefault(key, (row["task_type"], row["created_at"]))
    for row in bind.execute(sa.select(versions)).mappings():
        key = (row["project_id"], row["dataset_id"])
        entries.setdefault(
            key, (row["task_type"], (row["metadata_json"] or {}).get("created_at", now))
        )
    for (project_id, dataset_id), (task_type, created_at) in entries.items():
        if bind.scalar(
            sa.select(sa.func.count())
            .select_from(table)
            .where(table.c.project_id == project_id, table.c.dataset_id == dataset_id)
        ):
            continue
        bind.execute(
            table.insert().values(
                project_id=project_id,
                dataset_id=dataset_id,
                display_name=dataset_id,
                description="",
                task_type=task_type,
                created_at=created_at,
                updated_at=created_at,
                revision=uuid4().hex,
            )
        )
    if "ix_dataset_samples_version_split_image" not in {
        item["name"] for item in sa.inspect(bind).get_indexes("dataset_samples")
    }:
        op.create_index(
            "ix_dataset_samples_version_split_image",
            "dataset_samples",
            ["dataset_version_id", "split", "image_id"],
        )


def downgrade() -> None:
    """回退仅移除新目录及索引，保留原有版本数据。"""
    op.drop_index(
        "ix_dataset_samples_version_split_image", table_name="dataset_samples"
    )
    op.drop_table("datasets")
