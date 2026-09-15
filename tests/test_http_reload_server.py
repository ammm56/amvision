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
    monkeypatch.setattr(reload_server, "ChangeReload", reloader)
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
    assert config.headers == [["X-Test", "a:b"]]
    assert config.reload_dirs == [tmp_path]
    assert reloader.call_args.kwargs["sockets"] == []
    server = Mock()
    monkeypatch.setattr(reload_server, "Server", server)
    reloader.call_args.kwargs["target"](sockets=[])
    server.assert_called_once_with(config)
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
    monkeypatch.setattr(reload_server, "ChangeReload", reloader)
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
        reload_server.serve(Mock(), sockets=[Mock()])
