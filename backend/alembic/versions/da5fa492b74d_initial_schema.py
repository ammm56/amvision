"""initial_schema

Revision ID: da5fa492b74d
Revises:
Create Date: 2026-05-29 09:53:03.460922

这是初始基线迁移。对于已经通过 ``Base.metadata.create_all()`` 创建了
全部表结构的数据库，应使用 ``alembic stamp head`` 标记为已应用。

对于全新数据库，执行 ``alembic upgrade head`` 即可创建完整表结构。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from backend.service.infrastructure.persistence.base import Base
from backend.service.infrastructure.persistence import (
    model_orm,
    model_file_orm,
    dataset_orm,
    dataset_import_orm,
    dataset_export_orm,
    task_orm,
    deployment_orm,
    workflow_runtime_orm,
    workflow_trigger_source_orm,
    local_auth_orm,
)


# revision 标识符，由 Alembic 使用
revision: str = 'da5fa492b74d'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级 schema。"""
    # 从 ORM metadata 创建所有表
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    """降级 schema。"""
    # 删除所有表（反序）
    Base.metadata.drop_all(op.get_bind())
