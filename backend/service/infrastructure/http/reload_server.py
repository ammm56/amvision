"""开发热重载入口：监听 socket 随服务子进程创建和关闭，不跨 IOCP 复用。"""

from __future__ import annotations

from copy import copy
from functools import partial
from socket import socket
import sys

import click
from uvicorn import Config, Server
from uvicorn.config import LOGGING_CONFIG
from uvicorn.main import main as uvicorn_command
from uvicorn.supervisors import ChangeReload


def serve(config: Config, sockets: list[socket] | None = None) -> None:
    """在子进程内绑定监听；config 为服务配置，sockets 必须为空。"""
    if sockets:
        raise ValueError("开发热重载不接受父进程共享的监听 socket")
    Server(config).run()


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
    ChangeReload(config, target=partial(serve, config), sockets=[]).run()


def build_command() -> click.Command:
    """复用当前 Uvicorn 的 CLI 定义，保留附加参数且不修改第三方全局对象。"""
    parameters = [copy(parameter) for parameter in uvicorn_command.params]
    for parameter in parameters:
        if parameter.name == "ws_per_message_deflate":
            parameter.default = False
    return click.Command(
        "amvision-http-reload",
        params=parameters,
        callback=run_reload,
        context_settings=dict(uvicorn_command.context_settings),
        help=__doc__,
    )


if __name__ == "__main__":
    build_command()()
