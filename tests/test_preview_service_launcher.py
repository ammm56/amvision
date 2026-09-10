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
