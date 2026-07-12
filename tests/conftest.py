"""测试公共配置。"""

from __future__ import annotations

from pathlib import Path


def pytest_configure(config: object) -> None:
    """确保 pytest.ini 中测试临时目录和缓存目录的父目录存在。"""

    rootpath = Path(getattr(config, "rootpath", "."))
    (rootpath / ".tmp").mkdir(parents=True, exist_ok=True)
    (rootpath / ".tmp" / "pytest-cache").mkdir(parents=True, exist_ok=True)
