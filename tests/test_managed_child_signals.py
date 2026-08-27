"""父进程托管子进程信号边界测试。"""

from __future__ import annotations

from backend.runtime.processes import managed_child_signals


def test_configure_managed_child_signals_ignores_windows_console_signals(
    monkeypatch,
) -> None:
    """Windows 子进程应忽略 Ctrl+C 和 CTRL_BREAK 广播。"""

    configured: list[tuple[object, object]] = []
    monkeypatch.setattr(managed_child_signals.os, "name", "nt")
    monkeypatch.setattr(
        managed_child_signals.signal,
        "signal",
        lambda signal_number, handler: configured.append((signal_number, handler)),
    )

    managed_child_signals.configure_managed_child_signals()

    assert (managed_child_signals.signal.SIGINT, managed_child_signals.signal.SIG_IGN) in configured
    if hasattr(managed_child_signals.signal, "SIGBREAK"):
        assert (
            managed_child_signals.signal.SIGBREAK,
            managed_child_signals.signal.SIG_IGN,
        ) in configured


def test_configure_managed_child_signals_keeps_non_windows_defaults(
    monkeypatch,
) -> None:
    """非 Windows 子进程不应改变默认信号处理器。"""

    configured: list[tuple[object, object]] = []
    monkeypatch.setattr(managed_child_signals.os, "name", "posix")
    monkeypatch.setattr(
        managed_child_signals.signal,
        "signal",
        lambda signal_number, handler: configured.append((signal_number, handler)),
    )

    managed_child_signals.configure_managed_child_signals()

    assert configured == []
