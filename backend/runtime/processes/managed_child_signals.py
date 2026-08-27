"""父进程托管子进程的控制台信号边界。"""

from __future__ import annotations

import os
import signal


def configure_managed_child_signals() -> None:
    """阻止 Windows 控制台中断绕过父进程的正常停机协议。

    Windows 控制台会把 Ctrl+C/CTRL_BREAK 广播给同一控制台中的进程树。
    Workflow Runtime 与 Deployment worker 的生命周期由父进程通过队列管理，
    子进程必须忽略这些广播信号，等待父进程发送 shutdown 或执行受控回收。
    非 Windows 平台保留操作系统和 multiprocessing 的默认信号行为。
    """

    if os.name != "nt":
        return
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)
