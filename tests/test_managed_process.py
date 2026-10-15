"""统一进程归属的真实 OS 回归；不替换派生、停止或退出判断。"""

from pathlib import Path
import subprocess
import os
import sys
import time
from threading import Event, Thread

import psutil
import pytest

from backend.runtime.processes.managed_process import ManagedProcess
from backend.runtime.processes.managed_spawn import managed_spawn_context
from backend.runtime.processes.ownership import OwnershipScope, SCOPE_ENV, PARENT_ENV


@pytest.fixture(autouse=True)
def isolated_ownership(tmp_path, monkeypatch):
    """每个用例独立登记，不触及开发服务的归属。"""
    scope = OwnershipScope.create(tmp_path / "ownership")
    monkeypatch.setenv(SCOPE_ENV, str(scope.root))
    monkeypatch.delenv(PARENT_ENV, raising=False)
    yield scope
    scope.stop()
    scope.require_empty()


def _spawn_family(directory):
    """spawn target 派生与命令入口相同的真实三层进程。"""
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("process_family_fixture.py")),
            "root",
            str(directory),
        ],
        check=True,
    )


def _touch_target(path):
    """只有启动门放行后才能留下执行标记。"""
    Path(path).touch()


def test_spawn_registration_failure_never_runs_target(tmp_path, monkeypatch):
    """spawn 绑定失败也必须停止门内进程并关闭控制 pipe。"""
    marker = tmp_path / "executed"

    def reject(*_args, **_kwargs):
        raise OSError("register rejected")

    monkeypatch.setattr(OwnershipScope, "register", reject)
    process = managed_spawn_context().Process(target=_touch_target, args=(marker,))
    with pytest.raises(OSError, match="register rejected"):
        process.start()
    assert not marker.exists()
    assert not process.is_alive()
    process.close()


def test_nested_managed_group_is_in_component_scope(tmp_path):
    """POSIX 新 session 子组与 Windows 嵌套 Job 共享显式归属边界。"""
    script = (
        "import os,sys; from backend.runtime.processes.managed_process import ManagedProcess; "
        "env=dict(os.environ); env.pop('AMVISION_PROCESS_PARENT',None); env.pop('AMVISION_PROCESS_SCOPE',None); "
        f"p=ManagedProcess([sys.executable,{str(Path(__file__).with_name('process_family_fixture.py'))!r},'root',{str(tmp_path)!r}],env=env); p.wait()"
    )
    process = ManagedProcess([sys.executable, "-c", script])
    try:
        deadline = time.perf_counter() + 20
        while not (tmp_path / "root-ready").exists():
            assert time.perf_counter() < deadline
            time.sleep(0.01)
        leaf = psutil.Process(int((tmp_path / "leaf-ready").read_text()))
        assert leaf.pid in process.scope.members(process.group_id)
        assert all(
            record["parent"] == process.group_id
            for key, record in process.scope.records().items()
            if key != process.group_id
        )
        process.stop(grace=0)
        leaf.wait(10)
        process.scope.require_empty(process.group_id)
    finally:
        process.stop(grace=0)


def test_spawn_orphans_block_recovery_until_group_stop(tmp_path, isolated_ownership):
    """独立运行时的异常停止不能以根 PID 消失代替恢复准入。"""
    process = managed_spawn_context().Process(target=_spawn_family, args=(tmp_path,))
    process.start()
    try:
        deadline = time.perf_counter() + 20
        while not (tmp_path / "root-ready").exists():
            assert process.is_alive()
            assert time.perf_counter() < deadline
            time.sleep(0.01)
        leaf = psutil.Process(int((tmp_path / "leaf-ready").read_text()))
        with pytest.raises(TimeoutError):
            isolated_ownership.require_empty()
        process.stop_group()
        isolated_ownership.require_empty()
        leaf.wait(10)
        assert not leaf.is_running()
    finally:
        process.stop_group()
        process.close()


def test_stop_one_group_does_not_stop_sibling():
    """同一运行中的兄弟组不会被组件级停止误杀。"""
    left = ManagedProcess([sys.executable, "-c", "import time; time.sleep(60)"])
    right = ManagedProcess([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        left.stop(grace=0)
        assert right.poll() is None
        right.scope.require_empty(left.group_id)
        with pytest.raises(TimeoutError):
            right.scope.require_empty(right.group_id)
    finally:
        left.stop(grace=0)
        right.stop(grace=0)


@pytest.mark.parametrize("python_entrypoint", [False, True])
def test_orphaned_grandchild_is_reaped(tmp_path, python_entrypoint):
    """中间进程先退出，平台组仍须包含并回收末级进程。"""
    process = ManagedProcess(
        [
            sys.executable,
            str(Path(__file__).with_name("process_family_fixture.py")),
            "root",
            str(tmp_path),
        ],
        python_entrypoint=python_entrypoint,
    )
    leaf = None
    try:
        deadline = time.perf_counter() + 20
        while not (tmp_path / "root-ready").exists():
            assert process.poll() is None
            assert time.perf_counter() < deadline
            time.sleep(0.01)
        leaf = psutil.Process(int((tmp_path / "leaf-ready").read_text()))
        assert leaf.pid in process.group.members()
        process.stop(grace=0, timeout=10)
        leaf.wait(10)
        assert not leaf.is_running()
        assert process.group.members() == ()
    finally:
        process.stop(grace=0, timeout=10)
        if leaf is not None and leaf.is_running():
            leaf.kill()
            leaf.wait(10)


def test_failed_registration_does_not_execute_target(tmp_path):
    """持久化归属失败时不能运行目标。"""
    marker = tmp_path / "executed"

    def reject(_process):
        raise OSError("registration failed")

    with pytest.raises(OSError, match="registration failed"):
        ManagedProcess(
            [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"],
            before_release=reject,
        )
    assert not marker.exists()


def test_normal_result_keeps_exit_code_and_repeated_stop_is_safe():
    """正常退出与重复 stop 不丢失业务退出码。"""
    process = ManagedProcess(
        [sys.executable, "-c", "raise SystemExit(7)"], stdout=subprocess.DEVNULL
    )
    assert process.wait(10) == 7
    process.finish()
    process.stop()
    assert process.returncode == 7


def test_communicate_does_not_close_owner_control_early():
    """Popen 输出收集不能把生命周期控制管道当作目标输入而关闭。"""
    process = ManagedProcess(
        [sys.executable, "-c", "import time; time.sleep(.1); print('ok')"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    output, _ = process.communicate(timeout=10)
    assert output.strip() == b"ok"
    assert process.returncode == 0
    process.scope.require_empty(process.group_id)


@pytest.mark.skipif(os.name != "nt", reason="Windows 无控制台启动边界")
def test_hidden_launcher_can_stop_group_without_console():
    """桌面启动器无控制台时仍须能完整停止受管组。"""
    script = (
        "import sys; from backend.runtime.processes.managed_process import ManagedProcess; "
        "p=ManagedProcess([sys.executable,'-c','import time; time.sleep(60)']); "
        "p.stop(grace=.05,timeout=3); print('stopped')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        creationflags=subprocess.CREATE_NO_WINDOW,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout.strip() == b"stopped"


@pytest.mark.parametrize("kind", ["command", "spawn"])
def test_root_crash_keeps_grandchild_owned_for_external_stop(
    tmp_path, isolated_ownership, kind
):
    """根和中间进程都退出后，从持久化归属重新打开仍可停止孙进程。"""
    if kind == "command":
        process = ManagedProcess(
            [
                sys.executable,
                str(Path(__file__).with_name("process_family_fixture.py")),
                "root",
                str(tmp_path),
            ]
        )
    else:
        process = managed_spawn_context().Process(
            target=_spawn_family, args=(tmp_path,)
        )
        process.start()
    try:
        deadline = time.perf_counter() + 20
        while not (tmp_path / "root-ready").exists():
            assert time.perf_counter() < deadline
            time.sleep(0.01)
        leaf = psutil.Process(int((tmp_path / "leaf-ready").read_text()))
        psutil.Process(process.pid).kill()
        if kind == "command":
            process.wait(10)
        else:
            process.join(10)
        assert leaf.is_running()
        reopened = OwnershipScope(isolated_ownership.root)
        with pytest.raises(TimeoutError):
            reopened.require_empty()
        reopened.stop()
        reopened.require_empty()
        # Windows 的 terminated 内核对象可因外部句柄继续存在；等待退出信号才是执行终止判据。
        leaf.wait(10)
    finally:
        if kind == "command":
            process.finish()
        else:
            process.stop_group()
            process.close()


def test_scope_seal_rejects_target_before_execution(tmp_path, isolated_ownership):
    """停止封闭后不能启动下一代；注册失败不能放行业务 target。"""
    marker = tmp_path / "executed"
    isolated_ownership.seal()
    with pytest.raises(RuntimeError, match="运行已停止"):
        ManagedProcess([sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"])
    assert not marker.exists()


def test_scope_rejects_path_as_group_id(tmp_path, isolated_ownership):
    """损坏的记录不得导致归属目录以外写停止标记。"""
    with pytest.raises(ValueError, match="标识无效"):
        isolated_ownership.stop(root_id="../outside")
    assert not (isolated_ownership.root.parent / "outside.stopping").exists()


def test_scope_stop_lock_wait_uses_stop_budget(isolated_ownership):
    """归属锁竞争不能给停止操作追加独立的十秒等待预算。"""
    ready, release = Event(), Event()

    def hold():
        with isolated_ownership.guard():
            ready.set()
            release.wait(5)

    thread = Thread(target=hold)
    thread.start()
    try:
        assert ready.wait(3)
        started = time.perf_counter()
        with pytest.raises(TimeoutError, match="登记锁超时"):
            isolated_ownership.stop(timeout=0.05)
        assert time.perf_counter() - started < 0.5
    finally:
        release.set()
        thread.join(3)


def test_spawn_double_start_keeps_original_group():
    """误重复 start 只能报错，不能覆盖原有组身份或终止原进程。"""
    process = managed_spawn_context().Process(target=time.sleep, args=(60,))
    process.start()
    try:
        group = process._group
        with pytest.raises(RuntimeError, match="重复启动"):
            process.start()
        assert process._group is group
        assert process.is_alive()
    finally:
        process.close()


@pytest.mark.parametrize("python_entrypoint", [False, True])
def test_owner_crash_reaps_group_without_monitor_thread(tmp_path, python_entrypoint):
    """owner 强制退出时仍须回收子组，不能依赖业务监视线程继续运行。"""
    owner_root = tmp_path / "owner"
    owner_root.mkdir()
    script = (
        "from pathlib import Path; import os,sys,time; "
        "from backend.runtime.processes.ownership import OwnershipScope; "
        "from backend.runtime.processes.managed_process import ManagedProcess; "
        f"scope=OwnershipScope.create(Path({str(owner_root)!r})); "
        "os.environ['AMVISION_PROCESS_SCOPE']=str(scope.root); "
        "os.environ.pop('AMVISION_PROCESS_PARENT',None); "
        f"p=ManagedProcess([sys.executable,{str(Path(__file__).with_name('process_family_fixture.py'))!r},'root',{str(tmp_path)!r}],python_entrypoint={python_entrypoint!r}); "
        "time.sleep(60)"
    )
    owner = subprocess.Popen([sys.executable, "-c", script], env=dict(os.environ))
    leaf = None
    try:
        deadline = time.perf_counter() + 20
        while not (tmp_path / "root-ready").exists():
            assert owner.poll() is None
            assert time.perf_counter() < deadline
            time.sleep(0.01)
        leaf = psutil.Process(int((tmp_path / "leaf-ready").read_text()))
        owner.kill()
        owner.wait(10)
        leaf.wait(10)
        assert not leaf.is_running()
        for path in owner_root.iterdir():
            OwnershipScope(path).require_empty()
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(10)
        for path in owner_root.iterdir():
            OwnershipScope(path).stop()


@pytest.mark.parametrize("entry", ["script", "module"])
def test_python_entrypoint_executes_in_registered_pid(tmp_path, entry):
    """脚本和模块直接在登记 PID 内运行，支持 main/spawn、stdin EOF 和退出码。"""
    import json

    script = tmp_path / "entry.py"
    script.write_text(
        "import json,os,sys,multiprocessing,subprocess\n"
        "def child():\n    print('spawn-ok', flush=True)\n"
        "if __name__ == '__main__':\n"
        "    assert subprocess.check_output([sys.executable,'-c','import sys; print(sys.stdin.read() == chr(0)[:0])'],timeout=3).strip() == b'True'\n"
        "    p=multiprocessing.get_context('spawn').Process(target=child)\n"
        "    p.start(); p.join(10); assert p.exitcode == 0\n"
        "    print(json.dumps({'pid':os.getpid(),'argv':sys.argv[1:],'stdin':sys.stdin.read(),'exe':sys.executable}))\n"
        "    raise SystemExit(7)\n",
        encoding="utf-8",
    )
    arguments = [str(script)] if entry == "script" else ["-m", "entry"]
    process = ManagedProcess(
        [sys.executable, *arguments, "arg with spaces", "--flag"],
        python_entrypoint=True, cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    output, error = process.communicate(timeout=20)
    assert process.returncode == 7, error.decode(errors="replace")
    assert output.splitlines()[0] == b"spawn-ok"
    details = json.loads(output.splitlines()[1])
    assert details == {"pid": process.pid, "argv": ["arg with spaces", "--flag"],
                       "stdin": "", "exe": sys.executable}
    process.scope.require_empty(process.group_id)


def test_python_entrypoint_registration_failure_never_executes(tmp_path):
    """直接入口仍必须在目标代码执行前完成归属登记。"""
    marker = tmp_path / "executed"
    script = tmp_path / "entry.py"
    script.write_text(f"open({str(marker)!r}, 'w').close()", encoding="utf-8")

    def reject(_process):
        raise OSError("registration failed")

    with pytest.raises(OSError, match="registration failed"):
        ManagedProcess([sys.executable, str(script)], python_entrypoint=True, before_release=reject)
    assert not marker.exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux 启动时间墙钟换算")
@pytest.mark.parametrize("phase", ["startup", "recovery"])
def test_wall_clock_shift_keeps_group_identity(monkeypatch, tmp_path, phase):
    """父端墙钟基准改变不影响启动门、恢复拒绝及真实整组停止。"""
    original = psutil.Process.create_time
    script = tmp_path / "target.py"
    script.write_text("import time; time.sleep(60)", encoding="utf-8")
    process = None
    try:
        if phase == "recovery":
            process = ManagedProcess([sys.executable, "-c", "import time; time.sleep(60)"])
        with monkeypatch.context() as patch:
            patch.setattr(psutil.Process, "create_time", lambda self: original(self) + (0 if self.pid == os.getpid() else 2))
            if process is None:
                process = ManagedProcess(
                    [sys.executable, str(script)],
                    python_entrypoint=True,
                )
            with pytest.raises(TimeoutError):
                process.scope.require_empty(process.group_id)
            process.stop(grace=0)
            process.scope.require_empty(process.group_id)
    finally:
        if process is not None:
            process.stop(grace=0)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux 启动时间墙钟换算")
def test_wall_clock_shift_does_not_create_new_scope(monkeypatch, isolated_ownership):
    """同一 owner 的墙钟变化不能产生另一个未被原停止入口覆盖的 scope。"""
    original = psutil.Process.create_time
    monkeypatch.setattr(psutil.Process, "create_time", lambda self: original(self) + 2)
    assert OwnershipScope.current().root == isolated_ownership.root


@pytest.mark.skipif(os.name == "nt", reason="POSIX 归属守护身份")
def test_wrong_guardian_birth_identity_is_rejected():
    """PID/PGID 一致但出生标识错误时不能打开归属，也不应杀死原进程。"""
    from backend.runtime.processes.process_group import ProcessGroup

    process = ManagedProcess([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        reference = process.group.reference()
        reference["anchor"] = {**reference["anchor"], "birth_identity": "wrong"}
        with pytest.raises(RuntimeError, match="拒绝恢复"):
            ProcessGroup.open(reference)
        assert process.poll() is None
    finally:
        process.stop(grace=0)
