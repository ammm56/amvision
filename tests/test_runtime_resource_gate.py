"""长时间验收不丢失早期退化，资源样本不足时不能通过。"""

from threading import Event
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
import psutil

from tests.integration.runtime_resource_gate import BoundedHistory, ResourceGate
from tests.integration.deployment_workflow_trigger_soak import LaneMetrics, _stopping_executor


def test_history_and_resource_growth_are_bounded() -> None:
    """预热峰值不构成基线，首尾中位数能发现持续增长。"""
    history = BoundedHistory(2)
    for number in range(10):
        history.append(number)
    assert list(history) == [8, 9] and history.total_count == 10
    gate = ResourceGate(root_pids=(), warmup_seconds=10, limits={"rss_bytes": 10})
    gate.observe(0, {"rss_bytes": 10000})
    for number in range(10):
        gate.observe(10 + number, {"rss_bytes": 100 + number * 10})
    assert gate.summary()["growth"]["rss_bytes"] == 50
    assert gate.summary()["status"] == "failed"
    assert len(gate.first) == 5 and len(gate.last) == 5


def test_resource_gate_rejects_short_window() -> None:
    """不足 10 个样本不能把重叠窗口当作稳定证据。"""
    gate = ResourceGate(root_pids=(), warmup_seconds=0, limits={"rss_bytes": 0})
    gate.observe(0, {"rss_bytes": 1})
    assert gate.summary()["status"] == "failed"


@pytest.mark.parametrize("limits", [{"rss_bytes": float("nan")}, {"rss_bytes": -1}, {"rss_byte": 10}])
def test_invalid_resource_limits_are_rejected(limits):
    """拼错字段或非有限上限不能使比较静默失效。"""
    with pytest.raises(ValueError):
        ResourceGate(root_pids=(), warmup_seconds=0, limits=limits)


def test_missing_resource_field_never_counts_as_zero():
    """缺失字段必须记为采样错误，不能以零增长通过。"""
    gate = ResourceGate(root_pids=(), warmup_seconds=0, limits={"handles": 10})
    for index in range(10):
        gate.observe(index, {"rss_bytes": 1})
    assert gate.summary()["status"] == "failed"
    assert gate.sample_count == 0


def test_cpu_observations_use_elapsed_time_and_process_identity():
    """CPU 数据只用于观测，复用 PID 后的新进程不能产生假峰值。"""
    gate = ResourceGate(root_pids=(), warmup_seconds=0, limits={})
    assert gate._observe_cpu(0, {(1, 10.): 2.}) is None
    assert gate._observe_cpu(.5, {(1, 10.): 2.5}) == 100.
    assert gate._observe_cpu(1., {(1, 11.): 100.}) == 0.
    assert gate.summary()["cpu"]["peak_percent_one_core"] == 100.


def test_early_samples_cannot_cover_later_missing_hour() -> None:
    """早期十个样本不能把后续缺失的一小时判为稳定。"""
    gate = ResourceGate(root_pids=(), warmup_seconds=0, limits={"rss_bytes": 10}, sample_interval_seconds=10)
    for second in range(0, 100, 10):
        gate.observe(second, {"rss_bytes": 1})
    gate.complete_measurement(duration=3600, minimum_seconds=3600)
    assert gate.summary()["status"] == "failed"
    assert gate.summary()["maximum_gap_seconds"] == 3510


def test_complete_measured_window_passes() -> None:
    """时长、覆盖和趋势同时满足才允许通过。"""
    gate = ResourceGate(root_pids=(), warmup_seconds=0, limits={"rss_bytes": 10}, sample_interval_seconds=10)
    for second in range(0, 120, 10):
        gate.observe(second, {"rss_bytes": 1})
    gate.complete_measurement(duration=120, minimum_seconds=120)
    assert gate.summary()["status"] == "passed"


@pytest.mark.parametrize("closed", [True, False])
def test_failed_workload_finalization_requires_real_end_marker(tmp_path, monkeypatch, closed):
    """非零退出仍保留已闭合区间；硬退出没有结束标记时继续拒绝资源认证。"""
    from tests.integration import acceptance_contract

    timestamps = iter([100., 220., 221.])
    monkeypatch.setattr(acceptance_contract.time, "monotonic", lambda: next(timestamps))
    path = tmp_path / "phases.json"
    phases = acceptance_contract.AcceptancePhases(path, minimum_measure_seconds=120)
    phases.enter("measure")
    if closed:
        phases.enter("drain")
        phases.enter("failed")
    gate = ResourceGate(root_pids=(), warmup_seconds=0, limits={"rss_bytes": 10}, sample_interval_seconds=10)
    for second in range(0, 120, 10):
        gate.observe(second, {"rss_bytes": 1})
    gate.complete_from_phases(path)
    summary = gate.summary()
    assert summary["measurement_duration"] == (120 if closed else None)
    assert summary["status"] == ("passed" if closed else "failed")
    result = acceptance_contract.acceptance_result(
        {"performance": "failed", "resource": summary["status"]}, ("performance", "resource"))
    assert not result["passed"]


def test_cleanup_cannot_hide_earlier_resource_growth() -> None:
    """负载结束后的资源下降不能覆盖运行中已经超限的完整窗口。"""
    gate = ResourceGate(root_pids=(), warmup_seconds=0, limits={"rss_bytes": 10})
    for index, value in enumerate([100] * 5 + [200] * 5 + [1] * 5):
        gate.observe(index, {"rss_bytes": value})
    result = gate.summary()
    assert result["growth"]["rss_bytes"] == -99
    assert result["maximum_window_growth"]["rss_bytes"] == 100
    assert result["status"] == "failed"


def test_child_exit_discards_sample_but_root_exit_fails(monkeypatch) -> None:
    """受控子进程重启不能制造零内存样本；根进程死亡仍使门禁失败。"""
    def exited():
        """模拟枚举后进程退出。"""
        raise psutil.NoSuchProcess(2)

    child = SimpleNamespace(pid=2, oneshot=nullcontext, memory_info=exited)
    root = SimpleNamespace(pid=1, create_time=lambda: 10, is_running=lambda: True,
                           children=lambda **_: [child], oneshot=nullcontext,
                           memory_info=lambda: SimpleNamespace(rss=100, private=100),
                           num_threads=lambda: 1, num_handles=lambda: 1)
    monkeypatch.setattr(psutil, "Process", lambda _: root)
    gate = ResourceGate(root_pids=(1,), warmup_seconds=0, limits={"rss_bytes": 10})
    sample = gate.sample(0)
    assert sample["discarded"] == "child-exited-during-sampling"
    assert gate.sample_count == 0 and gate.discarded_count == 1 and gate.error_count == 0
    root.memory_info = exited
    assert "error" in gate.sample(1)
    assert gate.error_count == 1 and gate.summary()["status"] == "failed"


def test_optional_process_records_match_deduplicated_totals(monkeypatch):
    """角色观测直接复用同次采样，不重复累计嵌套根或改变门禁。"""
    monkeypatch.setattr("tests.integration.runtime_resource_gate.read_process_birth_identity",
                        lambda pid: f"test:{pid}")
    def process(pid):
        return SimpleNamespace(pid=pid, create_time=lambda: float(pid), is_running=lambda: True,
            ppid=lambda: pid - 1, children=lambda **_: [], oneshot=nullcontext,
            memory_info=lambda: SimpleNamespace(rss=pid * 100, private=pid * 50),
            num_threads=lambda: pid, num_handles=lambda: pid * 2)
    root, child = process(1), process(2)
    root.children = lambda **_: [child]
    monkeypatch.setattr(psutil, "Process", lambda pid: {1: root, 2: child}[pid])
    gate = ResourceGate(root_pids=(1, 2), warmup_seconds=0, limits={}, include_processes=True)
    sample = gate.sample(0)
    assert sample["process_count"] == 2
    for key in ("rss_bytes", "private_bytes", "threads", "handles"):
        assert sample[key] == sum(item[key] for item in sample["processes"])
    assert {(p["pid"], p["create_time"]) for p in sample["processes"]} == {(1, 1.), (2, 2.)}
    assert {p["birth_identity"] for p in sample["processes"]} == {"test:1", "test:2"}
    assert gate.summary()["status"] == "observed"
    assert "processes" not in ResourceGate(root_pids=(1,), warmup_seconds=0, limits={}).sample(0)


def test_stopping_executor_signals_before_join() -> None:
    """主线程失败后，等待 stop 的子线程必须先被唤醒再 join。"""
    stop = Event()
    with pytest.raises(RuntimeError):
        with _stopping_executor(stop, max_workers=1, thread_name_prefix="test") as executor:
            finished = executor.submit(stop.wait, 2)
            raise RuntimeError("cancelled")
    assert finished.result() is True


@pytest.mark.parametrize("phase", ["root-identity", "enumerate-children", "read-process"])
@pytest.mark.parametrize("exception", [psutil.NoSuchProcess, psutil.AccessDenied])
def test_sampler_retains_failure_phase_and_identity(monkeypatch, phase, exception):
    """同一个 PID 字符串必须能区分异常类别和采样阶段，不能吞掉失败。"""
    def fail():
        raise exception(17)

    root = SimpleNamespace(pid=1, create_time=lambda: 10, is_running=lambda: True,
                           children=lambda **_: [], oneshot=nullcontext,
                           status=lambda: psutil.STATUS_RUNNING,
                           memory_info=lambda: SimpleNamespace(rss=100, private=100),
                           num_threads=lambda: 1, num_handles=lambda: 1)
    monkeypatch.setattr(psutil, "Process", lambda _: root)
    gate = ResourceGate(root_pids=(1,), warmup_seconds=0, limits={"rss_bytes": 10})
    if phase == "root-identity":
        root.is_running = fail
    elif phase == "enumerate-children":
        root.children = lambda **_: fail()
    else:
        root.memory_info = fail
    for index in range(25):
        sample = gate.sample(index)
    detail = sample["error_detail"]
    assert detail["phase"] == phase
    assert detail["exception_type"] == exception.__name__
    assert detail["exception_pid"] == 17 and detail["root_identities"] == {1: 10}
    assert detail["root_pid"] == detail["target_pid"] == 1
    assert len(gate.error_details) == 20 and gate.error_count == 25
    assert gate.sample_count == 0 and gate.summary()["status"] == "failed"


def test_latency_gate_remembers_errors_outside_recent_window() -> None:
    """超过采样窗口后，全程超时统计仍保留早期慢请求。"""
    lane = LaneMetrics("test", latency_limit_ms=10)
    lane.latency_ms = BoundedHistory(2)
    for value in (100, 1, 1, 1):
        lane.begin()
        lane.finish(latency_ms=value, error=None)
    snapshot = lane.snapshot()
    assert snapshot["latency_ms"]["p99"] == 1
    assert snapshot["over_latency_limit_count"] == 1


@pytest.mark.parametrize("status,reused,root_denied,field,discard", [
    (psutil.STATUS_ZOMBIE, False, False, "num_fds", True),
    (psutil.STATUS_RUNNING, False, False, "num_fds", False),
    (psutil.STATUS_ZOMBIE, True, False, "num_fds", False),
    (psutil.STATUS_ZOMBIE, False, True, "num_fds", False),
    (psutil.STATUS_ZOMBIE, False, False, "memory_info", False),
])
def test_fd_access_denied_requires_confirmed_exited_child(monkeypatch, status, reused, root_denied, field, discard):
    """真实退出 fd 竞态可丢样；活进程权限、根退出、PID 复用不降级通过。"""
    def denied():
        raise psutil.AccessDenied(1 if root_denied else 2)

    def process(pid, created):
        return SimpleNamespace(pid=pid, create_time=lambda: created, is_running=lambda: True,
                               status=lambda: status, children=lambda **_: [], oneshot=nullcontext,
                               memory_info=lambda: SimpleNamespace(rss=100, private=100),
                               num_threads=lambda: 1, num_fds=lambda: 1)

    root, child = process(1, 10), process(2, 20)
    current = process(2, 21 if reused else 20)
    root.children = lambda **_: [child]
    setattr(root if root_denied else child, field, denied)
    monkeypatch.setattr(psutil, "Process", lambda pid: root if pid == 1 else current)
    gate = ResourceGate(root_pids=(1,), warmup_seconds=0, limits={"rss_bytes": 10})
    sample = gate.sample(0)
    assert ("discarded" in sample) is discard
    assert gate.sample_count == 0
    assert gate.discarded_count == int(discard)
    assert gate.error_count == int(not discard)
    assert gate.summary()["status"] == "failed"  # 没有完整样本，不能冒充通过。
    if discard:
        assert gate.discarded_details[-1]["status"] == psutil.STATUS_ZOMBIE
