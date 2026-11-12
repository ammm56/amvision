"""测试公共配置。"""

from __future__ import annotations

from pathlib import Path
import sys
from collections.abc import Iterator

import pytest


def pytest_configure(config: object) -> None:
    """确保 pytest.ini 中测试临时目录和缓存目录的父目录存在。"""

    rootpath = Path(getattr(config, "rootpath", "."))
    (rootpath / ".tmp").mkdir(parents=True, exist_ok=True)
    (rootpath / ".tmp" / "pytest-cache").mkdir(parents=True, exist_ok=True)


@pytest.fixture(autouse=True)
def preserve_custom_node_modules() -> Iterator[None]:
    """节点包刷新仅作用于本用例，不能破坏后续测试已导入的类和故障注入身份。"""
    def snapshot():
        """仅记录受节点包加载器刷新影响的模块。"""
        return {
            name: module for name, module in tuple(sys.modules.items())
            if name == "custom_nodes" or name.startswith("custom_nodes.")
        }

    previous = snapshot()
    try:
        yield
    finally:
        current = snapshot()
        for name, module in current.items():
            sys.modules.pop(name, None)
            parent_name, _, attribute = name.rpartition(".")
            parent = previous.get(parent_name)
            if name not in previous and parent is not None and getattr(parent, attribute, None) is module:
                delattr(parent, attribute)
        sys.modules.update(previous)
        for name, module in previous.items():
            parent_name, _, attribute = name.rpartition(".")
            parent = previous.get(parent_name)
            if parent is not None:
                setattr(parent, attribute, module)
