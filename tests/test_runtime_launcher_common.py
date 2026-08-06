"""发布 launcher 共用辅助测试。"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType


def _load_launcher_common() -> ModuleType:
    """按文件加载 launcher common，避免依赖其目录成为 Python package。"""

    common_path = (
        Path(__file__).resolve().parents[1] / "runtimes" / "launchers" / "common.py"
    )
    spec = importlib.util.spec_from_file_location("runtime_launcher_common_test", common_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 launcher common: {common_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_is_pid_alive_recognizes_current_and_missing_process() -> None:
    """验证存活判断不依赖 tasklist 权限或本地化输出。"""

    launcher_common = _load_launcher_common()

    assert launcher_common.is_pid_alive(os.getpid()) is True
    assert launcher_common.is_pid_alive(2_147_483_647) is False
