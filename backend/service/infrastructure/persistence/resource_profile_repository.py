"""ResourceProfile 的 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.service.application.errors import PersistenceOperationError
from backend.service.domain.tasks.task_records import ResourceProfile
from backend.service.infrastructure.persistence.task_orm import ResourceProfileEntity


class SqlAlchemyResourceProfileRepository:
    """使用 SQLAlchemy 持久化 ResourceProfile。"""

    def __init__(self, session: Session) -> None:
        """初始化 ResourceProfile 仓储。

        参数：
        - session：当前 Unit of Work 持有的 Session。
        """

        self.session = session

    def save_resource_profile(self, resource_profile: ResourceProfile) -> None:
        """保存一个 ResourceProfile。

        参数：
        - resource_profile：要保存的 ResourceProfile。
        """

        try:
            existing_record = self.session.get(ResourceProfileEntity, resource_profile.resource_profile_id)
            if existing_record is None:
                self.session.add(self._to_entity(resource_profile))
                return

            existing_record.profile_name = resource_profile.profile_name
            existing_record.worker_pool = resource_profile.worker_pool
            existing_record.executor_mode = resource_profile.executor_mode
            existing_record.max_concurrency = resource_profile.max_concurrency
            existing_record.metadata_json = dict(resource_profile.metadata)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 ResourceProfile 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_resource_profile(self, resource_profile_id: str) -> ResourceProfile | None:
        """按 id 读取一个 ResourceProfile。

        参数：
        - resource_profile_id：资源画像 id。

        返回：
        - 读取到的 ResourceProfile；不存在时返回 None。
        """

        try:
            record = self.session.get(ResourceProfileEntity, resource_profile_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 ResourceProfile 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None

        return self._to_domain(record)

    def list_resource_profiles(self, worker_pool: str) -> tuple[ResourceProfile, ...]:
        """按 worker pool 列出 ResourceProfile。

        参数：
        - worker_pool：目标 worker pool 名称。

        返回：
        - 当前 worker pool 下的 ResourceProfile 列表。
        """

        statement = (
            select(ResourceProfileEntity)
            .where(ResourceProfileEntity.worker_pool == worker_pool)
            .order_by(ResourceProfileEntity.profile_name, ResourceProfileEntity.resource_profile_id)
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 ResourceProfile 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

        return tuple(self._to_domain(record) for record in records)

    def _to_entity(self, resource_profile: ResourceProfile) -> ResourceProfileEntity:
        """把 ResourceProfile 领域对象转换为 ORM 实体。"""

        return ResourceProfileEntity(
            resource_profile_id=resource_profile.resource_profile_id,
            profile_name=resource_profile.profile_name,
            worker_pool=resource_profile.worker_pool,
            executor_mode=resource_profile.executor_mode,
            max_concurrency=resource_profile.max_concurrency,
            metadata_json=dict(resource_profile.metadata),
        )

    def _to_domain(self, record: ResourceProfileEntity) -> ResourceProfile:
        """把 ORM 实体转换为 ResourceProfile 领域对象。"""

        return ResourceProfile(
            resource_profile_id=record.resource_profile_id,
            profile_name=record.profile_name,
            worker_pool=record.worker_pool,
            executor_mode=record.executor_mode,
            max_concurrency=record.max_concurrency,
            metadata=dict(record.metadata_json or {}),
        )