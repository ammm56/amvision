"""训练任务队列 lease heartbeat 定点测试。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep

import pytest

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings, QueueMessage
from backend.service.application.errors import PersistenceOperationError
from backend.workers.training.training_lease_heartbeat import TrainingLeaseHeartbeat


@pytest.mark.parametrize("final_state", ["completed", "failed"])
def test_training_lease_heartbeat_uses_latest_message_for_final_state(
    tmp_path: Path,
    final_state: str,
) -> None:
    """验证 heartbeat 停止后返回的最新消息可以完成或失败队列任务。"""

    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(
            root_dir=str(tmp_path / "queue"),
            lease_timeout_seconds=0.3,
        )
    )
    queue_backend.enqueue(queue_name="trainings", payload={"task_id": "training-1"})
    leased_task = queue_backend.claim_next(
        queue_name="trainings",
        worker_id="training-worker-a",
    )
    assert leased_task is not None

    heartbeat = TrainingLeaseHeartbeat(
        queue_backend=queue_backend,
        queue_message=leased_task,
        interval_seconds=0.02,
    )
    heartbeat.start()
    _wait_until(lambda: heartbeat.current_message.leased_at != leased_task.leased_at)
    current_task = heartbeat.stop()

    assert heartbeat.is_running is False
    assert current_task.leased_at != leased_task.leased_at
    if final_state == "completed":
        finalized_task = queue_backend.complete(current_task)
    else:
        finalized_task = queue_backend.fail(
            current_task,
            error_message="training failed",
        )
    assert finalized_task.status == final_state


def test_training_lease_heartbeat_prevents_expired_lease_recovery(tmp_path: Path) -> None:
    """验证训练持续刷新 lease 时，其他 worker 不能回收并重新领取任务。"""

    settings = LocalFileQueueSettings(
        root_dir=str(tmp_path / "queue"),
        lease_timeout_seconds=0.08,
    )
    owner_backend = LocalFileQueueBackend(settings)
    competing_backend = LocalFileQueueBackend(settings)
    owner_backend.enqueue(queue_name="trainings", payload={"task_id": "training-1"})
    leased_task = owner_backend.claim_next(
        queue_name="trainings",
        worker_id="training-worker-a",
    )
    assert leased_task is not None

    heartbeat = TrainingLeaseHeartbeat(
        queue_backend=owner_backend,
        queue_message=leased_task,
        interval_seconds=0.01,
    )
    heartbeat.start()
    try:
        sleep(0.2)
        competing_task = competing_backend.claim_next(
            queue_name="trainings",
            worker_id="training-worker-b",
        )
        assert competing_task is None
    finally:
        current_task = heartbeat.stop()

    completed_task = owner_backend.complete(current_task)
    assert completed_task.status == "completed"


def test_training_lease_heartbeat_marks_replaced_attempt_as_lost() -> None:
    """验证队列任务已被其他 worker 接管时，heartbeat 会停止继续刷新。"""

    leased_task = QueueMessage(
        queue_name="trainings",
        task_id="queue-task-1",
        status="leased",
        leased_at="2026-08-01T00:00:00+00:00",
        worker_id="training-worker-a",
        attempt_count=1,
    )
    replacement_task = QueueMessage(
        queue_name="trainings",
        task_id="queue-task-1",
        status="leased",
        leased_at="2026-08-02T00:00:00+00:00",
        worker_id="training-worker-b",
        attempt_count=2,
    )
    queue_backend = _ReplacedLeaseQueueBackend(replacement_task=replacement_task)
    heartbeat = TrainingLeaseHeartbeat(
        queue_backend=queue_backend,  # type: ignore[arg-type]
        queue_message=leased_task,
        interval_seconds=0.01,
    )

    heartbeat.start()
    _wait_until(lambda: heartbeat.lease_lost)
    heartbeat.stop()

    assert heartbeat.lease_lost is True
    assert heartbeat.is_running is False
    assert queue_backend.refresh_count == 1


def _wait_until(predicate, *, timeout_seconds: float = 2.0) -> None:
    """等待异步测试条件成立，超时后让断言给出明确失败。"""

    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.01)
    raise AssertionError("等待训练 lease heartbeat 条件超时")


@dataclass
class _ReplacedLeaseQueueBackend:
    """模拟 heartbeat 刷新时 lease 已被其他 worker 接管。"""

    replacement_task: QueueMessage
    refresh_count: int = 0

    def refresh_lease(self, queue_message: QueueMessage) -> QueueMessage:
        """始终返回 lease 已失效错误。"""

        self.refresh_count += 1
        raise PersistenceOperationError(
            "队列任务 lease 已被其他 worker 接管",
            details={"task_id": queue_message.task_id},
        )

    def get_task(self, *, queue_name: str, task_id: str) -> QueueMessage:
        """返回其他 worker 当前持有的队列消息。"""

        assert queue_name == self.replacement_task.queue_name
        assert task_id == self.replacement_task.task_id
        return self.replacement_task
