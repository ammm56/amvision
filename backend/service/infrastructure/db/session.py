"""数据库会话工厂定义。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class DatabaseSettings:
    """描述数据库连接配置。

    字段：
    - url：数据库连接串。
    - echo：是否输出 SQL 日志。
    """

    url: str = "sqlite:///./data/amvision.db"
    echo: bool = False


class SessionFactory:
    """按配置创建 SQLAlchemy Session。"""

    def __init__(self, settings: DatabaseSettings) -> None:
        """初始化数据库会话工厂。

        参数：
        - settings：数据库连接配置。
        """

        self.settings = settings
        self.engine: Engine = create_engine(settings.url, echo=settings.echo, future=True)
        self._session_maker = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )

    def create_session(self) -> Session:
        """创建一个新的数据库会话。

        返回：
        - 新创建的 SQLAlchemy Session。
        """

        return self._session_maker()