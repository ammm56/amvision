"""数据库与事务依赖定义。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.unit_of_work import UnitOfWork
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


def get_session_factory(request: Request) -> SessionFactory:
    """从 FastAPI 应用状态中读取 SessionFactory。

    参数：
    - request：当前 HTTP 请求。

    返回：
    - 当前应用使用的 SessionFactory。

    异常：
    - 当应用未完成数据库装配时抛出服务配置错误。
    """

    session_factory = getattr(request.app.state, "session_factory", None)
    if not isinstance(session_factory, SessionFactory):
        raise ServiceConfigurationError(
            "当前服务尚未完成数据库会话工厂装配",
            details={"state_field": "session_factory"},
        )

    return session_factory


def get_db_session(
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> Iterator[Session]:
    """为当前请求提供数据库 Session。

    参数：
    - session_factory：当前应用使用的 SessionFactory。

    返回：
    - 当前请求可用的数据库 Session。
    """

    session = session_factory.create_session()
    try:
        yield session
    finally:
        session.close()


def get_unit_of_work(
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> Iterator[UnitOfWork]:
    """为当前请求提供请求级 Unit of Work。

    参数：
    - session_factory：当前应用使用的 SessionFactory。

    返回：
    - 当前请求可用的 SqlAlchemyUnitOfWork。
    """

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        yield unit_of_work
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise
    finally:
        unit_of_work.close()