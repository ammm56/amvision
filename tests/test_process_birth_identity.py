"""内核进程出生标识的解析及严格拒绝边界。"""

from pathlib import Path
import os
import sys

import pytest

from backend.runtime.processes.birth_identity import read_process_birth_identity
from backend.runtime.processes.birth_identity import birth_identity_is_newer
from backend.runtime.processes.process_group import ProcessGroup
from tests.process_family_fixture import fake_birth_identity


def test_current_process_identity_is_stable():
    """同一个真实 PID 的重复读取必须一致。"""
    assert read_process_birth_identity(os.getpid()) == read_process_birth_identity(os.getpid())


@pytest.mark.parametrize("pid", [0, -1, True, "1"])
def test_invalid_pid_is_rejected(pid):
    """无效 PID 不能构成内核文件路径。"""
    with pytest.raises(ValueError, match="PID"):
        read_process_birth_identity(pid)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux proc stat 格式")
def test_linux_identity_parses_complex_comm(monkeypatch):
    """comm 中的空格、换行和括号不能改变 starttime 字段定位。"""
    boot = "a1234567-1234-1234-1234-123456789012"
    values = {
        "/proc/sys/kernel/random/boot_id": boot,
        "/proc/42/stat": "42 (name ) with\nspace)) " + " ".join(["S", *(["0"] * 18), "123456"]),
    }
    monkeypatch.setattr(Path, "read_text", lambda self: values[str(self)])
    assert read_process_birth_identity(42) == f"linux:{boot}:123456"


def test_old_group_record_is_rejected():
    """旧记录不得降级为 PID 或不可靠的墙钟比较。"""
    with pytest.raises(ValueError, match="当前版本"):
        ProcessGroup.open({"format_id": "amvision.process-group.v1", "pid": os.getpid()})


def test_birth_order_uses_kernel_value_not_display_time():
    """同代次内严格比较启动顺序，相同出生时间不能反向接管。"""
    assert birth_identity_is_newer(fake_birth_identity(2), fake_birth_identity(1))
    assert not birth_identity_is_newer(fake_birth_identity(1), fake_birth_identity(2))
    assert not birth_identity_is_newer(fake_birth_identity(2), fake_birth_identity(2))


@pytest.mark.parametrize("identity", [None, "", "other:0x1p0", "linux:bad:1"])
def test_birth_order_rejects_unverifiable_identity(identity):
    """格式损坏及跨平台身份不降级到墙钟字段。"""
    with pytest.raises(ValueError):
        birth_identity_is_newer(identity, fake_birth_identity(1))


def test_owner_stop_uses_birth_identity(monkeypatch):
    """展示时间变化不拒绝合法 owner；出生标识变化时禁止 kill。"""
    from types import SimpleNamespace
    from backend.runtime.processes import owner_control
    calls = []
    process = SimpleNamespace(pid=42, kill=lambda: calls.append("kill"),
                              wait=lambda **_: calls.append("wait"))
    monkeypatch.setattr(owner_control.psutil, "Process", lambda _: process)
    monkeypatch.setattr(owner_control, "read_process_birth_identity", lambda _: fake_birth_identity(1))
    monkeypatch.setattr(owner_control, "wait_owner_exit", lambda *_, **__: calls.append("wait"))
    owner_control.stop_owner({"pid": 42, "birth_identity": fake_birth_identity(1), "create_time": 999}, timeout=1)
    assert calls == ["kill", "wait"]
    calls.clear()
    with pytest.raises(RuntimeError, match="身份"):
        owner_control.stop_owner({"pid": 42, "birth_identity": fake_birth_identity(2)}, timeout=1)
    assert not calls


@pytest.mark.parametrize("state, same_birth, exited", [
    ("zombie", True, True), ("running", False, True), ("running", True, False),
])
def test_owner_exit_checks_generation_and_execution_state(monkeypatch, state, same_birth, exited):
    """PID 复用及 zombie 属于原代次退出，仍在执行的相同代次必须超时。"""
    from types import SimpleNamespace
    import psutil
    from backend.runtime.processes import owner_control

    identity = {"pid": 42, "birth_identity": fake_birth_identity(1)}
    monkeypatch.setattr(owner_control.psutil, "Process", lambda _: SimpleNamespace(status=lambda: state))
    monkeypatch.setattr(owner_control, "read_process_birth_identity", lambda _: fake_birth_identity(1 if same_birth else 2))
    if exited:
        owner_control.wait_owner_exit(identity, timeout=0)
    else:
        with pytest.raises(psutil.TimeoutExpired):
            owner_control.wait_owner_exit(identity, timeout=0)
