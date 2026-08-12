"""本地文件队列 lease 恢复与清理测试。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Event, Thread
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


def test_local_file_queue_claims_task_once_across_backend_instances(tmp_path: Path) -> None:
    """验证同一队列目录的多个 backend 实例不会重复领取同一任务。"""

    settings = LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    first_backend = LocalFileQueueBackend(settings)
    second_backend = LocalFileQueueBackend(settings)
    queued_task = first_backend.enqueue(queue_name="jobs", payload={"task_id": "task-1"})

    first_claim = first_backend.claim_next(queue_name="jobs", worker_id="worker-a")
    second_claim = second_backend.claim_next(queue_name="jobs", worker_id="worker-b")

    assert first_claim is not None
    assert first_claim.task_id == queued_task.task_id
    assert second_claim is None


def test_local_file_queue_recovers_leased_task_without_lease_timestamp(tmp_path: Path) -> None:
    """验证异常中断留下的无 lease 时间文件可以恢复。"""

    queue_backend = LocalFileQueueBackend(LocalFileQueueSettings(root_dir=str(tmp_path / "queue")))
    queued_task = queue_backend.enqueue(queue_name="jobs", payload={"task_id": "task-1"})
    pending_path = tmp_path / "queue" / "jobs" / "pending" / f"{queued_task.task_id}.json"
    leased_path = tmp_path / "queue" / "jobs" / "leased" / f"{queued_task.task_id}.json"
    leased_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path.replace(leased_path)
    _age_path_tree(leased_path, seconds=60.0)

    recovered_count = queue_backend.recover_expired_leases(queue_name="jobs")
    reclaimed_task = queue_backend.claim_next(queue_name="jobs", worker_id="worker-a")

    assert recovered_count == 1
    assert reclaimed_task is not None
    assert reclaimed_task.task_id == queued_task.task_id
    assert reclaimed_task.attempt_count == 1


def test_local_file_queue_does_not_recover_inflight_claim_from_another_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """claim 写入 lease 的过渡窗口不得被另一个 backend 恢复并重复执行。"""

    settings = LocalFileQueueSettings(root_dir=str(tmp_path / "queue"))
    first_backend = LocalFileQueueBackend(settings)
    second_backend = LocalFileQueueBackend(settings)
    queued_task = first_backend.enqueue(
        queue_name="jobs",
        payload={"task_id": "task-1"},
    )
    entered_transition = Event()
    release_transition = Event()
    original_overwrite = first_backend._overwrite_task_file

    def overwrite_after_pause(task_path: Path, queue_task: object) -> None:
        if task_path.parent.name == "leased":
            entered_transition.set()
            assert release_transition.wait(timeout=5.0)
        original_overwrite(task_path, queue_task)

    monkeypatch.setattr(first_backend, "_overwrite_task_file", overwrite_after_pause)
    first_result: list[object] = []

    def claim_first() -> None:
        first_result.append(
            first_backend.claim_next(queue_name="jobs", worker_id="worker-a")
        )

    claim_thread = Thread(target=claim_first, daemon=True)
    claim_thread.start()
    assert entered_transition.wait(timeout=5.0)

    second_claim = second_backend.claim_next(
        queue_name="jobs",
        worker_id="worker-b",
    )
    release_transition.set()
    claim_thread.join(timeout=5.0)

    assert not claim_thread.is_alive()
    assert len(first_result) == 1
    assert first_result[0] is not None
    assert first_result[0].task_id == queued_task.task_id
    assert second_claim is None


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


def test_local_file_queue_retries_windows_sharing_violation_on_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 Windows 短暂文件占用不会让已执行任务丢失终态。"""

    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(
            root_dir=str(tmp_path / "queue"),
            file_operation_retry_timeout_seconds=1.0,
        )
    )
    queued_task = queue_backend.enqueue(queue_name="jobs", payload={"task_id": "task-1"})
    leased_task = queue_backend.claim_next(queue_name="jobs", worker_id="worker-a")
    assert leased_task is not None

    original_replace = Path.replace
    sharing_violation_count = 0

    def replace_with_transient_lock(
        source_path: Path,
        target_path: str | Path,
    ) -> Path:
        nonlocal sharing_violation_count
        normalized_target = Path(target_path)
        if (
            source_path.parent.name == "leased"
            and normalized_target.parent.name == "completed"
            and sharing_violation_count < 3
        ):
            sharing_violation_count += 1
            error = PermissionError("simulated Windows sharing violation")
            error.winerror = 32  # type: ignore[attr-defined]
            raise error
        return original_replace(source_path, target_path)

    monkeypatch.setattr(Path, "replace", replace_with_transient_lock)

    completed_task = queue_backend.complete(leased_task)

    assert sharing_violation_count == 3
    assert completed_task.status == "completed"
    stored_task = queue_backend.get_task(
        queue_name="jobs",
        task_id=queued_task.task_id,
    )
    assert stored_task is not None
    assert stored_task.status == "completed"


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
