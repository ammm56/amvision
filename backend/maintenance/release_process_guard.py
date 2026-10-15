"""发行目录重建前检查占用进程，避免先删除 app 再遇到运行时文件锁。"""

from pathlib import Path

import psutil


def require_release_stopped(release_dir: Path) -> None:
    """release_dir 内的解释器或工作目录仍被进程使用时拒绝重建，不终止进程。"""
    root = release_dir.resolve()
    owners = []
    for process in psutil.process_iter(["pid", "exe", "cwd"]):
        try:
            paths = (process.info.get("exe"), process.info.get("cwd"))
            if any(value and Path(value).resolve().is_relative_to(root) for value in paths):
                owners.append(process.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    if owners:
        raise ValueError(f"发行目录仍有运行进程，停止后才能重建：{root}；PID={sorted(owners)}")
