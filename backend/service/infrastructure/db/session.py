"""数据库会话工厂定义。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


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
        self._configure_sqlite_connection(settings.url)
        self.service_event_bus: object | None = None
        self.training_telemetry_broker: object | None = None
        self.training_telemetry_publisher: object | None = None
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
            options: dict[str, object] = {"connect_args": {"check_same_thread": False}}
            if parsed_url.database in (None, ":memory:"):
                options["poolclass"] = StaticPool
            return options

        return {}

    def _configure_sqlite_connection(self, database_url: str) -> None:
        """为本地多进程访问启用 SQLite 外键、WAL 和 busy timeout。

        WAL 只应用于文件数据库；内存数据库不支持跨连接 WAL。busy timeout
        用于避免 service、worker 和 inference daemon 的短事务直接因锁竞争失败。
        """

        parsed_url = make_url(database_url)
        if parsed_url.drivername != "sqlite":
            return

        is_file_database = parsed_url.database not in (None, ":memory:")

        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=30000")
                if is_file_database:
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA synchronous=NORMAL")
            finally:
                cursor.close()
