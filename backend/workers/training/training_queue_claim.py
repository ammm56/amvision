"""训练任务队列领取与 crash lease 恢复。"""

from __future__ import annotations

from backend.service.application.ports.queue import QueueBackend, QueueMessage
from backend.workers.training.training_lease_heartbeat import (
    TRAINING_LEASE_TIMEOUT_SECONDS,
)


def claim_next_training_queue(
    queue_backend: QueueBackend,
    *,
    queue_names: tuple[str, ...],
    worker_id: str,
) -> QueueMessage | None:
    """先按训练专用超时恢复 stale lease，再按顺序领取任务。"""

    recover_expired_leases = getattr(
        queue_backend,
        "recover_expired_leases",
        None,
    )
    for queue_name in queue_names:
        if callable(recover_expired_leases):
            recover_expired_leases(
                queue_name=queue_name,
                lease_timeout_seconds=TRAINING_LEASE_TIMEOUT_SECONDS,
            )
        queue_task = queue_backend.claim_next(
            queue_name=queue_name,
            worker_id=worker_id,
        )
        if queue_task is not None:
            return queue_task
    return None


def build_training_run_metadata(
    queue_task: QueueMessage,
    *,
    queue_backend: QueueBackend | None = None,
) -> dict[str, object]:
    """把 queue lease 恢复信息传给训练执行器。"""

    recovery_count = queue_task.metadata.get("lease_recovery_count")
    normalized_recovery_count = (
        recovery_count if isinstance(recovery_count, int) else 0
    )
    metadata: dict[str, object] = {
        "queue_task_id": queue_task.task_id,
        "queue_attempt_count": queue_task.attempt_count,
        "queue_lease_recovery_count": normalized_recovery_count,
        "queue_lease_recovered": normalized_recovery_count > 0,
    }
    fence_resolver = getattr(queue_backend, "get_execution_fence", None)
    if callable(fence_resolver):
        fence = fence_resolver(queue_task, include_heartbeat=False)
        metadata["task_execution_fence"] = {
            "attempt_id": fence.attempt_id,
            "worker_id": fence.worker_id,
            "queue_message_id": fence.queue_message_id,
            "queue_attempt_count": fence.queue_attempt_count,
        }
    return metadata


__all__ = ["build_training_run_metadata", "claim_next_training_queue"]
