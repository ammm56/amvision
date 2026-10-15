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


def test_identity_access_failure_is_not_treated_as_exit(monkeypatch):
    """无法核对身份不能放行恢复或清理归属记录。"""
    import psutil
    common = _load_launcher_common()
    identity = common.read_process_identity(os.getpid())

    def denied(_pid):
        raise psutil.AccessDenied(os.getpid())

    monkeypatch.setattr(common, "read_process_identity", denied)
    with pytest.raises(psutil.AccessDenied):
        common.process_identity_matches(identity)


def test_standalone_process_probe_loads_code_root_without_pythonpath(tmp_path):
    """独立入口显式解析项目，不依赖调用进程的 PYTHONPATH 或当前目录。"""
    script = Path(__file__).resolve().parents[1] / "runtimes/launchers/inspect_process.py"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run([sys.executable, str(script), "--pid", str(os.getpid())],
                               cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    value = json.loads(completed.stdout)
    assert value["format_id"] == "amvision.launcher-process.v2"
    assert value["identity"]["birth_identity"] == _load_launcher_common().read_process_identity(os.getpid())["birth_identity"]


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
        from types import SimpleNamespace
        return SimpleNamespace(wait=lambda: 0, stop=lambda **_: None)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("backend.runtime.processes.managed_process.ManagedProcess", run)

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
        from types import SimpleNamespace
        def wait():
            raise KeyboardInterrupt
        return SimpleNamespace(wait=wait, stop=lambda **_: None)

    monkeypatch.setattr("backend.runtime.processes.managed_process.ManagedProcess", run)

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


def test_release_python_resolution_uses_platform_layout(tmp_path):
    """只接受当前平台随包解释器；缺失时不使用开发环境。"""
    common = _load_launcher_common()
    (tmp_path / "manifests" / "release-profiles").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="禁止回退"):
        common.resolve_python_executable(tmp_path)
    executable = tmp_path / ("python/python.exe" if os.name == "nt" else "python/bin/python3")
    executable.parent.mkdir(parents=True)
    executable.touch()
    assert common.resolve_python_executable(tmp_path) == str(executable)


@pytest.mark.skipif(os.name == "nt", reason="POSIX venv 解释器符号链接")
def test_explicit_python_preserves_venv_symlink(tmp_path):
    """解析显式解释器不能绕过 venv 的 pyvenv.cfg。"""
    common = _load_launcher_common()
    executable = tmp_path / "python"
    executable.symlink_to(sys.executable)
    assert common.resolve_python_executable(tmp_path, str(executable)) == str(executable)


@pytest.mark.parametrize("spawn_descendant", [False, True])
def test_managed_launcher_module_reuses_registered_root(tmp_path, spawn_descendant):
    """已登记 launcher 不额外驻留等待进程，模块仍获得正确 argv/env/cwd。"""
    from backend.runtime.processes.managed_process import ManagedProcess

    root = Path(__file__).resolve().parents[1]
    (tmp_path / "backend").mkdir()
    modules = tmp_path / "modules"
    modules.mkdir()
    descendant = (
        "import subprocess\n"
        f"subprocess.run([sys.executable,{str(root / 'tests' / 'process_family_fixture.py')!r},"
        f"'middle',{str(tmp_path)!r}],check=True,timeout=20)\n"
    ) if spawn_descendant else ""
    (modules / "target_module.py").write_text(
        "import json,os,sys\n"
        + descendant +
        "print(json.dumps({'pid':os.getpid(),'cwd':os.getcwd(),'args':sys.argv[1:],"
        "'value':os.environ['LAUNCH_TEST_VALUE']}),flush=True)\n",
        encoding="utf-8",
    )
    launcher = tmp_path / "launcher.py"
    launcher.write_text(
        f"import sys; sys.path.insert(0,{str(root / 'runtimes' / 'launchers')!r})\n"
        "from pathlib import Path\nfrom common import run_python_module\n"
        f"raise SystemExit(run_python_module(app_root=Path({str(tmp_path)!r}),"
        "module_name='target_module',module_args=['value with spaces'],"
        f"extra_env={{'LAUNCH_TEST_VALUE':'configured','PYTHONPATH':{str(modules) + os.pathsep + str(root)!r}}}))\n",
        encoding="utf-8",
    )
    process = ManagedProcess([sys.executable, str(launcher)], python_entrypoint=True,
                             env={**os.environ, "PYTHONPATH": str(root)},
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate(timeout=20)
    assert process.returncode == 0, error.decode(errors="replace")
    details = json.loads(output)
    assert details == {"pid": process.pid, "cwd": str(tmp_path),
                       "args": ["value with spaces"], "value": "configured"}
    process.scope.require_empty(process.group_id)
    if spawn_descendant:
        import psutil

        # middle 已先退出；launcher/module 正常退出后仍必须回收持文件的 leaf。
        assert not psutil.pid_exists(int((tmp_path / "leaf-ready").read_text()))
        (tmp_path / "held-file").unlink()


def test_managed_launcher_refuses_sealed_scope(tmp_path, monkeypatch):
    """当前 PID 即使已登记，停止封闭后也不能开始新的模块入口。"""
    from backend.runtime.processes.managed_process import ManagedProcess
    from backend.runtime.processes.ownership import OwnershipScope, SCOPE_ENV, PARENT_ENV

    scope = OwnershipScope.create(tmp_path / "scope")
    monkeypatch.setenv(SCOPE_ENV, str(scope.root))
    monkeypatch.delenv(PARENT_ENV, raising=False)

    root = Path(__file__).resolve().parents[1]
    script = tmp_path / "sealed.py"
    script.write_text(
        "from backend.runtime.processes.ownership import OwnershipScope\n"
        "scope=OwnershipScope.current()\nscope.seal()\n"
        "OwnershipScope.current_process_is_group_root()\n",
        encoding="utf-8",
    )
    process = ManagedProcess([sys.executable, str(script)], python_entrypoint=True,
                             env={**os.environ, "PYTHONPATH": str(root)},
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _, error = process.communicate(timeout=20)
    assert process.returncode != 0
    assert "运行已停止" in error.decode("utf-8", errors="replace")
    process.scope.require_empty(process.group_id)
