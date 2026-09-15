"""本地视觉服务固定禁用 WS 压缩的入口验证。"""

import importlib.util
from pathlib import Path

import pytest


@pytest.mark.parametrize("extra, rejected", [
    ([], False), (["--", "--ws-per-message-deflate", "false"], False),
    (["--", "--ws-per-message-deflate=false"], False),
    (["--", "--ws-per-message-deflate", "true"], True),
    (["--", "--ws-per-message-deflate=true"], True),
    (["--", "--ws-per-message-deflate"], True),
])
def test_service_launcher_prefers_low_latency_websocket(monkeypatch, extra, rejected):
    """所有允许的启动参数只生成一个 false；开启压缩时拒绝启动。"""
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("preview_service_launcher_test", root / "runtimes/launchers/service/start_backend_service.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ensure_windows_long_paths_enabled", lambda **kwargs: True)
    captured = {}
    def run(**kwargs):
        captured.update(kwargs)
        return 0
    monkeypatch.setattr(module, "run_python_module", run)
    if rejected:
        with pytest.raises(SystemExit) as error:
            module.main(["--app-root", str(root), *extra])
        assert error.value.code == 2
        assert not captured
        return
    assert module.main(["--app-root", str(root), *extra]) == 0
    args = captured["module_args"]
    assert args.count("--ws-per-message-deflate") == 1
    assert args[args.index("--ws-per-message-deflate")+1] == "false"


@pytest.mark.parametrize("platform,extra,expected", [
    ("win32", [], "uvicorn"),
    ("win32", ["--reload"], "backend.service.infrastructure.http.reload_server"),
    ("win32", ["--", "--reload"], "backend.service.infrastructure.http.reload_server"),
    ("linux", ["--reload"], "uvicorn"),
])
def test_service_launcher_routes_reload(monkeypatch, platform, extra, expected):
    """只有 Windows 热重载改用子进程独立监听，其余启动路径保持原样。"""
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("reload_service_launcher_test", root / "runtimes/launchers/service/start_backend_service.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.sys, "platform", platform)
    monkeypatch.setattr(module, "ensure_windows_long_paths_enabled", lambda **kwargs: True)
    captured = {}
    def run(**kwargs):
        captured.update(kwargs)
        return 0
    monkeypatch.setattr(module, "run_python_module", run)
    assert module.main(["--app-root", str(root), *extra]) == 0
    assert captured["module_name"] == expected
    assert captured["module_args"].count("--reload") == bool(extra)
