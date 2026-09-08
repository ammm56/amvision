"""维护窗口中的 SQLite 空闲页回收，不参与普通资源 DELETE。"""

import json
from pathlib import Path
import shutil
import sqlite3

from sqlalchemy.engine import make_url

from backend.maintenance.database_migrations import _backup_sqlite_database
from backend.service.settings import get_backend_service_settings


def compact_database(settings) -> dict[str, object]:
    """保留一致性备份后压缩 SQLite；写入占用或空间不足时明确失败。"""
    url = make_url(settings.database.url)
    if (
        not url.drivername.startswith("sqlite")
        or not url.database
        or url.database == ":memory:"
    ):
        raise ValueError("此维护命令仅适用于本地 SQLite；其他数据库使用对应维护工具")
    path = Path(url.database).resolve(strict=True)
    before = path.stat().st_size
    if shutil.disk_usage(path.parent).free < before * 3:
        raise OSError("剩余磁盘空间不足以保存备份和 SQLite 整理临时文件")
    with sqlite3.connect(path, timeout=1.0) as connection:
        free_pages = connection.execute("PRAGMA freelist_count").fetchone()[0]
        # 写入占用先失败，避免在活跃写事务中启动大体积备份。
        connection.execute("BEGIN EXCLUSIVE")
        connection.rollback()
    backup = _backup_sqlite_database(settings)
    with sqlite3.connect(path, timeout=1.0) as connection:
        connection.execute("VACUUM")
        after_free_pages = connection.execute("PRAGMA freelist_count").fetchone()[0]
    return {
        "database": str(path),
        "backup_file": str(backup),
        "before_bytes": before,
        "after_bytes": path.stat().st_size,
        "before_free_pages": free_pages,
        "after_free_pages": after_free_pages,
    }


if __name__ == "__main__":
    print(
        json.dumps(
            compact_database(get_backend_service_settings()),
            ensure_ascii=False,
            indent=2,
        )
    )
