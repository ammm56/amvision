"""ModelFile 的 SQLAlchemy 仓储实现。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.service.application.errors import PersistenceOperationError
from backend.service.domain.files.model_file import ModelFile
from backend.service.infrastructure.persistence.model_file_orm import ModelFileRecord


class SqlAlchemyModelFileRepository:
    """使用 SQLAlchemy 持久化 ModelFile。"""

    def __init__(self, session: Session) -> None:
        """初始化 ModelFile 仓储。

        参数：
        - session：当前 Unit of Work 持有的 Session。
        """

        self.session = session

    def save_model_file(self, model_file: ModelFile) -> None:
        """保存一个 ModelFile。

        参数：
        - model_file：要保存的 ModelFile。
        """

        try:
            existing_record = self.session.get(ModelFileRecord, model_file.file_id)
            if existing_record is None:
                self.session.add(self._to_record(model_file))
                return

            existing_record.project_id = model_file.project_id
            existing_record.model_id = model_file.model_id
            existing_record.file_type = model_file.file_type
            existing_record.logical_name = model_file.logical_name
            existing_record.storage_uri = model_file.storage_uri
            existing_record.model_version_id = model_file.model_version_id
            existing_record.model_build_id = model_file.model_build_id
            existing_record.metadata_json = dict(model_file.metadata)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "保存 ModelFile 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

    def get_model_file(self, file_id: str) -> ModelFile | None:
        """按 id 读取一个 ModelFile。"""

        try:
            record = self.session.get(ModelFileRecord, file_id)
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "读取 ModelFile 失败",
                details={"error_type": error.__class__.__name__},
            ) from error
        if record is None:
            return None

        return self._to_domain(record)

    def list_model_files(
        self,
        *,
        model_version_id: str | None = None,
        model_build_id: str | None = None,
    ) -> tuple[ModelFile, ...]:
        """按模型版本或 build 列出关联文件。"""

        statement = select(ModelFileRecord).order_by(ModelFileRecord.file_id)
        if model_version_id is not None:
            statement = statement.where(ModelFileRecord.model_version_id == model_version_id)
        if model_build_id is not None:
            statement = statement.where(ModelFileRecord.model_build_id == model_build_id)

        try:
            records = self.session.execute(statement).scalars().all()
        except SQLAlchemyError as error:
            raise PersistenceOperationError(
                "列出 ModelFile 失败",
                details={"error_type": error.__class__.__name__},
            ) from error

        return tuple(self._to_domain(record) for record in records)

    def _to_record(self, model_file: ModelFile) -> ModelFileRecord:
        """把 ModelFile 领域对象转换为 ORM 实体。"""

        return ModelFileRecord(
            file_id=model_file.file_id,
            project_id=model_file.project_id,
            model_id=model_file.model_id,
            file_type=model_file.file_type,
            logical_name=model_file.logical_name,
            storage_uri=model_file.storage_uri,
            model_version_id=model_file.model_version_id,
            model_build_id=model_file.model_build_id,
            metadata_json=dict(model_file.metadata),
        )

    def _to_domain(self, record: ModelFileRecord) -> ModelFile:
        """把 ORM 实体转换为 ModelFile 领域对象。"""

        return ModelFile(
            file_id=record.file_id,
            project_id=record.project_id,
            model_id=record.model_id,
            file_type=record.file_type,
            logical_name=record.logical_name,
            storage_uri=record.storage_uri,
            model_version_id=record.model_version_id,
            model_build_id=record.model_build_id,
            metadata=dict(record.metadata_json or {}),
        )