"""发行包验收不能将未完成负载或非法阈值登记为通过。"""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.integration.test_release_full_stack_acceptance import (
    _build_release_resource_gate,
    _require_optional_workload_completed,
)
from tests.integration.deployment_workflow_trigger_soak import parse_args
from tests.integration.release_environment import build_release_test_environment
from tests.integration import test_release_full_stack_acceptance as acceptance


def test_fault_injection_only_kills_verified_root(monkeypatch) -> None:
    """验收不能自行杀后代，掩盖正式监督器的组回收缺陷。"""
    calls = []
    process = SimpleNamespace(kill=lambda: calls.append("kill"))
    monkeypatch.setattr(acceptance, "_process_ref_is_alive", lambda *_args: True)
    monkeypatch.setattr(acceptance.psutil, "Process", lambda _pid: process)
    monkeypatch.setattr(acceptance, "read_process_birth_identity", lambda _: "birth-1")
    monkeypatch.setattr(acceptance, "wait_owner_exit", lambda identity, **kwargs: calls.append((identity, kwargs)))
    acceptance._terminate_exact_component_root(pid=42, birth_identity="birth-1")
    assert calls == ["kill", ({"pid": 42, "birth_identity": "birth-1"}, {"timeout": 10})]


def test_fault_injection_rejects_reused_pid(monkeypatch) -> None:
    """二次身份校验失败不能对复用 PID 注入故障。"""
    process = SimpleNamespace()
    monkeypatch.setattr(acceptance, "_process_ref_is_alive", lambda *_args: True)
    monkeypatch.setattr(acceptance.psutil, "Process", lambda _pid: process)
    monkeypatch.setattr(acceptance, "read_process_birth_identity", lambda _: "birth-2")
    with pytest.raises(AssertionError, match="PID 已被复用"):
        acceptance._terminate_exact_component_root(pid=42, birth_identity="birth-1")


def test_release_service_does_not_inherit_development_environment(monkeypatch, tmp_path: Path) -> None:
    """工具运行在 conda 中不意味着发行服务可以借用 conda 和开发数据库。"""
    monkeypatch.setenv("CONDA_PREFIX", "development-python")
    monkeypatch.setenv("PYTHONPATH", "development-modules")
    monkeypatch.setenv("PATH", "development-python;development-node")
    monkeypatch.setenv("AMVISION_DATABASE__URL", "sqlite:///development.db")
    environment = build_release_test_environment(tmp_path)
    assert "CONDA_PREFIX" not in environment and "PYTHONPATH" not in environment
    assert "AMVISION_DATABASE__URL" not in environment
    assert "development" not in environment["PATH"]
    assert str(tmp_path / "python") in environment["PATH"]
    assert environment["PYTHONNOUSERSITE"] == "1"


@pytest.mark.parametrize("code", [None, 1, -1])
def test_unfinished_or_failed_workload_cannot_pass(code: int | None) -> None:
    """后台进程仍在运行时退出验收，只能报告未完成。"""
    process = SimpleNamespace(process=SimpleNamespace(poll=lambda: code), log_file=Path("workload.log"))
    with pytest.raises(AssertionError, match="负载尚未正常完成"):
        _require_optional_workload_completed(process)


def test_completed_workload_passes() -> None:
    """只有正常退出的负载允许完成验收。"""
    process = SimpleNamespace(process=SimpleNamespace(poll=lambda: 0), log_file=Path("workload.log"))
    _require_optional_workload_completed(process)


@pytest.mark.parametrize("limits", ['{"rss_bytes": NaN}', '{"rss_bytes": -1}', '{"rss_bytes": true}', '{"typo": 1}', '[]'])
def test_invalid_resource_limits_are_rejected(monkeypatch, limits: str) -> None:
    """错拼指标和非法数值必须报错，不能静默跳过门禁。"""
    monkeypatch.setenv("AMVISION_RELEASE_FULL_RESOURCE_LIMITS_JSON", limits)
    with pytest.raises(ValueError, match="资源增长上限"):
        _build_release_resource_gate(os.getpid())


@pytest.mark.parametrize("option", ["--duration-seconds", "--http-timeout-seconds", "--sample-interval-seconds"])
def test_soak_nan_does_not_skip_duration_or_timeouts(option: str) -> None:
    """非有限参数不能令验收窗口被跳过或无法结束。"""
    with pytest.raises(SystemExit):
        parse_args([option, "nan"])
