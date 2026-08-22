"""持久任务 worker 的 TaskAttempt 幂等领取测试。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import replace
from multiprocessing import get_context
from pathlib import Path

from backend.service.application.errors import PersistenceOperationError
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    SqlAlchemyTaskService,
)
from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.queue.local_file import (
    LocalFileQueueBackend,
    LocalFileQueueSettings,
)
from backend.workers.task_execution_claim import TaskAttemptClaimingQueueBackend


def test_task_attempt_claim_is_atomic_across_database_sessions(tmp_path: Path) -> None:
    """两个 worker 同时领取同一轮次时只能有一个取得执行权。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-race",
            project_id="project-1",
            task_kind="training",
        )
    )

    def claim(worker_id: str) -> str:
        return SqlAlchemyTaskService(session_factory).claim_task_attempt(
            task_id="task-race",
            attempt_no=1,
            worker_id=worker_id,
            queue_name="trainings",
            queue_message_id=f"message-{worker_id}",
            queue_attempt_count=1,
            queue_leased_at="2026-08-22T00:00:00+00:00",
        ).outcome

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(claim, ("worker-a", "worker-b")))

    assert sorted(outcomes) == ["acquired", "duplicate_running"]
    attempts = task_service.list_task_attempts("task-race")
    assert len(attempts) == 1
    assert attempts[0].attempt_no == 1
    assert attempts[0].state == "running"


def test_task_attempt_claim_is_atomic_across_worker_processes(tmp_path: Path) -> None:
    """两个独立 worker 进程竞争同一轮次时也只能有一个取得执行权。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-process-race",
            project_id="project-1",
            task_kind="validation",
        )
    )
    database_url = str(session_factory.settings.url)
    session_factory.engine.dispose()

    with ProcessPoolExecutor(
        max_workers=2,
        mp_context=get_context("spawn"),
    ) as executor:
        outcomes = tuple(
            executor.map(
                _claim_attempt_in_worker_process,
                ((database_url, "worker-a"), (database_url, "worker-b")),
            )
        )

    assert sorted(outcomes) == ["acquired", "duplicate_running"]
    attempts = task_service.list_task_attempts("task-process-race")
    assert len(attempts) == 1
    assert attempts[0].attempt_no == 1


def test_queue_wrapper_suppresses_running_and_finished_duplicate_messages(
    tmp_path: Path,
) -> None:
    """同一 task_id/attempt_no 的重复文件消息不会再次进入业务 worker。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-duplicate",
            project_id="project-1",
            task_kind="conversion",
        )
    )
    raw_queue = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    )
    queue = TaskAttemptClaimingQueueBackend(
        queue_backend=raw_queue,
        session_factory=session_factory,
    )
    for message_id in ("message-1", "message-2"):
        raw_queue.enqueue(
            queue_name="conversions",
            message_id=message_id,
            payload={"task_id": "task-duplicate", "attempt_no": 1},
        )

    first = queue.claim_next(queue_name="conversions", worker_id="worker-a")
    assert first is not None
    claimed_attempt = task_service.list_task_attempts("task-duplicate")[0]
    service_attempt = task_service.start_task_attempt(
        task_id="task-duplicate",
        attempt_no=1,
        process_id=1234,
        metadata={"operation_kind": "conversion"},
    )
    assert service_attempt.heartbeat_at == claimed_attempt.heartbeat_at
    assert service_attempt.worker_id == claimed_attempt.worker_id
    assert service_attempt.process_id is None
    assert service_attempt.metadata == claimed_attempt.metadata
    # 第二条消息被数据库唯一 claim 抑制；装饰器继续扫描后返回空。
    assert queue.claim_next(queue_name="conversions", worker_id="worker-b") is None
    suppressed_running = raw_queue.get_task(
        queue_name="conversions",
        task_id="message-2",
    )
    assert suppressed_running is not None
    assert suppressed_running.status == "completed"
    assert suppressed_running.metadata["status"] == "duplicate_suppressed"
    assert suppressed_running.metadata["task_execution_claim"] == "duplicate_running"

    queue.complete(first, metadata={"task_id": "task-duplicate", "status": "succeeded"})
    raw_queue.enqueue(
        queue_name="conversions",
        message_id="message-3",
        payload={"task_id": "task-duplicate", "attempt_no": 1},
    )
    assert queue.claim_next(queue_name="conversions", worker_id="worker-c") is None
    suppressed_finished = raw_queue.get_task(
        queue_name="conversions",
        task_id="message-3",
    )
    assert suppressed_finished is not None
    assert suppressed_finished.metadata["task_execution_claim"] == "duplicate_finished"
    attempts = task_service.list_task_attempts("task-duplicate")
    assert len(attempts) == 1
    assert attempts[0].state == "succeeded"


def test_queue_wrapper_uses_explicit_next_attempt_for_retry(tmp_path: Path) -> None:
    """新一轮重试必须使用下一个 attempt_no，旧轮次始终被去重。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-retry",
            project_id="project-1",
            task_kind="training",
        )
    )
    raw_queue = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-retry"))
    )
    queue = TaskAttemptClaimingQueueBackend(
        queue_backend=raw_queue,
        session_factory=session_factory,
    )
    raw_queue.enqueue(
        queue_name="trainings",
        message_id="message-attempt-1",
        payload={"task_id": "task-retry", "attempt_no": 1},
    )
    first = queue.claim_next(queue_name="trainings", worker_id="worker-a")
    assert first is not None
    queue.fail(first, error_message="训练进程退出")

    task_service.append_task_event(
        AppendTaskEventRequest(
            task_id="task-retry",
            event_type="status",
            message="retry queued",
            payload={"state": "queued", "finished_at": None},
        )
    )
    assert task_service.get_next_task_attempt_no("task-retry") == 2
    raw_queue.enqueue(
        queue_name="trainings",
        message_id="message-attempt-2",
        payload={"task_id": "task-retry", "attempt_no": 2},
    )
    second = queue.claim_next(queue_name="trainings", worker_id="worker-b")
    assert second is not None
    queue.complete(second, metadata={"status": "succeeded"})

    attempts = task_service.list_task_attempts("task-retry")
    assert [(item.attempt_no, item.state) for item in attempts] == [
        (1, "failed"),
        (2, "succeeded"),
    ]
    obsolete = task_service.claim_task_attempt(
        task_id="task-retry",
        attempt_no=1,
        worker_id="worker-stale",
        queue_name="trainings",
        queue_message_id="message-attempt-1",
        queue_attempt_count=2,
        queue_leased_at="2026-08-22T01:00:00+00:00",
        lease_recovery_count=1,
    )
    assert obsolete.outcome == "obsolete_attempt"


def test_lease_refresh_keeps_task_attempt_binding(tmp_path: Path) -> None:
    """训练 heartbeat 更新 leased_at 后仍能结束原 TaskAttempt。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-heartbeat",
            project_id="project-1",
            task_kind="training",
        )
    )
    raw_queue = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-heartbeat"))
    )
    queue = TaskAttemptClaimingQueueBackend(
        queue_backend=raw_queue,
        session_factory=session_factory,
    )
    raw_queue.enqueue(
        queue_name="trainings",
        message_id="message-heartbeat",
        payload={"task_id": "task-heartbeat", "attempt_no": 1},
    )
    claimed = queue.claim_next(queue_name="trainings", worker_id="worker-a")
    assert claimed is not None
    refreshed = queue.refresh_lease(claimed, metadata={"heartbeat": 1})
    queue.complete(refreshed, metadata={"status": "succeeded"})

    attempts = task_service.list_task_attempts("task-heartbeat")
    assert attempts[0].state == "succeeded"
    assert attempts[0].metadata["queue_attempt_count"] == 1


def test_recovered_same_message_reclaims_attempt_and_fences_stale_owner(
    tmp_path: Path,
) -> None:
    """同一消息的 crash recovery 接管原 attempt，旧 lease 不能提交终态。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-recovered",
            project_id="project-1",
            task_kind="training",
        )
    )
    raw_queue = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-recovered"))
    )
    first_queue = TaskAttemptClaimingQueueBackend(
        queue_backend=raw_queue,
        session_factory=session_factory,
    )
    raw_queue.enqueue(
        queue_name="trainings",
        message_id="message-recovered",
        payload={"task_id": "task-recovered", "attempt_no": 1},
    )
    stale_message = first_queue.claim_next(
        queue_name="trainings",
        worker_id="worker-a",
    )
    assert stale_message is not None
    stale_heartbeat_at = task_service.list_task_attempts("task-recovered")[
        0
    ].heartbeat_at

    leased_path = (
        raw_queue.root_dir / "trainings" / "leased" / "message-recovered.json"
    )
    raw_queue._overwrite_task_file(  # noqa: SLF001 - 构造 crash 后超时 lease
        leased_path,
        replace(stale_message, leased_at="2000-01-01T00:00:00+00:00"),
    )
    assert raw_queue.recover_expired_leases(
        queue_name="trainings",
        lease_timeout_seconds=0.1,
    ) == 1

    recovered_queue = TaskAttemptClaimingQueueBackend(
        queue_backend=raw_queue,
        session_factory=session_factory,
    )
    recovered_message = recovered_queue.claim_next(
        queue_name="trainings",
        worker_id="worker-a",
    )
    assert recovered_message is not None
    attempts = task_service.list_task_attempts("task-recovered")
    assert len(attempts) == 1
    assert attempts[0].worker_id == "worker-a"
    assert attempts[0].heartbeat_at != stale_heartbeat_at
    assert attempts[0].metadata["queue_attempt_count"] == 2
    assert attempts[0].metadata["lease_recovery_count"] == 1

    try:
        first_queue.complete(stale_message, metadata={"status": "succeeded"})
    except (PersistenceOperationError, RuntimeError):
        pass
    else:
        raise AssertionError("旧 lease 不应能够提交队列终态")
    assert task_service.list_task_attempts("task-recovered")[0].state == "running"

    recovered_queue.complete(
        recovered_message,
        metadata={"status": "succeeded"},
    )
    assert task_service.list_task_attempts("task-recovered")[0].state == "succeeded"


def test_recovered_message_enters_service_when_attempt_finished_before_task(
    tmp_path: Path,
) -> None:
    """Attempt 已终态但 Task 未最终发布时，恢复消息不能被普通判重吞掉。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-finalization-window",
            project_id="project-1",
            task_kind="conversion",
        )
    )
    raw_queue = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-finalization"))
    )
    first_queue = TaskAttemptClaimingQueueBackend(
        queue_backend=raw_queue,
        session_factory=session_factory,
    )
    raw_queue.enqueue(
        queue_name="conversions",
        message_id="message-finalization",
        payload={"task_id": "task-finalization-window", "attempt_no": 1},
    )
    stale_message = first_queue.claim_next(
        queue_name="conversions",
        worker_id="worker-a",
    )
    assert stale_message is not None
    attempt = task_service.list_task_attempts("task-finalization-window")[0]
    attempt = task_service.finish_task_attempt(
        attempt_id=attempt.attempt_id,
        state="succeeded",
        result={"publication": "written"},
        expected_worker_id="worker-a",
    )
    assert task_service.get_task("task-finalization-window").task.state == "queued"

    leased_path = (
        raw_queue.root_dir / "conversions" / "leased" / "message-finalization.json"
    )
    raw_queue._overwrite_task_file(  # noqa: SLF001 - 构造最终发布前 crash
        leased_path,
        replace(stale_message, leased_at="2000-01-01T00:00:00+00:00"),
    )
    assert raw_queue.recover_expired_leases(
        queue_name="conversions",
        lease_timeout_seconds=0.1,
    ) == 1

    recovered_queue = TaskAttemptClaimingQueueBackend(
        queue_backend=raw_queue,
        session_factory=session_factory,
    )
    recovered_message = recovered_queue.claim_next(
        queue_name="conversions",
        worker_id="worker-b",
    )
    assert recovered_message is not None
    assert task_service.list_task_attempts("task-finalization-window") == (attempt,)

    task_service.append_task_event(
        AppendTaskEventRequest(
            task_id="task-finalization-window",
            event_type="result",
            message="conversion finalization recovered",
            payload={"state": "succeeded", "result": {"publication": "written"}},
        )
    )
    recovered_queue.complete(
        recovered_message,
        metadata={"status": "succeeded"},
    )
    assert task_service.get_task("task-finalization-window").task.state == "succeeded"
    assert task_service.list_task_attempts("task-finalization-window")[0].state == (
        "succeeded"
    )


def test_recovered_message_finalizes_attempt_when_task_already_finished(
    tmp_path: Path,
) -> None:
    """Task 已发布终态但 Attempt 未结束时，恢复消息只补终态而不重放 service。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-attempt-finalization",
            project_id="project-1",
            task_kind="evaluation",
        )
    )
    raw_queue = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-attempt-finalization"))
    )
    first_queue = TaskAttemptClaimingQueueBackend(
        queue_backend=raw_queue,
        session_factory=session_factory,
    )
    raw_queue.enqueue(
        queue_name="evaluations",
        message_id="message-attempt-finalization",
        payload={"task_id": "task-attempt-finalization", "attempt_no": 1},
    )
    stale_message = first_queue.claim_next(
        queue_name="evaluations",
        worker_id="worker-a",
    )
    assert stale_message is not None
    task_service.append_task_event(
        AppendTaskEventRequest(
            task_id="task-attempt-finalization",
            event_type="result",
            payload={"state": "succeeded", "result": {"metric": 0.99}},
        )
    )
    assert task_service.list_task_attempts("task-attempt-finalization")[0].state == (
        "running"
    )

    leased_path = (
        raw_queue.root_dir
        / "evaluations"
        / "leased"
        / "message-attempt-finalization.json"
    )
    raw_queue._overwrite_task_file(  # noqa: SLF001 - 构造 Task 发布后的 crash
        leased_path,
        replace(stale_message, leased_at="2000-01-01T00:00:00+00:00"),
    )
    assert raw_queue.recover_expired_leases(
        queue_name="evaluations",
        lease_timeout_seconds=0.1,
    ) == 1

    recovered_queue = TaskAttemptClaimingQueueBackend(
        queue_backend=raw_queue,
        session_factory=session_factory,
    )
    # task_finished 在 wrapper 内直接 ACK，业务 worker 不会拿到该消息。
    assert (
        recovered_queue.claim_next(
            queue_name="evaluations",
            worker_id="worker-b",
        )
        is None
    )
    attempt = task_service.list_task_attempts("task-attempt-finalization")[0]
    assert attempt.state == "succeeded"
    assert attempt.result == {"task_result": {"metric": 0.99}}
    assert attempt.metadata["finalized_from_terminal_task"] is True
    completed = raw_queue.get_task(
        queue_name="evaluations",
        task_id="message-attempt-finalization",
    )
    assert completed is not None
    assert completed.status == "completed"
    assert completed.metadata["task_execution_claim"] == "task_finished"


def _create_session_factory(tmp_path: Path) -> SessionFactory:
    """创建支持跨 Session 并发的文件 SQLite 数据库。"""

    session_factory = SessionFactory(
        DatabaseSettings(url=f"sqlite:///{(tmp_path / 'claims.db').as_posix()}")
    )
    initialize_database_schema(session_factory)
    return session_factory


def _claim_attempt_in_worker_process(arguments: tuple[str, str]) -> str:
    """在 spawn worker 中创建独立 Engine/Session 并竞争同一 attempt。"""

    database_url, worker_id = arguments
    session_factory = SessionFactory(DatabaseSettings(url=database_url))
    try:
        return SqlAlchemyTaskService(session_factory).claim_task_attempt(
            task_id="task-process-race",
            attempt_no=1,
            worker_id=worker_id,
            queue_name="validations",
            queue_message_id=f"message-{worker_id}",
            queue_attempt_count=1,
            queue_leased_at="2026-08-22T00:00:00+00:00",
        ).outcome
    finally:
        session_factory.engine.dispose()
