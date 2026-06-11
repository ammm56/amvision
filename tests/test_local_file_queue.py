"""本地文件队列 lease 恢复与清理测试。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from time import time

import pytest

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.application.errors import PersistenceOperationError


def test_local_file_queue_recovers_expired_leased_task(tmp_path: Path) -> None:
    """验证超时 leased 任务会恢复到 pending 并可再次领取。"""

    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(
            root_dir=str(tmp_path / "queue"),
            lease_timeout_seconds=0.1,
        )
    )
    queued_task = queue_backend.enqueue(
        queue_name="jobs",
        payload={"task_id": "task-1"},
    )
    leased_task = queue_backend.claim_next(queue_name="jobs", worker_id="worker-a")
    assert leased_task is not None
    leased_path = tmp_path / "queue" / "jobs" / "leased" / f"{queued_task.task_id}.json"
    _rewrite_queue_task_time(leased_path, leased_at="2000-01-01T00:00:00+00:00")

    recovered_count = queue_backend.recover_expired_leases(queue_name="jobs")
    reclaimed_task = queue_backend.claim_next(queue_name="jobs", worker_id="worker-b")

    assert recovered_count == 1
    assert reclaimed_task is not None
    assert reclaimed_task.task_id == queued_task.task_id
    assert reclaimed_task.worker_id == "worker-b"
    assert reclaimed_task.attempt_count == 2
    assert reclaimed_task.metadata["lease_recovery_count"] == 1
    assert reclaimed_task.metadata["last_lease_worker_id"] == "worker-a"


def test_local_file_queue_rejects_stale_lease_completion_after_recovery(tmp_path: Path) -> None:
    """验证旧 worker 不能完成已经被恢复并重新领取的任务。"""

    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(
            root_dir=str(tmp_path / "queue"),
            lease_timeout_seconds=0.1,
        )
    )
    queued_task = queue_backend.enqueue(queue_name="jobs", payload={"task_id": "task-1"})
    stale_task = queue_backend.claim_next(queue_name="jobs", worker_id="worker-a")
    assert stale_task is not None
    leased_path = tmp_path / "queue" / "jobs" / "leased" / f"{queued_task.task_id}.json"
    _rewrite_queue_task_time(leased_path, leased_at="2000-01-01T00:00:00+00:00")

    queue_backend.recover_expired_leases(queue_name="jobs")
    current_task = queue_backend.claim_next(queue_name="jobs", worker_id="worker-b")
    assert current_task is not None

    with pytest.raises(PersistenceOperationError):
        queue_backend.complete(stale_task)
    completed_task = queue_backend.complete(current_task)

    assert completed_task.status == "completed"
    assert completed_task.worker_id == "worker-b"


def test_local_file_queue_cleans_response_queue_directories(tmp_path: Path) -> None:
    """验证一次性响应队列目录超过保留期后会被整体清理。"""

    queue_backend = LocalFileQueueBackend(LocalFileQueueSettings(root_dir=str(tmp_path / "queue")))
    response_queue_name = "detection-ai-rsp-test"
    response_task = queue_backend.enqueue(
        queue_name=response_queue_name,
        payload={"request_id": "request-1", "ok": True},
    )
    leased_response = queue_backend.claim_next(queue_name=response_queue_name, worker_id="worker-a")
    assert leased_response is not None
    queue_backend.complete(leased_response, metadata={"request_id": response_task.payload["request_id"]})
    response_queue_dir = tmp_path / "queue" / response_queue_name
    _age_path_tree(response_queue_dir, seconds=30.0)

    deleted_count = queue_backend.cleanup_queues_by_prefix(
        queue_name_prefix="detection-ai-rsp-",
        retention_seconds=1.0,
    )

    assert deleted_count == 1
    assert not response_queue_dir.exists()


def test_local_file_queue_deletes_queue_directory(tmp_path: Path) -> None:
    """验证指定队列目录可以被显式删除。"""

    queue_backend = LocalFileQueueBackend(LocalFileQueueSettings(root_dir=str(tmp_path / "queue")))
    queue_backend.enqueue(queue_name="detection-ai-rsp-test", payload={"request_id": "request-1"})

    deleted = queue_backend.delete_queue(queue_name="detection-ai-rsp-test")

    assert deleted is True
    assert not (tmp_path / "queue" / "detection-ai-rsp-test").exists()


def _rewrite_queue_task_time(task_path: Path, *, leased_at: str) -> None:
    """改写测试队列任务文件里的 lease 时间。"""

    payload = json.loads(task_path.read_text(encoding="utf-8"))
    payload["leased_at"] = leased_at
    task_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _age_path_tree(path: Path, *, seconds: float) -> None:
    """把目录树修改时间调早，便于测试保留期清理。"""

    target_time = time() - seconds
    for child_path in path.rglob("*"):
        os.utime(child_path, (target_time, target_time))
    os.utime(path, (target_time, target_time))
