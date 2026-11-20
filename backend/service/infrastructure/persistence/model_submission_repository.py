"""模型任务提交回执的 SQLAlchemy 存储。"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, Session, mapped_column

from backend.service.infrastructure.persistence.base import Base


class ModelSubmissionReceiptEntity(Base):
    """按项目和提交人隔离回执；任务删除后仍保留原提交结果。"""

    __tablename__ = "model_submission_receipts"

    project_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    submission_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # 空值表示本次提交已确认未创建，原请求不可再写入任务。
    task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class ModelSubmissionRepository:
    """读写绑定到同一项目、主体和提交编号的回执。"""

    def __init__(self, session: Session) -> None:
        """使用调用方的事务。"""
        self.session = session

    def insert(self, key: tuple[str, str, str], task_id: str | None) -> None:
        """在提交事务内立即竞争唯一键。"""
        project_id, principal_id, submission_id = key
        self.session.add(ModelSubmissionReceiptEntity(
            project_id=project_id, principal_id=principal_id,
            submission_id=submission_id, task_id=task_id,
        ))
        self.session.flush()

    def get(self, key: tuple[str, str, str]) -> ModelSubmissionReceiptEntity | None:
        """读取已记录的提交结果。"""
        return self.session.get(ModelSubmissionReceiptEntity, key)
