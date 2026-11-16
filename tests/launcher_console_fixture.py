"""独立控制台内验证前台启动器中断，信号不进入开发者终端。"""

from pathlib import Path
import ctypes
import json
import os
import signal
import socket
import subprocess
import sys
import time

STARTUP_TIMEOUT = 120
"""真实应用冷启动包含节点目录导入；与 Ctrl+C 的退出预算分开。"""
SHUTDOWN_TIMEOUT = 8
"""退出必须保持快速，不能借放宽启动预算掩盖停止失败。"""


def main() -> None:
    """controller 接收放行字节；launcher 使用真实共用入口；child 等待停止。"""
    role, directory = sys.argv[1:3]
    root = Path(__file__).resolve().parents[1]
    output = Path(directory)
    if role == "child":
        (output / "ready").write_text(str(os.getpid()), encoding="utf-8")
        while True:
            time.sleep(0.1)
    if role == "launcher":
        sys.path.insert(0, str(root / "runtimes/launchers"))
        from common import run_python_module

        raise SystemExit(run_python_module(
            app_root=root, module_name="tests.launcher_console_fixture",
            module_args=["child", directory],
        ))
    if sys.stdin.buffer.read(1) != b"1":
        raise RuntimeError("测试控制台尚未建立进程归属")
    mode = sys.argv[3] if len(sys.argv) > 3 else "idle"
    http = mode.startswith("http")
    port = None
    if http:
        (output / "watched.py").write_text("VALUE = 1\n", encoding="utf-8")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        command = [sys.executable, str(root / "runtimes/launchers/service/start_backend_service.py"),
                   "--app-root", str(root), "--host", "127.0.0.1", "--port", str(port),
                   "--reload", "--", "--lifespan", "off", "--reload-dir", directory]
    else:
        command = [sys.executable, __file__, "launcher", directory]
    process = subprocess.Popen(command)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    # 子启动器已继承正常 Ctrl+C 状态，仅让发送者自身忽略控制事件。
    if not kernel.SetConsoleCtrlHandler(None, True):
        raise ctypes.WinError(ctypes.get_last_error())
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while True:
        if http:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                pass
        elif (output / "ready").exists():
            break
        if time.monotonic() >= deadline or process.poll() is not None:
            raise RuntimeError("测试子进程未就绪")
        time.sleep(0.05)
    if mode == "http-reload":
        # 服务已监听后改监控目录；必须出现第二个服务且外层启动器仍存活。
        time.sleep(0.5)
        (output / "watched.py").write_text("VALUE = 2\n", encoding="utf-8")
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while True:
            log = (output / "console.log").read_text("utf-8", errors="replace")
            if log.count("Uvicorn running on") >= 2:
                break
            if process.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("内部重载导致启动器退出或未恢复监听: " + log[-2000:])
            time.sleep(0.05)
    started = time.monotonic()
    if not kernel.GenerateConsoleCtrlEvent(signal.CTRL_C_EVENT, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        result = process.wait(timeout=SHUTDOWN_TIMEOUT)
    except subprocess.TimeoutExpired:
        result = None
    (output / "result.json").write_text(json.dumps({
        "returncode": result, "elapsed": time.monotonic() - started,
        "child_pid": int((output / "ready").read_text("utf-8")) if not http else None,
        "port": port,
        "reloaded": mode == "http-reload",
    }), encoding="utf-8")


if __name__ == "__main__":
    main()
