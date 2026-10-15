"""验收缺项、提前退出与异常清理不得被短功能通过覆盖。"""

import subprocess

import pytest

from tests.integration.acceptance_contract import (
    AcceptancePhases, acceptance_result, cleanup_all, positive_seconds, read_measurement,
)


def test_required_performance_failure_overrides_functional_success():
    """报告消费方只看 passed 时也不能误判。"""
    report = acceptance_result({"functional": "passed", "performance": "failed"}, ("functional", "performance"))
    assert report["status"] == "failed" and not report["passed"]
    assert acceptance_result({"resource": "observed"}, ("resource",))["status"] == "incomplete"


def test_cleanup_continues_after_stop_timeout():
    """stop 超时后仍尝试回收 supervisor 和关闭日志。"""
    calls = []
    def fail():
        """模拟停止子进程超时。"""
        raise subprocess.TimeoutExpired("stop", 60)
    errors = cleanup_all([("stop", fail), ("supervisor", lambda: calls.append("supervisor")),
                          ("logs", lambda: calls.append("logs"))])
    assert calls == ["supervisor", "logs"] and len(errors) == 1


def test_measurement_closes_before_cleanup(tmp_path, monkeypatch):
    """清理期不能延长真实持续负载时长。"""
    ticks = iter([0, 1, 11, 12])
    monkeypatch.setattr("tests.integration.acceptance_contract.time.monotonic", lambda: next(ticks))
    phases = AcceptancePhases(tmp_path / "phase.json", minimum_measure_seconds=10)
    for phase in ("warmup", "measure", "drain", "cleanup"):
        phases.enter(phase)
    record = read_measurement(phases.path)
    assert record["started"] == 1 and record["ended"] == 11
    with pytest.raises(ValueError):
        phases.enter("measure")


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_duration_rejected(value):
    """无效时长不能使验收空转通过。"""
    with pytest.raises(ValueError):
        positive_seconds(value, "duration")
