"""expand_dataset_annotations_for_classification_and_obb

Revision ID: 8b1a7b1c2d3e
Revises: da5fa492b74d
Create Date: 2026-06-11 17:10:00.000000

为 DatasetVersion 注解层补齐 classification / obb 所需字段，
并把 bbox 列调整为可空，避免继续把 annotation 写死成 detection。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8b1a7b1c2d3e"
down_revision: Union[str, Sequence[str], None] = "da5fa492b74d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级 schema。"""

    with op.batch_alter_table("dataset_detection_annotations") as batch_op:
        batch_op.add_column(sa.Column("annotation_type", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("segmentation_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("keypoints_json", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column("num_keypoints", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("polygon_xy_json", sa.JSON(), nullable=True))
        batch_op.alter_column("bbox_x", existing_type=sa.Float(), nullable=True)
        batch_op.alter_column("bbox_y", existing_type=sa.Float(), nullable=True)
        batch_op.alter_column("bbox_w", existing_type=sa.Float(), nullable=True)
        batch_op.alter_column("bbox_h", existing_type=sa.Float(), nullable=True)

    op.execute(
        "UPDATE dataset_detection_annotations "
        "SET annotation_type = 'detection' "
        "WHERE annotation_type IS NULL"
    )

    with op.batch_alter_table("dataset_detection_annotations") as batch_op:
        batch_op.alter_column("num_keypoints", server_default=None)


def downgrade() -> None:
    """降级 schema。"""

    # 降级回旧表结构时，只保留原先能表达的 detection 风格记录。
    op.execute(
        "DELETE FROM dataset_detection_annotations "
        "WHERE annotation_type IS NOT NULL AND annotation_type != 'detection'"
    )
    op.execute(
        "UPDATE dataset_detection_annotations "
        "SET bbox_x = COALESCE(bbox_x, 0), "
        "    bbox_y = COALESCE(bbox_y, 0), "
        "    bbox_w = COALESCE(bbox_w, 0), "
        "    bbox_h = COALESCE(bbox_h, 0)"
    )

    with op.batch_alter_table("dataset_detection_annotations") as batch_op:
        batch_op.alter_column("bbox_x", existing_type=sa.Float(), nullable=False)
        batch_op.alter_column("bbox_y", existing_type=sa.Float(), nullable=False)
        batch_op.alter_column("bbox_w", existing_type=sa.Float(), nullable=False)
        batch_op.alter_column("bbox_h", existing_type=sa.Float(), nullable=False)
        batch_op.drop_column("polygon_xy_json")
        batch_op.drop_column("num_keypoints")
        batch_op.drop_column("keypoints_json")
        batch_op.drop_column("segmentation_json")
        batch_op.drop_column("annotation_type")
