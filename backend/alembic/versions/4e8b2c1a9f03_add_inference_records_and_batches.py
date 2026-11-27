"""新增同步推理保存记录表与批量推理任务表。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "4e8b2c1a9f03"
down_revision = "1c92ab5f486e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建 direct_inference_records、batch_inference_tasks 与 batch_inference_task_items 表。"""

    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "direct_inference_records" not in existing_tables:
        op.create_table(
            "direct_inference_records",
            sa.Column("record_id", sa.String(length=128), nullable=False),
            sa.Column("project_id", sa.String(length=128), nullable=False),
            sa.Column("request_id", sa.String(length=128), nullable=False),
            sa.Column("task_type", sa.String(length=32), nullable=False),
            sa.Column("deployment_instance_id", sa.String(length=128), nullable=False),
            sa.Column("deployment_display_name", sa.String(length=255), nullable=False),
            sa.Column("model_version_id", sa.String(length=128), nullable=True),
            sa.Column("model_build_id", sa.String(length=128), nullable=True),
            sa.Column("input_source_kind", sa.String(length=64), nullable=False),
            sa.Column("input_label", sa.String(length=512), nullable=False),
            sa.Column("input_uri", sa.String(length=1024), nullable=True),
            sa.Column("input_file_id", sa.String(length=512), nullable=True),
            sa.Column("input_image_object_key", sa.String(length=1024), nullable=True),
            sa.Column("preview_image_object_key", sa.String(length=1024), nullable=True),
            sa.Column("result_object_key", sa.String(length=1024), nullable=False),
            sa.Column("output_object_prefix", sa.String(length=1024), nullable=False),
            sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("latency_ms", sa.Float(), nullable=True),
            sa.Column("image_width", sa.Integer(), nullable=True),
            sa.Column("image_height", sa.Integer(), nullable=True),
            sa.Column("parameters_json", sa.JSON(), nullable=False),
            sa.Column("result_summary_json", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.String(length=64), nullable=False),
            sa.PrimaryKeyConstraint("record_id"),
            sa.UniqueConstraint(
                "project_id",
                "request_id",
                name="uq_direct_inference_records_project_request",
            ),
        )
        op.create_index(
            "ix_direct_inference_records_project_id",
            "direct_inference_records",
            ["project_id"],
        )
        op.create_index(
            "ix_direct_inference_records_request_id",
            "direct_inference_records",
            ["request_id"],
        )
        op.create_index(
            "ix_direct_inference_records_task_type",
            "direct_inference_records",
            ["task_type"],
        )
        op.create_index(
            "ix_direct_inference_records_deployment_instance_id",
            "direct_inference_records",
            ["deployment_instance_id"],
        )
        op.create_index(
            "ix_direct_inference_records_created_at",
            "direct_inference_records",
            ["created_at"],
        )

    if "batch_inference_tasks" not in existing_tables:
        op.create_table(
            "batch_inference_tasks",
            sa.Column("batch_task_id", sa.String(length=128), nullable=False),
            sa.Column("project_id", sa.String(length=128), nullable=False),
            sa.Column("task_type", sa.String(length=32), nullable=False),
            sa.Column("display_name", sa.String(length=255), nullable=False),
            sa.Column("deployment_instance_id", sa.String(length=128), nullable=False),
            sa.Column("deployment_display_name", sa.String(length=255), nullable=False),
            sa.Column("model_version_id", sa.String(length=128), nullable=True),
            sa.Column("model_build_id", sa.String(length=128), nullable=True),
            sa.Column("source_kind", sa.String(length=64), nullable=False),
            sa.Column("source_summary_json", sa.JSON(), nullable=False),
            sa.Column("parameters_json", sa.JSON(), nullable=False),
            sa.Column("state", sa.String(length=32), nullable=False),
            sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("completed_items", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("succeeded_items", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_items", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped_items", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_object_prefix", sa.String(length=1024), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.String(length=64), nullable=False),
            sa.Column("started_at", sa.String(length=64), nullable=True),
            sa.Column("finished_at", sa.String(length=64), nullable=True),
            sa.Column("updated_at", sa.String(length=64), nullable=False),
            sa.PrimaryKeyConstraint("batch_task_id"),
        )
        op.create_index(
            "ix_batch_inference_tasks_project_id",
            "batch_inference_tasks",
            ["project_id"],
        )
        op.create_index(
            "ix_batch_inference_tasks_task_type",
            "batch_inference_tasks",
            ["task_type"],
        )
        op.create_index(
            "ix_batch_inference_tasks_deployment_instance_id",
            "batch_inference_tasks",
            ["deployment_instance_id"],
        )
        op.create_index(
            "ix_batch_inference_tasks_state",
            "batch_inference_tasks",
            ["state"],
        )
        op.create_index(
            "ix_batch_inference_tasks_created_at",
            "batch_inference_tasks",
            ["created_at"],
        )
        op.create_index(
            "ix_batch_inference_tasks_updated_at",
            "batch_inference_tasks",
            ["updated_at"],
        )

    if "batch_inference_task_items" not in existing_tables:
        op.create_table(
            "batch_inference_task_items",
            sa.Column("item_id", sa.String(length=128), nullable=False),
            sa.Column("batch_task_id", sa.String(length=128), nullable=False),
            sa.Column("sequence_no", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("input_label", sa.String(length=512), nullable=False),
            sa.Column("input_source_kind", sa.String(length=64), nullable=False),
            sa.Column("input_file_id", sa.String(length=512), nullable=True),
            sa.Column("input_uri", sa.String(length=1024), nullable=True),
            sa.Column("input_image_object_key", sa.String(length=1024), nullable=True),
            sa.Column("dataset_id", sa.String(length=128), nullable=True),
            sa.Column("dataset_version_id", sa.String(length=128), nullable=True),
            sa.Column("sample_id", sa.String(length=128), nullable=True),
            sa.Column("state", sa.String(length=32), nullable=False),
            sa.Column("child_task_id", sa.String(length=128), nullable=True),
            sa.Column("item_count", sa.Integer(), nullable=True),
            sa.Column("latency_ms", sa.Float(), nullable=True),
            sa.Column("image_width", sa.Integer(), nullable=True),
            sa.Column("image_height", sa.Integer(), nullable=True),
            sa.Column("result_object_key", sa.String(length=1024), nullable=True),
            sa.Column("preview_image_object_key", sa.String(length=1024), nullable=True),
            sa.Column("result_summary_json", sa.JSON(), nullable=False),
            sa.Column("error_code", sa.String(length=128), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.String(length=64), nullable=True),
            sa.Column("finished_at", sa.String(length=64), nullable=True),
            sa.ForeignKeyConstraint(
                ["batch_task_id"],
                ["batch_inference_tasks.batch_task_id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("item_id"),
        )
        op.create_index(
            "ix_batch_inference_task_items_batch_task_id",
            "batch_inference_task_items",
            ["batch_task_id"],
        )
        op.create_index(
            "ix_batch_inference_task_items_state",
            "batch_inference_task_items",
            ["state"],
        )


def downgrade() -> None:
    """回滚删除批量推理任务表与同步推理保存记录表。"""

    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "batch_inference_task_items" in existing_tables:
        op.drop_table("batch_inference_task_items")
    if "batch_inference_tasks" in existing_tables:
        op.drop_table("batch_inference_tasks")
    if "direct_inference_records" in existing_tables:
        op.drop_table("direct_inference_records")
