"""测试公共配置。"""

from __future__ import annotations

from pathlib import Path


def pytest_configure(config: object) -> None:
    """确保 pytest.ini 中 --basetemp 的父目录存在。"""

    rootpath = Path(getattr(config, "rootpath", "."))
    (rootpath / ".tmp").mkdir(parents=True, exist_ok=True)
