"""受管命令启动门，目标仅在父进程完成平台归属登记后执行。"""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import runpy
from typing import Sequence

_START_TOKEN = b"\x01"


def release_bootstrap(process: subprocess.Popen[bytes]) -> None:
    """放行一次目标；保留控制管道供 POSIX 监视 owner 生命周期。"""
    if process.stdin is None:
        raise RuntimeError("受管 bootstrap 缺少控制 pipe")
    process.stdin.write(_START_TOKEN)
    process.stdin.flush()


def build_bootstrap_command(command: Sequence[str], *, python_entrypoint: bool = False) -> list[str]:
    """保持当前发行解释器，按原始参数数组启动真实目标。"""
    if isinstance(command, (str, bytes)):
        raise ValueError("command 必须为参数数组")
    normalized = [str(part) for part in command]
    if not normalized:
        raise ValueError("command 不能为空")
    if python_entrypoint:
        # Python 入口使用目标解释器执行启动门；不额外保留等待型包装进程。
        if len(normalized) < 2 or (normalized[1].startswith("-") and normalized[1] != "-m"):
            raise ValueError("Python 入口必须为 script 或 -m module")
        if normalized[1] == "-m" and len(normalized) < 3:
            raise ValueError("Python 模块名不能为空")
        return [normalized[0], str(Path(__file__).resolve()), "--python", *normalized[1:]]
    return [sys.executable, str(Path(__file__).resolve()), "--", *normalized]


def _run_python(arguments: list[str]) -> int:
    """在已归属的进程内运行入口，保持 main、argv、导入路径和 spawn 语义。"""
    # 控制 pipe 只能由 guardian 持有，不能泄露为目标 stdin 或传给后代。
    descriptor = os.open(os.devnull, os.O_RDONLY)
    sys.stdin.close()
    try:
        os.dup2(descriptor, 0)
    finally:
        if descriptor != 0:
            os.close(descriptor)
    sys.stdin = open(0, encoding="utf-8", closefd=False)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.SIG_DFL)
    return execute_python_entrypoint(arguments)


def execute_python_entrypoint(arguments: list[str]) -> int:
    """在调用方已确认的受管 PID 内执行 Python 入口，保留 main 和 spawn 语义。"""
    if arguments[0] == "-m":
        sys.argv = arguments[1:]
        sys.path[0] = os.getcwd()
        runpy.run_module(arguments[1], run_name="__main__", alter_sys=True)
    else:
        sys.argv = arguments
        sys.path[0] = str(Path(arguments[0]).resolve().parent)
        runpy.run_path(arguments[0], run_name="__main__")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """等待登记完成；平台归属保留于 Job 或独立 session 中。"""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in {"--", "--python"} or len(arguments) == 1:
        return 2
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)
    if os.name != "nt":
        reader, writer = os.pipe()
        subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).with_name("posix_group_guardian.py")),
                "--ready-fd",
                str(writer),
            ],
            stdin=sys.stdin,
            stdout=subprocess.DEVNULL,
            pass_fds=(writer,),
        )
        os.close(writer)
        try:
            if os.read(reader, 1) != _START_TOKEN:
                return 125
        finally:
            os.close(reader)
    elif sys.stdin.buffer.read(1) != _START_TOKEN:
        return 125
    if arguments[0] == "--python":
        return _run_python(arguments[1:])
    process = subprocess.Popen(arguments[1:], stdin=subprocess.DEVNULL)
    return int(process.wait())


if __name__ == "__main__":
    raise SystemExit(main())
