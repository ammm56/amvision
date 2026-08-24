"""持久任务 worker 的 TaskAttempt 幂等领取测试。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import replace
from multiprocessing import get_context
from pathlib import Path

import pytest

from backend.service.application.errors import InvalidRequestError, PersistenceOperationError
from backend.service.application.tasks.task_service import (
    AppendTaskEventRequest,
    CreateTaskRequest,
    RecordTaskProgressRequest,
    SqlAlchemyTaskService,
    TaskExecutionFence,
    TaskStateCommandRequest,
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
        return SqlAlchemyTaskService(session_factory).claim_task_execution(
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


def test_running_progress_requires_exact_attempt_lease_fence(tmp_path: Path) -> None:
    """进度写入只能使用当前 Attempt 的准确 queue lease 身份。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-progress-fence",
            project_id="project-1",
            task_kind="training",
        )
    )
    claim = task_service.claim_task_execution(
        task_id="task-progress-fence",
        attempt_no=1,
        worker_id="worker-a",
        queue_name="trainings",
        queue_message_id="message-progress",
        queue_attempt_count=2,
        queue_leased_at="2026-08-24T00:00:00+00:00",
        lease_recovery_count=1,
    )
    assert claim.attempt is not None
    fence = TaskExecutionFence(
        attempt_id=claim.attempt.attempt_id,
        worker_id="worker-a",
        heartbeat_at="2026-08-24T00:00:00+00:00",
        queue_message_id="message-progress",
        queue_attempt_count=2,
    )

    detail = task_service.record_task_progress(
        RecordTaskProgressRequest(
            task_id="task-progress-fence",
            fence=fence,
            progress={"stage": "training", "percent": 12.5},
        )
    )
    assert detail.task.state == "running"
    assert detail.task.progress == {"stage": "training", "percent": 12.5}
    assert detail.events[0].attempt_id == claim.attempt.attempt_id

    stale_fence = replace(fence, queue_attempt_count=1)
    with pytest.raises(InvalidRequestError, match="lease 所有权"):
        task_service.record_task_progress(
            RecordTaskProgressRequest(
                task_id="task-progress-fence",
                fence=stale_fence,
                progress={"percent": 99.0},
            )
        )
    assert task_service.get_task("task-progress-fence").task.progress["percent"] == 12.5


def test_attempt_event_is_pure_append_and_rejects_state_payload(tmp_path: Path) -> None:
    """Attempt 运行事件不能通过 payload 偷渡 Task 状态变更。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-attempt-event",
            project_id="project-1",
            task_kind="conversion",
        )
    )
    claim = task_service.claim_task_execution(
        task_id="task-attempt-event",
        attempt_no=1,
        worker_id="worker-a",
        queue_name="conversions",
        queue_message_id="message-event",
        queue_attempt_count=1,
        queue_leased_at="2026-08-24T00:00:00+00:00",
    )
    assert claim.attempt is not None
    fence = TaskExecutionFence(
        attempt_id=claim.attempt.attempt_id,
        worker_id="worker-a",
        heartbeat_at="2026-08-24T00:00:00+00:00",
        queue_message_id="message-event",
        queue_attempt_count=1,
    )
    detail = task_service.append_task_attempt_event(
        AppendTaskEventRequest(
            task_id="task-attempt-event",
            attempt_id=claim.attempt.attempt_id,
            event_type="log",
            message="conversion output prepared",
            payload={"output_count": 2},
        ),
        fence=fence,
    )
    assert detail.task.state == "running"
    assert detail.task.result == {}

    with pytest.raises(InvalidRequestError, match="不能携带 state"):
        task_service.append_task_attempt_event(
            AppendTaskEventRequest(
                task_id="task-attempt-event",
                attempt_id=claim.attempt.attempt_id,
                event_type="status",
                payload={"state": "succeeded"},
            ),
            fence=fence,
        )


def test_fenced_terminal_state_command_finalizes_task_and_attempt_atomically(
    tmp_path: Path,
) -> None:
    """带 fence 的业务终态命令必须由统一 finalizer 同时结束 Task/Attempt。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-fenced-finalizer",
            project_id="project-1",
            task_kind="inference",
        )
    )
    claim = task_service.claim_task_execution(
        task_id="task-fenced-finalizer",
        attempt_no=1,
        worker_id="worker-a",
        queue_name="inferences",
        queue_message_id="message-finalizer",
        queue_attempt_count=1,
        queue_leased_at="2026-08-24T00:00:00+00:00",
    )
    assert claim.attempt is not None
    stable_fence = TaskExecutionFence(
        attempt_id=claim.attempt.attempt_id,
        worker_id="worker-a",
        heartbeat_at=None,
        queue_message_id="message-finalizer",
        queue_attempt_count=1,
    )

    initialized = task_service.execute_task_state_event_command(
        AppendTaskEventRequest(
            task_id="task-fenced-finalizer",
            event_type="status",
            message="inference started",
            payload={
                "state": "running",
                "attempt_no": 2,
                "progress": {"stage": "inferencing", "percent": 5.0},
            },
        ),
        fence=stable_fence,
    )
    assert initialized.task.current_attempt_no == 1
    assert initialized.events[0].event_type == "progress"
    started_events = [
        event
        for event in task_service.get_task(
            "task-fenced-finalizer",
            include_events=True,
        ).events
        if event.event_type == "status" and event.payload.get("state") == "running"
    ]
    assert len(started_events) == 1

    detail = task_service.execute_task_state_event_command(
        AppendTaskEventRequest(
            task_id="task-fenced-finalizer",
            event_type="result",
            message="inference completed",
            payload={
                "state": "succeeded",
                "progress": {"stage": "completed", "percent": 100.0},
                "result": {"result_object_key": "tasks/result.json"},
            },
        ),
        fence=stable_fence,
    )

    assert detail.task.state == "succeeded"
    assert detail.task.progress["percent"] == 100.0
    assert detail.task.result["result_object_key"] == "tasks/result.json"
    attempt = task_service.list_task_attempts("task-fenced-finalizer")[0]
    assert attempt.state == "succeeded"
    assert attempt.heartbeat_at == "2026-08-24T00:00:00+00:00"
    assert len(detail.events) == 1
    assert detail.events[0].attempt_id == attempt.attempt_id

    repeated = task_service.finalize_task_execution_attempt(
        attempt_id=attempt.attempt_id,
        attempt_outcome="succeeded",
        result={"queue_result": {"status": "succeeded"}},
        error_message=None,
        metadata=None,
        expected_worker_id="worker-a",
        expected_heartbeat_at="2026-08-24T00:00:00+00:00",
        expected_queue_message_id="message-finalizer",
        expected_queue_attempt_count=1,
    )
    assert repeated.task.result == {"result_object_key": "tasks/result.json"}
    assert repeated.event is None


def test_committed_task_event_survives_in_process_bus_failure(tmp_path: Path) -> None:
    """进程内通知失败不能回滚或伪装已经提交的 TaskEvent。"""

    class FailingEventBus:
        def publish(self, _event) -> None:
            raise RuntimeError("event bus unavailable")

    session_factory = _create_session_factory(tmp_path)
    session_factory.service_event_bus = FailingEventBus()
    task_service = SqlAlchemyTaskService(session_factory)

    task = task_service.create_task(
        CreateTaskRequest(
            task_id="task-event-bus-failure",
            project_id="project-1",
            task_kind="training",
        )
    )

    detail = task_service.get_task(task.task_id, include_events=True)
    assert detail.task.state == "queued"
    assert len(detail.events) == 1
    assert detail.events[0].message == "task created"


def test_late_metadata_patch_cannot_overwrite_cancelled_task(tmp_path: Path) -> None:
    """旧 Worker 的 metadata patch 不能越过 cancel 终态 CAS。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-metadata-cancel-race",
            project_id="project-1",
            task_kind="training",
            metadata={"training_control": {"pause_requested": False}},
        )
    )
    task_service.claim_task_execution(
        task_id="task-metadata-cancel-race",
        attempt_no=1,
        worker_id="worker-a",
        queue_name="trainings",
        queue_message_id="message-metadata",
        queue_attempt_count=1,
        queue_leased_at="2026-08-24T00:00:00+00:00",
    )
    running_task = task_service.get_task("task-metadata-cancel-race").task
    task_service.cancel_task("task-metadata-cancel-race")

    with pytest.raises(InvalidRequestError, match="metadata 未写入"):
        task_service.update_task_metadata(
            running_task.task_id,
            {"training_control": {"pause_requested": True}},
            expected_states=("running",),
            expected_current_attempt_no=running_task.current_attempt_no,
        )
    cancelled_task = task_service.get_task("task-metadata-cancel-race").task
    assert cancelled_task.state == "cancelled"
    assert cancelled_task.metadata["training_control"] == {
        "pause_requested": False
    }


def test_explicit_state_command_uses_state_and_attempt_cas(tmp_path: Path) -> None:
    """显式状态命令只在预期状态和 attempt_no 下生效。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-state-command",
            project_id="project-1",
            task_kind="dataset-export",
        )
    )
    detail = task_service.execute_task_state_command(
        TaskStateCommandRequest(
            task_id="task-state-command",
            target_state="running",
            expected_states=("queued",),
            expected_current_attempt_no=0,
            progress_patch={"stage": "exporting", "percent": 10},
            message="dataset export started",
        )
    )
    assert detail.task.state == "running"
    assert detail.task.progress["percent"] == 10

    with pytest.raises(InvalidRequestError, match="状态命令未生效"):
        task_service.execute_task_state_command(
            TaskStateCommandRequest(
                task_id="task-state-command",
                target_state="failed",
                expected_states=("running",),
                expected_current_attempt_no=1,
                error_message="stale attempt",
            )
        )
    assert task_service.get_task("task-state-command").task.state == "running"


def test_cancel_and_finalizer_race_has_one_authoritative_terminal_state(
    tmp_path: Path,
) -> None:
    """cancel 与 Worker finalizer 并发时 Task/Attempt 必须收敛到同一终态。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-cancel-finalize-race",
            project_id="project-1",
            task_kind="evaluation",
        )
    )
    claim = task_service.claim_task_execution(
        task_id="task-cancel-finalize-race",
        attempt_no=1,
        worker_id="worker-a",
        queue_name="evaluations",
        queue_message_id="message-race",
        queue_attempt_count=1,
        queue_leased_at="2026-08-24T00:00:00+00:00",
    )
    assert claim.attempt is not None

    def finalize() -> str:
        try:
            task_service.finalize_task_execution_attempt(
                attempt_id=claim.attempt.attempt_id,
                attempt_outcome="succeeded",
                result={"metric": 0.9},
                error_message=None,
                metadata=None,
                expected_worker_id="worker-a",
                expected_heartbeat_at="2026-08-24T00:00:00+00:00",
                expected_queue_message_id="message-race",
                expected_queue_attempt_count=1,
            )
            return "succeeded"
        except InvalidRequestError:
            return "rejected"

    def cancel() -> str:
        try:
            task_service.cancel_task("task-cancel-finalize-race")
            return "cancelled"
        except InvalidRequestError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda action: action(), (finalize, cancel)))

    task = task_service.get_task("task-cancel-finalize-race").task
    attempt = task_service.list_task_attempts("task-cancel-finalize-race")[0]
    assert outcomes.count("rejected") == 1
    assert task.state in {"succeeded", "cancelled"}
    assert attempt.state == task.state


def test_conversion_publication_reservation_is_fenced_and_blocks_cancel(
    tmp_path: Path,
) -> None:
    """验证 publication 只能由当前 Attempt 推进，取得后取消必须冲突。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="conversion-publication-fence",
            project_id="project-1",
            task_kind="yolox-conversion",
            task_spec={"target_formats": ["onnx"]},
        )
    )
    claim = task_service.claim_task_execution(
        task_id="conversion-publication-fence",
        attempt_no=1,
        worker_id="conversion-worker",
        queue_name="yolox-conversions",
        queue_message_id="conversion-message",
        queue_attempt_count=1,
        queue_leased_at="2026-08-24T00:00:00+00:00",
    )
    assert claim.attempt is not None
    fence = TaskExecutionFence(
        attempt_id=claim.attempt.attempt_id,
        worker_id="conversion-worker",
        heartbeat_at=claim.attempt.heartbeat_at,
        queue_message_id="conversion-message",
        queue_attempt_count=1,
    )

    reservation = task_service.begin_conversion_publication(
        task_id="conversion-publication-fence",
        fence=fence,
        publication_token="publication-token-1",
    )
    assert reservation.publication_state == "reserved"
    assert task_service.get_task("conversion-publication-fence").task.publication_state == (
        "reserved"
    )
    with pytest.raises(InvalidRequestError, match="不能取消"):
        task_service.cancel_task("conversion-publication-fence")
    with pytest.raises(InvalidRequestError, match="CAS 失败"):
        task_service.transition_conversion_publication(
            task_id="conversion-publication-fence",
            attempt_no=1,
            publication_token="stale-token",
            expected_state="reserved",
            target_state="published",
        )

    published = task_service.transition_conversion_publication(
        task_id="conversion-publication-fence",
        attempt_no=1,
        publication_token="publication-token-1",
        expected_state="reserved",
        target_state="published",
    )
    assert published.publication_state == "published"
    registered = task_service.transition_conversion_publication(
        task_id="conversion-publication-fence",
        attempt_no=1,
        publication_token="publication-token-1",
        expected_state="published",
        target_state="registered",
    )
    assert registered.publication_state == "registered"


def test_conversion_reservation_and_cancel_race_has_one_winner(tmp_path: Path) -> None:
    """验证 reservation 与取消竞争由同一 Task 行 CAS 决定唯一结果。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="conversion-publication-cancel-race",
            project_id="project-1",
            task_kind="rfdetr-conversion",
            task_spec={"target_formats": ["onnx"]},
        )
    )
    claim = task_service.claim_task_execution(
        task_id="conversion-publication-cancel-race",
        attempt_no=1,
        worker_id="conversion-worker",
        queue_name="rfdetr-conversions",
        queue_message_id="conversion-race-message",
        queue_attempt_count=1,
        queue_leased_at="2026-08-24T00:00:00+00:00",
    )
    assert claim.attempt is not None
    fence = TaskExecutionFence(
        attempt_id=claim.attempt.attempt_id,
        worker_id="conversion-worker",
        heartbeat_at=claim.attempt.heartbeat_at,
        queue_message_id="conversion-race-message",
        queue_attempt_count=1,
    )

    def reserve() -> str:
        try:
            task_service.begin_conversion_publication(
                task_id="conversion-publication-cancel-race",
                fence=fence,
                publication_token="race-token",
            )
            return "reserved"
        except InvalidRequestError:
            return "rejected"

    def cancel() -> str:
        try:
            task_service.cancel_task("conversion-publication-cancel-race")
            return "cancelled"
        except InvalidRequestError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda action: action(), (reserve, cancel)))

    assert outcomes.count("rejected") == 1
    task = task_service.get_task("conversion-publication-cancel-race").task
    if "reserved" in outcomes:
        assert task.state == "running"
        assert task.publication_state == "reserved"
    else:
        assert task.state == "cancelled"
        assert task.publication_state is None


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
    assert suppressed_finished.metadata["task_execution_claim"] == (
        "finalization_recovery"
    )
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

    task_service.execute_task_state_event_command(
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
    obsolete = task_service.claim_task_execution(
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


def test_queue_failure_preserves_timeout_terminal_state(tmp_path: Path) -> None:
    """Queue failed 记录不能把业务 timed_out 误写成 failed。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-timeout-finalizer",
            project_id="project-1",
            task_kind="evaluation",
        )
    )
    raw_queue = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-timeout"))
    )
    queue = TaskAttemptClaimingQueueBackend(
        queue_backend=raw_queue,
        session_factory=session_factory,
    )
    raw_queue.enqueue(
        queue_name="evaluations",
        message_id="message-timeout",
        payload={"task_id": "task-timeout-finalizer", "attempt_no": 1},
    )
    claimed = queue.claim_next(queue_name="evaluations", worker_id="worker-a")
    assert claimed is not None

    queue.fail(
        claimed,
        error_message="deadline exceeded",
        metadata={"status": "timed_out"},
    )

    task = task_service.get_task("task-timeout-finalizer").task
    attempt = task_service.list_task_attempts(task.task_id)[0]
    assert task.state == "timed_out"
    assert attempt.state == "timed_out"


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


def test_conversion_lease_recovery_never_resets_total_deadline(tmp_path: Path) -> None:
    """同一 Conversion Attempt 被新 lease 接管时必须沿用首次 deadline。"""

    session_factory = _create_session_factory(tmp_path)
    service = SqlAlchemyTaskService(session_factory)
    service.create_task(
        CreateTaskRequest(
            task_id="conversion-deadline-recovery",
            project_id="project-1",
            task_kind="yolox-conversion",
            task_spec={"target_formats": ["tensorrt-engine"]},
        )
    )
    first = service.claim_task_execution(
        task_id="conversion-deadline-recovery",
        attempt_no=1,
        worker_id="worker-a",
        queue_name="yolox-conversions",
        queue_message_id="conversion-message",
        queue_attempt_count=1,
        queue_leased_at="2026-08-24T00:00:00Z",
    )
    assert first.attempt is not None
    original_deadline = first.attempt.metadata["deadline_at"]

    recovered = service.claim_task_execution(
        task_id="conversion-deadline-recovery",
        attempt_no=1,
        worker_id="worker-b",
        queue_name="yolox-conversions",
        queue_message_id="conversion-message",
        queue_attempt_count=2,
        queue_leased_at="2026-08-24T01:30:00Z",
        lease_recovery_count=1,
    )

    assert recovered.outcome == "acquired"
    assert recovered.attempt is not None
    assert recovered.attempt.metadata["deadline_at"] == original_deadline
    assert recovered.attempt.metadata["timeout_seconds"] == 10800.0


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
    except (InvalidRequestError, PersistenceOperationError, RuntimeError):
        pass
    else:
        raise AssertionError("旧 lease 不应能够提交队列终态")
    assert task_service.list_task_attempts("task-recovered")[0].state == "running"

    recovered_queue.complete(
        recovered_message,
        metadata={"status": "succeeded"},
    )
    assert task_service.list_task_attempts("task-recovered")[0].state == "succeeded"


def test_recovered_message_only_acks_atomic_finalization_after_queue_ack_loss(
    tmp_path: Path,
) -> None:
    """Task/Attempt 已原子终结但 queue ACK 丢失时只补 ACK，不重放业务。"""

    session_factory = _create_session_factory(tmp_path)
    task_service = SqlAlchemyTaskService(session_factory)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-finalization-recovery",
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
        payload={"task_id": "task-finalization-recovery", "attempt_no": 1},
    )
    stale_message = first_queue.claim_next(
        queue_name="evaluations",
        worker_id="worker-a",
    )
    assert stale_message is not None
    attempt = task_service.list_task_attempts("task-finalization-recovery")[0]
    task_service.finalize_task_execution_attempt(
        attempt_id=attempt.attempt_id,
        attempt_outcome="succeeded",
        result={"metric": 0.99},
        error_message=None,
        metadata=None,
        expected_worker_id="worker-a",
        expected_heartbeat_at=str(attempt.heartbeat_at),
        expected_queue_message_id="message-attempt-finalization",
        expected_queue_attempt_count=1,
        exit_code=0,
    )
    assert task_service.get_task("task-finalization-recovery").task.state == "succeeded"

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
    attempt = task_service.list_task_attempts("task-finalization-recovery")[0]
    assert attempt.state == "succeeded"
    assert attempt.result == {"metric": 0.99}
    completed = raw_queue.get_task(
        queue_name="evaluations",
        task_id="message-attempt-finalization",
    )
    assert completed is not None
    assert completed.status == "completed"
    assert completed.metadata["task_execution_claim"] == "finalization_recovery"


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
        return SqlAlchemyTaskService(session_factory).claim_task_execution(
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
