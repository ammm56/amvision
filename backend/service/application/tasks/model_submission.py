"""模型任务提交结果确认。"""

from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.service.application.errors import ResourceConflictError
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.persistence.model_submission_repository import (
    ModelSubmissionRepository,
)


@dataclass(frozen=True)
class ModelSubmissionIdentity:
    """请求携带的提交编号和已鉴权的提交人。"""

    submission_id: str
    principal_id: str


# 只由训练、转换创建路由设置，避免影响其他创建和内部任务。
model_submission_identity: ContextVar[ModelSubmissionIdentity | None] = ContextVar(
    "model_submission_identity", default=None,
)


def record_model_submission(
    session: Session, project_id: str, created_by: str | None, task_id: str,
) -> None:
    """在任务和队列消息的事务内记录回执，拒绝重复或已封闭的提交。"""
    identity = model_submission_identity.get()
    if identity is None:
        return
    if identity.principal_id != created_by:
        raise RuntimeError("模型任务提交人与任务创建人不一致")
    try:
        ModelSubmissionRepository(session).insert(
            (project_id, identity.principal_id, identity.submission_id), task_id,
        )
    except IntegrityError as error:
        session.rollback()
        if ModelSubmissionRepository(session).get(
            (project_id, identity.principal_id, identity.submission_id),
        ) is None:
            raise
        raise ResourceConflictError(
            "请查询该模型任务的提交结果",
            details={"submission_id": identity.submission_id},
        ) from error


def resolve_model_submission(
    session_factory: SessionFactory, project_id: str, principal_id: str, submission_id: str,
) -> str | None:
    """返回已创建的任务，或原子确认未创建并阻止迟到请求创建任务。"""
    key = (project_id, principal_id, submission_id)
    with session_factory.create_session() as session:
        try:
            ModelSubmissionRepository(session).insert(key, None)
            session.commit()
        except IntegrityError:
            session.rollback()
            receipt = ModelSubmissionRepository(session).get(key)
            if receipt is None:
                raise
            return receipt.task_id
    return None
