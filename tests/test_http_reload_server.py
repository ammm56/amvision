"""开发热重载配置和监听所有权验证。"""

from unittest.mock import Mock

from click.testing import CliRunner
import pytest
from uvicorn import Config
from uvicorn.main import main as uvicorn_command

from backend.service.infrastructure.http import reload_server


def test_reload_parent_never_binds_or_loads_application(monkeypatch, tmp_path):
    """父进程只监控文件，完整透传 HTTP/WS 配置；子进程绑定自己的监听。"""
    reloader = Mock()
    monkeypatch.setattr(reload_server, "ServiceReload", reloader)
    monkeypatch.setattr(Config, "bind_socket", Mock(side_effect=AssertionError("parent bind")))
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    result = CliRunner().invoke(reload_server.build_command(), [
        "module_not_imported_in_parent:app", "--reload", "--reload-dir", str(tmp_path),
        "--host", "127.0.0.1", "--port", "5600", "--lifespan", "off",
        "--loop", "backend.service.infrastructure.http.windows_event_loop:create_loop",
        "--header", "X-Test:a:b", "--timeout-graceful-shutdown", "17",
        "--ws-max-size", "2097152", "--no-access-log",
    ])
    assert result.exit_code == 0, result.output + str(result.exception)
    config = reloader.call_args.args[0]
    assert not config.loaded
    assert config.port == 5600 and config.host == "127.0.0.1"
    assert config.timeout_graceful_shutdown == 17 and config.ws_max_size == 2097152
    assert config.ws_per_message_deflate is False and config.access_log is False
    assert config.ws == "wsproto"
    assert config.headers == [["X-Test", "a:b"]]
    assert config.reload_dirs == [tmp_path]
    assert reloader.call_args.kwargs["sockets"] == []
    server = Mock()
    monkeypatch.setattr(reload_server, "ReloadServer", server)
    reloader.call_args.kwargs["target"](sockets=[])
    server.assert_called_once_with(config, reloader.call_args.kwargs["stop_event"])
    server.return_value.run.assert_called_once_with()
    # 创建项目命令不能改变 Uvicorn 原命令的默认值。
    assert next(p for p in uvicorn_command.params if p.name == "ws_per_message_deflate").default is True


@pytest.mark.parametrize("arguments", [
    [], ["--reload", "--fd", "12"], ["--reload", "--uds", "test.sock"],
    ["--reload", "--workers", "2"], ["--reload", "--ws-per-message-deflate", "true"],
])
def test_reload_rejects_unsupported_configuration(monkeypatch, arguments):
    """不能通过附加选项引入共享监听、多进程或压缩。"""
    reloader = Mock()
    monkeypatch.setattr(reload_server, "ServiceReload", reloader)
    result = CliRunner().invoke(reload_server.build_command(), ["unused:app", *arguments])
    assert result.exit_code == 2
    reloader.assert_not_called()


def test_reload_rejects_environment_workers(monkeypatch):
    """WEB_CONCURRENCY 不能绕过单服务进程约束。"""
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    result = CliRunner().invoke(reload_server.build_command(), ["unused:app", "--reload"])
    assert result.exit_code == 2


def test_child_rejects_shared_listener():
    """防止后续接线重新把父进程 socket 交给子进程。"""
    with pytest.raises(ValueError, match="socket"):
        reload_server.serve(Mock(), stop_event=Mock(), sockets=[Mock()])


def test_windows_reload_child_restores_console_interrupt(monkeypatch):
    """只在子进程启用 Ctrl+C，不改变父进程组控制规则。"""
    import ctypes
    kernel = Mock()
    kernel.SetConsoleCtrlHandler.return_value = 1
    monkeypatch.setattr(reload_server.sys, 'platform', 'win32')
    monkeypatch.setattr(ctypes, 'WinDLL', Mock(return_value=kernel), raising=False)
    reload_server.enable_reload_interrupt()
    kernel.SetConsoleCtrlHandler.assert_called_once_with(None, False)


@pytest.mark.parametrize("stop_during_restart", [False, True])
def test_reload_event_orders_old_exit_before_new_start(monkeypatch, tmp_path, stop_during_restart):
    """先通知并等待旧服务；同时收到退出时不能再派生新服务。"""
    from threading import Event

    event = Event()
    reload = reload_server.ServiceReload(
        Config("unused:app", reload=True, reload_dirs=[str(tmp_path)]),
        stop_event=event, target=Mock(), sockets=[],
    )
    old = Mock()
    reload.process = old

    def joined():
        assert event.is_set()
        if stop_during_restart:
            reload.should_exit.set()

    old.join.side_effect = joined
    new = Mock()
    factory = Mock(return_value=new)
    monkeypatch.setattr(reload_server, "get_subprocess", factory)
    reload.restart()
    old.join.assert_called_once_with()
    if stop_during_restart:
        factory.assert_not_called()
    else:
        assert not event.is_set()
        new.start.assert_called_once_with()
        reload.shutdown()
        assert event.is_set()
        new.join.assert_called_once_with()


def test_reload_server_tick_observes_stop_event():
    """原服务循环收到事件后进入 Uvicorn 正常关闭，无额外监视线程。"""
    import asyncio
    from threading import Event

    event = Event()
    server = reload_server.ReloadServer(Config("unused:app"), event)
    assert asyncio.run(server.on_tick(1)) is False
    event.set()
    assert asyncio.run(server.on_tick(2)) is True
    assert server.should_exit
