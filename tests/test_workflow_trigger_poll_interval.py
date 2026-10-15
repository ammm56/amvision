"""活跃数据交换可以缩短等待，但空闲限速与阻塞等待必须保留。"""
from threading import Event, Lock
from types import SimpleNamespace
import pytest
from backend.service.application.workflows.trigger_sources import local_shared_mailbox_supervisor as module


@pytest.mark.parametrize(("pending", "interval", "expected"), [(None, .001, .001), (False, .001, .00025), (False, .0001, .0001), (True, .001, .001)])
def test_poller_keeps_blocking_and_idle_interval(monkeypatch, pending, interval, expected):
    """一轮无进展后只调用一次 sleep，不引入忙轮询，也不延长显式更短的间隔。"""
    stop = Event()
    calls = []
    def sleep(seconds):
        calls.append(seconds)
        stop.set()
    monkeypatch.setattr(module, "sleep", sleep)
    state = SimpleNamespace(_stop_event=stop, process_once=lambda: False, _pending_lock=Lock(),
                            _idle_poll_sleep_count=0, _pending={} if pending is None else {1: SimpleNamespace(task_active=pending)},
                            poll_interval_seconds=interval)
    module.WorkflowTriggerMailboxSupervisor._run(state)
    assert calls == [expected]
    assert state._idle_poll_sleep_count == 1
