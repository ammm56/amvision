"""initial_schema

Revision ID: da5fa492b74d
Revises:
Create Date: 2026-05-29 09:53:03.460922

这是初始基线迁移。对于已经通过 ``Base.metadata.create_all()`` 创建了
全部表结构的数据库，应使用 ``alembic stamp head`` 标记为已应用。

对于全新数据库，执行 ``alembic upgrade head`` 即可创建完整表结构。
"""
from importlib import import_module
from typing import Sequence, Union

from alembic import op

from backend.service.infrastructure.persistence.base import Base

_ORM_MODULES = (
    "backend.service.infrastructure.persistence.model_orm",
    "backend.service.infrastructure.persistence.model_file_orm",
    "backend.service.infrastructure.persistence.dataset_orm",
    "backend.service.infrastructure.persistence.dataset_import_orm",
    "backend.service.infrastructure.persistence.dataset_export_orm",
    "backend.service.infrastructure.persistence.task_orm",
    "backend.service.infrastructure.persistence.deployment_orm",
    "backend.service.infrastructure.persistence.workflow_runtime_orm",
    "backend.service.infrastructure.persistence.workflow_trigger_source_orm",
    "backend.service.infrastructure.persistence.local_auth_orm",
)

for module_name in _ORM_MODULES:
    import_module(module_name)


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
