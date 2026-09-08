"""启动器停止目标与状态清理契约测试，不操作真实视觉服务。"""

import importlib.util
import json
from pathlib import Path


def _module(name: str, path: str):
    """从源码入口载入指定 launcher 模块。"""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_expected_identity_refuses_different_root(tmp_path, monkeypatch):
    """旧请求不能停止同目录的新实例。"""
    stop = _module("launcher_stop_contract", "runtimes/launchers/full/stop_amvision_full.py")
    state = tmp_path / "runtime-state.json"
    state.write_text(json.dumps({"format_id": stop.FULL_SUPERVISOR_STATE_FORMAT_ID, "root_process": {"pid": 20}}))
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"format_id": "amvision.launcher-stop-target.v1", "root_process": {"pid": 10}}))
    monkeypatch.setattr(stop, "_stop_recorded_process", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not stop")))
    assert stop.main(["--app-root", str(tmp_path), "--state-file", str(state), "--expected-root-identity-file", str(request), "--graceful-only"]) == 2
    assert json.loads(state.read_text())["root_process"]["pid"] == 20


def test_graceful_timeout_never_force_kills(tmp_path, monkeypatch):
    """等待超时保留诊断，不进入旧 CLI 强杀分支。"""
    stop = _module("launcher_stop_graceful", "runtimes/launchers/full/stop_amvision_full.py")
    state = tmp_path / "runtime-state.json"
    state.write_text(json.dumps({"format_id": stop.FULL_SUPERVISOR_STATE_FORMAT_ID, "root_process": {"pid": 20}, "components": []}))
    monkeypatch.setattr(stop, "process_identity_matches", lambda _: True)
    monkeypatch.setattr(stop, "_wait_root_process_exit", lambda *a, **k: False)
    monkeypatch.setattr(stop, "_stop_recorded_process", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not kill")))
    assert stop.main(["--app-root", str(tmp_path), "--state-file", str(state), "--graceful-only"]) == 2
    assert state.exists()


def test_cleanup_preserves_new_state_and_failed_diagnostic(tmp_path):
    """条件清理不删除新 root 或需要保留的故障摘要。"""
    common = _module("launcher_common_cleanup", "runtimes/launchers/common.py")
    state = tmp_path / "runtime-state.json"
    status = tmp_path / "launcher-status.json"
    state.write_text(json.dumps({"root_process": {"pid": 2}}))
    status.write_text(json.dumps({"root_process": {"pid": 1}, "state": "failed"}))
    common.clear_full_state(state, {"pid": 1})
    assert state.exists() and status.exists()


def test_wait_loop_observes_startup_shutdown(monkeypatch):
    """就绪轮询在探测前响应当前 root 的退出意图。"""
    start = _module("launcher_start_check", "runtimes/launchers/full/start_amvision_full.py")
    def cancel():
        """模拟已有、绑定身份的停止请求。"""
        raise KeyboardInterrupt
    monkeypatch.setattr(start, "_active_shutdown_check", cancel)
    import pytest
    with pytest.raises(KeyboardInterrupt):
        start._wait_for_backend_service_ready(host="127.0.0.1", port=1, timeout_seconds=1, process=None)
