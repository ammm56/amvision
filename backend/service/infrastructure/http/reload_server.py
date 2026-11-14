"""开发热重载入口：监听 socket 随服务子进程创建和关闭，不跨 IOCP 复用。"""

from __future__ import annotations

from copy import copy
from functools import partial
import logging
import multiprocessing
from multiprocessing.synchronize import Event
from socket import socket
import sys

import click
from uvicorn import Config, Server
from uvicorn.config import LOGGING_CONFIG
from uvicorn.main import main as uvicorn_command
from uvicorn.supervisors import ChangeReload
from uvicorn._subprocess import get_subprocess


class ReloadServer(Server):
    """复用 Uvicorn 服务循环接收父进程重载事件，不广播控制台信号。"""

    def __init__(self, config: Config, stop_event: Event) -> None:
        """stop_event 仅属于本次重载器；不参与 Workflow 停止控制。"""
        super().__init__(config)
        self.stop_event = stop_event

    async def on_tick(self, counter: int) -> bool:
        """沿原服务周期检查退出，不创建线程或另一套调度器。"""
        if self.stop_event.is_set():
            self.should_exit = True
        return await super().on_tick(counter)


class ServiceReload(ChangeReload):
    """沿现有文件监控和 spawn 实现重载，只替换内部停止通知。"""

    def __init__(self, config: Config, *, stop_event: Event, **kwargs) -> None:
        """保存同一个跨进程事件，启动仍由 Uvicorn 负责。"""
        super().__init__(config, **kwargs)
        self.stop_event = stop_event

    def restart(self) -> None:
        """旧服务完整关闭后重建监听，不能把内部重载变成用户 Ctrl+C。"""
        self.stop_event.set()
        self.process.join()
        if self.should_exit.is_set():
            return
        self.stop_event.clear()
        self.process = get_subprocess(
            config=self.config, target=self.target, sockets=self.sockets,
        )
        self.process.start()

    def shutdown(self) -> None:
        """正常停止也走相同事件，外层受管组负责最终强制回收边界。"""
        self.stop_event.set()
        self.process.join()
        for listener in self.sockets:
            listener.close()
        logging.getLogger("uvicorn.error").info("Stopping reloader process [%s]", self.pid)


def serve(config: Config, *, stop_event: Event, sockets: list[socket] | None = None) -> None:
    """在子进程内绑定监听；config 为服务配置，sockets 必须为空。"""
    if sockets:
        raise ValueError("开发热重载不接受父进程共享的监听 socket")
    enable_reload_interrupt()
    ReloadServer(config, stop_event).run()


def enable_reload_interrupt() -> None:
    """恢复受管进程组继承的 Ctrl+C，使 Uvicorn 能正常结束重载子进程。"""
    if sys.platform != "win32":
        return
    import ctypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    # CREATE_NEW_PROCESS_GROUP 默认忽略 Ctrl+C，且忽略标志会被 spawn 子进程继承。
    # 只在开发 HTTP 子进程恢复；不改变父启动器或任何 Runtime/Trigger 的信号策略。
    if not kernel.SetConsoleCtrlHandler(None, False):
        raise ctypes.WinError(ctypes.get_last_error())


def run_reload(**options: object) -> None:
    """将 Uvicorn CLI options 转为配置，复用其重载器但不预先绑定 socket。"""
    if not options.get("reload"):
        raise click.UsageError("此入口仅用于 --reload；普通服务使用标准启动入口")
    if options.get("fd") is not None or options.get("uds") is not None:
        raise click.UsageError("开发热重载仅支持通过 host/port 创建 TCP 监听")
    if options.get("ws_per_message_deflate"):
        raise click.UsageError("WebSocket permessage-deflate 已禁用；不支持开启压缩")
    app_dir = options.pop("app_dir")
    if app_dir is not None:
        sys.path.insert(0, str(app_dir))
    if options.get("log_config") is None:
        options["log_config"] = LOGGING_CONFIG
    for name in ("reload_dirs", "reload_includes", "reload_excludes"):
        options[name] = list(options[name]) or None
    options["headers"] = [header.split(":", 1) for header in options["headers"]]
    config = Config(**options)
    if config.workers != 1:
        raise click.UsageError("开发热重载仅支持一个 HTTP 服务进程")
    # 不在父进程加载应用、创建事件循环或 bind_socket；旧进程退出后再由新进程绑定。
    stop_event = multiprocessing.get_context("spawn").Event()
    ServiceReload(
        config, stop_event=stop_event,
        target=partial(serve, config, stop_event=stop_event), sockets=[],
    ).run()


def build_command() -> click.Command:
    """复用当前 Uvicorn 的 CLI 定义，保留附加参数且不修改第三方全局对象。"""
    parameters = [copy(parameter) for parameter in uvicorn_command.params]
    for parameter in parameters:
        if parameter.name == "ws_per_message_deflate":
            parameter.default = False
        elif parameter.name == "ws":
            parameter.default = "wsproto"
    return click.Command(
        "amvision-http-reload",
        params=parameters,
        callback=run_reload,
        context_settings=dict(uvicorn_command.context_settings),
        help=__doc__,
    )


if __name__ == "__main__":
    build_command()()
