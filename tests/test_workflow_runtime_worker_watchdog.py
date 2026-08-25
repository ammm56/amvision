"""Workflow Runtime worker 父进程失联回收测试。"""

from __future__ import annotations

from threading import Event, Thread

from backend.service.application.workflows.worker.process import (
    _run_supervisor_watchdog,
)


class _DeadSupervisor:
    """模拟已异常退出的 backend-service 父进程。"""

    def is_alive(self) -> bool:
        """返回父进程已退出。"""

        return False


def test_worker_watchdog_cancels_and_force_exits_after_parent_loss() -> None:
    """父进程失联必须先取消 Run，并在 grace 后结束孤儿 worker。"""

    stop_event = Event()
    supervisor_lost_event = Event()
    cancellation_event = Event()
    exit_codes: list[int] = []

    _run_supervisor_watchdog(
        supervisor_process=_DeadSupervisor(),
        stop_event=stop_event,
        supervisor_lost_event=supervisor_lost_event,
        run_cancellation_event=cancellation_event,
        force_exit=exit_codes.append,
        poll_seconds=0.001,
        force_exit_grace_seconds=0.001,
    )

    assert supervisor_lost_event.is_set()
    assert cancellation_event.is_set()
    assert exit_codes == [0]


def test_worker_watchdog_does_not_force_exit_after_main_cleanup_starts() -> None:
    """主线程在 grace 内进入 finally 时不得再次强制退出。"""

    stop_event = Event()
    supervisor_lost_event = Event()
    cancellation_event = Event()
    exit_codes: list[int] = []

    def finish_cleanup() -> None:
        assert supervisor_lost_event.wait(timeout=1.0)
        stop_event.set()

    cleanup_thread = Thread(target=finish_cleanup)
    cleanup_thread.start()

    _run_supervisor_watchdog(
        supervisor_process=_DeadSupervisor(),
        stop_event=stop_event,
        supervisor_lost_event=supervisor_lost_event,
        run_cancellation_event=cancellation_event,
        force_exit=exit_codes.append,
        poll_seconds=0.001,
        force_exit_grace_seconds=1.0,
    )
    cleanup_thread.join(timeout=1.0)

    assert supervisor_lost_event.is_set()
    assert cancellation_event.is_set()
    assert stop_event.is_set()
    assert exit_codes == []
