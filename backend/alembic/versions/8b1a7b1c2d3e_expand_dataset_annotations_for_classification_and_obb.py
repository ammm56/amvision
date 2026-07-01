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
from sqlalchemy import inspect


revision: str = "8b1a7b1c2d3e"
down_revision: Union[str, Sequence[str], None] = "da5fa492b74d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ANNOTATION_TABLE = "dataset_detection_annotations"
_BBOX_COLUMNS = ("bbox_x", "bbox_y", "bbox_w", "bbox_h")
_ADDED_COLUMNS = (
    "annotation_type",
    "segmentation_json",
    "keypoints_json",
    "num_keypoints",
    "polygon_xy_json",
)


def _table_columns() -> dict[str, dict[str, object]]:
    """读取当前注解表字段，支持迁移失败后再次执行。"""
    bind = op.get_bind()
    return {
        column["name"]: column
        for column in inspect(bind).get_columns(_ANNOTATION_TABLE)
    }


def _add_missing_columns(columns: dict[str, dict[str, object]]) -> None:
    """只补充缺失字段，避免半升级数据库重复 add column。"""
    if "annotation_type" not in columns:
        op.add_column(
            _ANNOTATION_TABLE,
            sa.Column("annotation_type", sa.String(length=64), nullable=True),
        )
    if "segmentation_json" not in columns:
        op.add_column(
            _ANNOTATION_TABLE,
            sa.Column("segmentation_json", sa.JSON(), nullable=True),
        )
    if "keypoints_json" not in columns:
        op.add_column(
            _ANNOTATION_TABLE,
            sa.Column("keypoints_json", sa.JSON(), nullable=True),
        )
    if "num_keypoints" not in columns:
        op.add_column(
            _ANNOTATION_TABLE,
            sa.Column(
                "num_keypoints",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
    if "polygon_xy_json" not in columns:
        op.add_column(
            _ANNOTATION_TABLE,
            sa.Column("polygon_xy_json", sa.JSON(), nullable=True),
        )


def _make_bbox_columns_nullable(columns: dict[str, dict[str, object]]) -> None:
    """把 bbox 字段改成可空，支持 classification 和 OBB 样本。"""
    need_alter = any(not columns[name]["nullable"] for name in _BBOX_COLUMNS)
    if not need_alter:
        return
    with op.batch_alter_table(_ANNOTATION_TABLE) as batch_op:
        for name in _BBOX_COLUMNS:
            if not columns[name]["nullable"]:
                batch_op.alter_column(name, existing_type=sa.Float(), nullable=True)


def _drop_num_keypoints_default(columns: dict[str, dict[str, object]]) -> None:
    """移除迁移期间用于补齐旧数据的默认值。"""
    column = columns.get("num_keypoints")
    if column is None or column.get("default") in (None, "NULL"):
        return
    with op.batch_alter_table(_ANNOTATION_TABLE) as batch_op:
        batch_op.alter_column(
            "num_keypoints",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default=None,
        )


def upgrade() -> None:
    """升级 schema。"""

    columns = _table_columns()
    _add_missing_columns(columns)
    columns = _table_columns()
    _make_bbox_columns_nullable(columns)

    op.execute(
        "UPDATE dataset_detection_annotations "
        "SET annotation_type = 'detection' "
        "WHERE annotation_type IS NULL"
    )

    columns = _table_columns()
    _drop_num_keypoints_default(columns)


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

    columns = _table_columns()
    if any(columns[name]["nullable"] for name in _BBOX_COLUMNS):
        with op.batch_alter_table(_ANNOTATION_TABLE) as batch_op:
            for name in _BBOX_COLUMNS:
                if columns[name]["nullable"]:
                    batch_op.alter_column(
                        name,
                        existing_type=sa.Float(),
                        nullable=False,
                    )

    columns = _table_columns()
    existing_added_columns = [name for name in _ADDED_COLUMNS if name in columns]
    if existing_added_columns:
        with op.batch_alter_table(_ANNOTATION_TABLE) as batch_op:
            for name in reversed(_ADDED_COLUMNS):
                if name in existing_added_columns:
                    batch_op.drop_column(name)
