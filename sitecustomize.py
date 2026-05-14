"""修正 Windows 开发环境中的 MKL 与 PyTorch OpenMP 运行时冲突。

本模块会在 Python 启动时被 site 自动导入。
当前 conda 环境同时提供 MKL 的 libiomp5md.dll，torch 也自带一份
libiomp5md.dll；在 Windows 下二者可能在导入 numpy 或 torch 时触发
重复初始化并导致进程 abort。

约束：
- 只在 Windows 下生效。
- 只在未显式配置 MKL_SERVICE_FORCE_INTEL 时提供默认值。
- 不使用 KMP_DUPLICATE_LIB_OK 这种不安全绕过。
"""

from __future__ import annotations

import os
import sys


def _configure_windows_openmp_runtime() -> None:
    """为 Windows 进程设置更稳定的 MKL OpenMP 选择。

    返回：
    - None。
    """

    if sys.platform != "win32":
        return
    os.environ.setdefault("MKL_SERVICE_FORCE_INTEL", "1")


_configure_windows_openmp_runtime()