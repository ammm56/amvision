"""数据库会话工厂定义。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
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
        self._prepare_sqlite_path(settings.url)
        self.engine: Engine = create_engine(
            settings.url,
            echo=settings.echo,
            future=True,
            **self._build_engine_options(settings.url),
        )
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

    def _prepare_sqlite_path(self, database_url: str) -> None:
        """为 SQLite 文件数据库预创建父目录。

        参数：
        - database_url：数据库连接串。
        """

        parsed_url = make_url(database_url)
        if parsed_url.drivername != "sqlite" or parsed_url.database in (None, ":memory:"):
            return

        database_path = Path(parsed_url.database)
        database_path.parent.mkdir(parents=True, exist_ok=True)

    def _build_engine_options(self, database_url: str) -> dict[str, object]:
        """根据数据库类型构建 engine 选项。

        参数：
        - database_url：数据库连接串。

        返回：
        - 传给 create_engine 的附加参数。
        """

        parsed_url: URL = make_url(database_url)
        if parsed_url.drivername == "sqlite":
            return {"connect_args": {"check_same_thread": False}}

        return {}