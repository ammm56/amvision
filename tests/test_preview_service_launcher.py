"""本地视觉服务的 WS 压缩默认值与显式覆盖验证。"""

import importlib.util
from pathlib import Path

import pytest


@pytest.mark.parametrize("extra, expected", [([], "false"), (["--", "--ws-per-message-deflate", "true"], "true")])
def test_service_launcher_prefers_low_latency_websocket(monkeypatch, extra, expected):
    """默认不用二次压缩；显式站点配置仍可覆盖，原始帧格式不变。"""
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
    assert module.main(["--app-root", str(root), *extra]) == 0
    args = captured["module_args"]
    assert args.count("--ws-per-message-deflate") == 1
    assert args[args.index("--ws-per-message-deflate")+1] == expected
