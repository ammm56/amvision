"""DeploymentInstance 的 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.service.application.errors import PersistenceOperationError
from backend.service.domain.deployments.deployment_instance import DeploymentInstance
from backend.service.infrastructure.persistence.deployment_orm import DeploymentInstanceRecord


class SqlAlchemyDeploymentInstanceRepository:
    """使用 SQLAlchemy 持久化 DeploymentInstance。"""

    def __init__(self, session: Session) -> None:
        """初始化 DeploymentInstance 仓储。

        参数：
        - session：当前 Unit of Work 持有的 Session。
        """

        self.session = session

    def save_deployment_instance(self, deployment_instance: DeploymentInstance) -> None:
        """保存一个 DeploymentInstance。"""

        try:
            existing_record = self.session.get(
                DeploymentInstanceRecord,
                deployment_instance.deployment_instance_id,
            )
            if existing_record is None:
                self.session.add(self._to_record(deployment_instance))
                return

            existing_record.project_id = deployment_instance.project_id
            existing_record.model_id = deployment_instance.model_id
            existing_record.model_version_id = deployment_instance.model_version_id
            existing_record.model_build_id = deployment_instance.model_build_id
            existing_record.runtime_profile_id = deployment_instance.runtime_profile_id
            existing_record.runtime_backend = deployment_instance.runtime_backend
            existing_record.device_name = deployment_instance.device_name
            existing_record.instance_count = deployment_instance.instance_count
            existing_record.status = deployment_instance.status
            existing_record.display_name = deployment_instance.display_name
            existing_record.created_at = deployment_instance.created_at
            existing_record.updated_at = deployment_instance.updated_at
            existing_record.created_by = deployment_instance.created_by
            existing_record.metadata_json = dict(deployment_instance.metadata)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 DeploymentInstance 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_deployment_instance(self, deployment_instance_id: str) -> DeploymentInstance | None:
        """按 id 读取一个 DeploymentInstance。"""

        try:
            record = self.session.get(DeploymentInstanceRecord, deployment_instance_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 DeploymentInstance 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None
        return self._to_domain(record)

    def list_deployment_instances(self, project_id: str) -> tuple[DeploymentInstance, ...]:
        """按 Project id 列出 DeploymentInstance。"""

        statement = (
            select(DeploymentInstanceRecord)
            .where(DeploymentInstanceRecord.project_id == project_id)
            .order_by(
                DeploymentInstanceRecord.created_at.desc(),
                DeploymentInstanceRecord.deployment_instance_id.desc(),
            )
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 DeploymentInstance 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        return tuple(self._to_domain(record) for record in records)

    @staticmethod
    def _to_record(deployment_instance: DeploymentInstance) -> DeploymentInstanceRecord:
        """把领域对象转换为 ORM 实体。"""

        return DeploymentInstanceRecord(
            deployment_instance_id=deployment_instance.deployment_instance_id,
            project_id=deployment_instance.project_id,
            model_id=deployment_instance.model_id,
            model_version_id=deployment_instance.model_version_id,
            model_build_id=deployment_instance.model_build_id,
            runtime_profile_id=deployment_instance.runtime_profile_id,
            runtime_backend=deployment_instance.runtime_backend,
            device_name=deployment_instance.device_name,
            instance_count=deployment_instance.instance_count,
            status=deployment_instance.status,
            display_name=deployment_instance.display_name,
            created_at=deployment_instance.created_at,
            updated_at=deployment_instance.updated_at,
            created_by=deployment_instance.created_by,
            metadata_json=dict(deployment_instance.metadata),
        )

    @staticmethod
    def _to_domain(record: DeploymentInstanceRecord) -> DeploymentInstance:
        """把 ORM 实体转换为领域对象。"""

        return DeploymentInstance(
            deployment_instance_id=record.deployment_instance_id,
            project_id=record.project_id,
            model_id=record.model_id,
            model_version_id=record.model_version_id,
            model_build_id=record.model_build_id,
            runtime_profile_id=record.runtime_profile_id,
            runtime_backend=record.runtime_backend,
            device_name=record.device_name,
            instance_count=record.instance_count,
            status=record.status,
            display_name=record.display_name,
            created_at=record.created_at,
            updated_at=record.updated_at,
            created_by=record.created_by,
            metadata=dict(record.metadata_json or {}),
        )