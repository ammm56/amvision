"""Model 聚合的 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.service.application.errors import PersistenceOperationError
from backend.service.domain.models.model_records import Model, ModelBuild, ModelScopeKind, ModelVersion
from backend.service.infrastructure.persistence.model_orm import (
    ModelBuildRecord,
    ModelRecord,
    ModelVersionRecord,
)


class SqlAlchemyModelRepository:
    """使用 SQLAlchemy 持久化 Model 聚合。"""

    def __init__(self, session: Session) -> None:
        """初始化 Model 仓储。

        参数：
        - session：当前 Unit of Work 持有的 Session。
        """

        self.session = session

    def list_models(
        self,
        *,
        scope_kind: ModelScopeKind | None = None,
        model_name: str | None = None,
        model_scale: str | None = None,
        task_type: str | None = None,
        limit: int | None = None,
    ) -> tuple[Model, ...]:
        """按公开筛选条件列出 Model。"""

        statement = select(ModelRecord)
        if scope_kind is not None:
            statement = statement.where(ModelRecord.scope_kind == scope_kind)
        if model_name is not None:
            statement = statement.where(ModelRecord.model_name == model_name)
        if model_scale is not None:
            statement = statement.where(ModelRecord.model_scale == model_scale)
        if task_type is not None:
            statement = statement.where(ModelRecord.task_type == task_type)

        statement = statement.order_by(
            ModelRecord.model_name,
            ModelRecord.model_scale,
            ModelRecord.model_id,
        )
        if limit is not None:
            statement = statement.limit(limit)

        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 Model 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

        return tuple(self._to_model_domain(record) for record in records)

    def find_model(
        self,
        *,
        project_id: str | None,
        scope_kind: ModelScopeKind,
        model_name: str,
        model_scale: str,
        task_type: str,
    ) -> Model | None:
        """按自然键查找一个 Model。

        参数：
    - project_id：所属项目 id；平台基础模型时为空。
        - scope_kind：模型作用域类型。
        - model_name：模型名。
        - model_scale：模型 scale。
        - task_type：任务类型。

        返回：
        - 读取到的 Model；不存在时返回 None。
        """

        statement = select(ModelRecord).where(
            ModelRecord.project_id == project_id,
            ModelRecord.scope_kind == scope_kind,
            ModelRecord.model_name == model_name,
            ModelRecord.model_scale == model_scale,
            ModelRecord.task_type == task_type,
        )
        try:
            record = self.session.execute(statement).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "按自然键读取 Model 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None

        return self._to_model_domain(record)

    def save_model(self, model: Model) -> None:
        """保存一个 Model。

        参数：
        - model：要保存的 Model。
        """

        try:
            existing_record = self.session.get(ModelRecord, model.model_id)
            if existing_record is None:
                self.session.add(self._to_model_record(model))
                return

            existing_record.project_id = model.project_id
            existing_record.scope_kind = model.scope_kind
            existing_record.model_name = model.model_name
            existing_record.model_type = model.model_type
            existing_record.task_type = model.task_type
            existing_record.model_scale = model.model_scale
            existing_record.labels_file_id = model.labels_file_id
            existing_record.metadata_json = dict(model.metadata)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 Model 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_model(self, model_id: str) -> Model | None:
        """按 id 读取 Model。"""

        try:
            record = self.session.get(ModelRecord, model_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 Model 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None

        return self._to_model_domain(record)

    def save_model_version(self, model_version: ModelVersion) -> None:
        """保存一个 ModelVersion。"""

        try:
            existing_record = self.session.get(ModelVersionRecord, model_version.model_version_id)
            if existing_record is None:
                self.session.add(self._to_model_version_record(model_version))
                return

            existing_record.model_id = model_version.model_id
            existing_record.source_kind = model_version.source_kind
            existing_record.dataset_version_id = model_version.dataset_version_id
            existing_record.training_task_id = model_version.training_task_id
            existing_record.parent_version_id = model_version.parent_version_id
            existing_record.file_ids_json = list(model_version.file_ids)
            existing_record.metadata_json = dict(model_version.metadata)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 ModelVersion 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_model_version(self, model_version_id: str) -> ModelVersion | None:
        """按 id 读取 ModelVersion。"""

        try:
            record = self.session.get(ModelVersionRecord, model_version_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 ModelVersion 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None

        return self._to_model_version_domain(record)

    def list_model_versions(self, model_id: str) -> tuple[ModelVersion, ...]:
        """按 Model id 列出所有 ModelVersion。"""

        statement = (
            select(ModelVersionRecord)
            .where(ModelVersionRecord.model_id == model_id)
            .order_by(ModelVersionRecord.model_version_id)
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 ModelVersion 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

        return tuple(self._to_model_version_domain(record) for record in records)

    def save_model_build(self, model_build: ModelBuild) -> None:
        """保存一个 ModelBuild。"""

        try:
            existing_record = self.session.get(ModelBuildRecord, model_build.model_build_id)
            if existing_record is None:
                self.session.add(self._to_model_build_record(model_build))
                return

            existing_record.model_id = model_build.model_id
            existing_record.source_model_version_id = model_build.source_model_version_id
            existing_record.build_format = model_build.build_format
            existing_record.runtime_profile_id = model_build.runtime_profile_id
            existing_record.conversion_task_id = model_build.conversion_task_id
            existing_record.file_ids_json = list(model_build.file_ids)
            existing_record.metadata_json = dict(model_build.metadata)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 ModelBuild 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_model_build(self, model_build_id: str) -> ModelBuild | None:
        """按 id 读取 ModelBuild。"""

        try:
            record = self.session.get(ModelBuildRecord, model_build_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 ModelBuild 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None

        return self._to_model_build_domain(record)

    def list_model_builds(self, model_id: str) -> tuple[ModelBuild, ...]:
        """按 Model id 列出所有 ModelBuild。"""

        statement = (
            select(ModelBuildRecord)
            .where(ModelBuildRecord.model_id == model_id)
            .order_by(ModelBuildRecord.model_build_id)
        )
        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 ModelBuild 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

        return tuple(self._to_model_build_domain(record) for record in records)

    def _to_model_record(self, model: Model) -> ModelRecord:
        """把 Model 领域对象转换为 ORM 实体。"""

        return ModelRecord(
            model_id=model.model_id,
            project_id=model.project_id,
            scope_kind=model.scope_kind,
            model_name=model.model_name,
            model_type=model.model_type,
            task_type=model.task_type,
            model_scale=model.model_scale,
            labels_file_id=model.labels_file_id,
            metadata_json=dict(model.metadata),
        )

    def _to_model_version_record(self, model_version: ModelVersion) -> ModelVersionRecord:
        """把 ModelVersion 领域对象转换为 ORM 实体。"""

        return ModelVersionRecord(
            model_version_id=model_version.model_version_id,
            model_id=model_version.model_id,
            source_kind=model_version.source_kind,
            dataset_version_id=model_version.dataset_version_id,
            training_task_id=model_version.training_task_id,
            parent_version_id=model_version.parent_version_id,
            file_ids_json=list(model_version.file_ids),
            metadata_json=dict(model_version.metadata),
        )

    def _to_model_build_record(self, model_build: ModelBuild) -> ModelBuildRecord:
        """把 ModelBuild 领域对象转换为 ORM 实体。"""

        return ModelBuildRecord(
            model_build_id=model_build.model_build_id,
            model_id=model_build.model_id,
            source_model_version_id=model_build.source_model_version_id,
            build_format=model_build.build_format,
            runtime_profile_id=model_build.runtime_profile_id,
            conversion_task_id=model_build.conversion_task_id,
            file_ids_json=list(model_build.file_ids),
            metadata_json=dict(model_build.metadata),
        )

    def _to_model_domain(self, record: ModelRecord) -> Model:
        """把 ORM 实体转换为 Model 领域对象。"""

        return Model(
            model_id=record.model_id,
            project_id=record.project_id,
            scope_kind=record.scope_kind,
            model_name=record.model_name,
            model_type=record.model_type,
            task_type=record.task_type,
            model_scale=record.model_scale,
            labels_file_id=record.labels_file_id,
            metadata=dict(record.metadata_json or {}),
        )

    def _to_model_version_domain(self, record: ModelVersionRecord) -> ModelVersion:
        """把 ORM 实体转换为 ModelVersion 领域对象。"""

        return ModelVersion(
            model_version_id=record.model_version_id,
            model_id=record.model_id,
            source_kind=record.source_kind,
            dataset_version_id=record.dataset_version_id,
            training_task_id=record.training_task_id,
            parent_version_id=record.parent_version_id,
            file_ids=tuple(record.file_ids_json or []),
            metadata=dict(record.metadata_json or {}),
        )

    def _to_model_build_domain(self, record: ModelBuildRecord) -> ModelBuild:
        """把 ORM 实体转换为 ModelBuild 领域对象。"""

        return ModelBuild(
            model_build_id=record.model_build_id,
            model_id=record.model_id,
            source_model_version_id=record.source_model_version_id,
            build_format=record.build_format,
            runtime_profile_id=record.runtime_profile_id,
            conversion_task_id=record.conversion_task_id,
            file_ids=tuple(record.file_ids_json or []),
            metadata=dict(record.metadata_json or {}),
        )