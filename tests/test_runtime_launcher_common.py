"""发布 launcher 共用辅助测试。"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest


def _load_launcher_common() -> ModuleType:
    """按文件加载 launcher common，避免依赖其目录成为 Python package。"""

    common_path = (
        Path(__file__).resolve().parents[1] / "runtimes" / "launchers" / "common.py"
    )
    spec = importlib.util.spec_from_file_location("runtime_launcher_common_test", common_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 launcher common: {common_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_is_pid_alive_recognizes_current_and_missing_process() -> None:
    """验证存活判断不依赖 tasklist 权限或本地化输出。"""

    launcher_common = _load_launcher_common()

    assert launcher_common.is_pid_alive(os.getpid()) is True
    assert launcher_common.is_pid_alive(2_147_483_647) is False


@pytest.mark.skipif(os.name != "nt", reason="验证 Windows 读句柄不共享删除时的真实文件占用")
def test_full_json_publish_survives_concurrent_windows_reader(tmp_path: Path) -> None:
    """状态读取与原子替换并发时，写入应在读句柄释放后完成。"""
    from threading import Event, Thread

    common = _load_launcher_common()
    path = tmp_path / "runtime-state.json"
    path.write_text('{"generation": 1}', encoding="utf-8")
    opened = Event()

    def read_state() -> None:
        """模拟未持有写锁的状态轮询者。"""
        with path.open("rb"):
            opened.set()
            Event().wait(0.15)

    reader = Thread(target=read_state)
    reader.start()
    assert opened.wait(2)
    try:
        common.write_full_json(path, {"generation": 2})
    finally:
        reader.join(2)
    assert json.loads(path.read_text(encoding="utf-8")) == {"generation": 2}
    assert not list(tmp_path.glob("*.tmp"))


def test_full_json_permanent_replace_error_preserves_previous_state(tmp_path: Path, monkeypatch) -> None:
    """超出重试窗口仍报告错误，保留旧状态并回收本次暂存文件。"""
    common = _load_launcher_common()
    path = tmp_path / "runtime-state.json"
    path.write_text('{"generation": 1}', encoding="utf-8")
    timestamps = iter([0.0, 6.0])
    monkeypatch.setattr(common.time, "monotonic", lambda: next(timestamps))

    def fail_replace(*args) -> None:
        """模拟不可恢复的 Windows 拒绝访问。"""
        error = PermissionError("replacement denied")
        error.winerror = 5
        raise error

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(PermissionError, match="replacement denied"):
        common.write_full_json(path, {"generation": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"generation": 1}
    assert not list(tmp_path.glob("*.tmp"))


def test_run_python_module_resolves_explicit_relative_python_before_cwd_change(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """显式相对 Python 路径不能在发行目录 cwd 下被重复解析。"""

    launcher_common = _load_launcher_common()
    app_root = tmp_path / "release"
    (app_root / "app" / "backend").mkdir(parents=True)
    (app_root / "config").mkdir()
    expected_python = tmp_path / "runtime" / "python.exe"
    expected_python.parent.mkdir()
    expected_python.touch()
    calls: list[dict[str, object]] = []

    def run(command, **kwargs):
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher_common.subprocess, "run", run)

    result = launcher_common.run_python_module(
        app_root=app_root,
        module_name="backend.maintenance.main",
        module_args=["validate-layout"],
        python_executable=str(Path("runtime") / "python.exe"),
    )

    assert result == 0
    assert calls[0]["command"][0] == str(expected_python.resolve())
    assert calls[0]["cwd"] == str(app_root)


def test_run_python_module_returns_standard_code_on_keyboard_interrupt(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """交互式停止 launcher 时不应把 KeyboardInterrupt 继续抛到控制台。"""

    launcher_common = _load_launcher_common()
    app_root = tmp_path / "source"
    (app_root / "backend").mkdir(parents=True)

    def run(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(launcher_common.subprocess, "run", run)

    result = launcher_common.run_python_module(
        app_root=app_root,
        module_name="backend.inference.main",
        module_args=[],
        python_executable=sys.executable,
    )

    assert result == 130


def test_full_launcher_templates_can_run_from_source_layout() -> None:
    """full start/stop 模板在复制前也必须能加载共用 launcher。"""

    repository_root = Path(__file__).resolve().parents[1]
    for script_name in ("start_amvision_full.py", "stop_amvision_full.py"):
        script = repository_root / "runtimes" / "launchers" / "full" / script_name
        completed = subprocess.run(
            [sys.executable, str(script), "--help"],
            cwd=repository_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout
