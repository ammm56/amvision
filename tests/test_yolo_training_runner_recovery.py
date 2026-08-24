"""YOLO non-detection 训练 runner 的 queue lease 恢复测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.service.application.backends import TrainingBackendRunRequest
from backend.service.application.errors import InvalidRequestError
from backend.service.application.tasks.task_service import (
    CreateTaskRequest,
    SqlAlchemyTaskService,
    TaskExecutionFence,
)
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base
from backend.workers.training.yolo_training_runner import SqlAlchemyYoloTrainingRunner


def _build_runner_context(
    tmp_path: Path,
) -> tuple[
    SessionFactory,
    LocalDatasetStorage,
    SqlAlchemyTaskService,
    SqlAlchemyYoloTrainingRunner,
]:
    """构建只覆盖 lease 恢复逻辑的最小持久化上下文。"""

    session_factory = SessionFactory(
        DatabaseSettings(url=f"sqlite:///{(tmp_path / 'runner.db').as_posix()}")
    )
    Base.metadata.create_all(session_factory.engine)
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    task_service = SqlAlchemyTaskService(session_factory=session_factory)
    runner = SqlAlchemyYoloTrainingRunner(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    return session_factory, dataset_storage, task_service, runner


def test_recovered_running_task_exposes_checkpoint_and_increments_attempt(
    tmp_path: Path,
) -> None:
    """验证 worker 崩溃后的 lease 回收会从 latest checkpoint 继续。"""

    session_factory, dataset_storage, task_service, runner = _build_runner_context(
        tmp_path
    )
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-recovered",
            project_id="project-1",
            task_kind="yolov8-pose-training",
        )
    )
    claim = task_service.claim_task_execution(
        task_id="task-recovered",
        attempt_no=1,
        worker_id="worker-recovered",
        queue_name="trainings",
        queue_message_id="queue-task-1",
        queue_attempt_count=2,
        queue_leased_at="2026-08-24T00:00:00+00:00",
        lease_recovery_count=1,
    )
    assert claim.attempt is not None
    task = claim.task
    execution_fence = TaskExecutionFence(
        attempt_id=claim.attempt.attempt_id,
        worker_id="worker-recovered",
        heartbeat_at="2026-08-24T00:00:00+00:00",
        queue_message_id="queue-task-1",
        queue_attempt_count=2,
    )
    checkpoint_key = (
        "task-runs/task-recovered/output-files/latest-checkpoint.pt"
    )
    dataset_storage.write_bytes(checkpoint_key, b"checkpoint")

    try:
        recovered_task = runner._restore_recovered_running_task(
            task=task,
            task_service=task_service,
            request=TrainingBackendRunRequest(
                training_task_id=task.task_id,
                metadata={
                    "queue_task_id": "queue-task-1",
                    "queue_attempt_count": 2,
                    "queue_lease_recovery_count": 1,
                    "queue_lease_recovered": True,
                },
            ),
            execution_fence=execution_fence,
        )

        assert recovered_task.state == "running"
        assert recovered_task.current_attempt_no == 1
        assert recovered_task.result["latest_checkpoint_object_key"] == checkpoint_key
        assert recovered_task.metadata["training_queue_recovery"] == {
            "queue_task_id": "queue-task-1",
            "queue_attempt_count": 2,
            "lease_recovery_count": 1,
        }
        events = task_service.get_task(task.task_id, include_events=True).events
        assert events[-1].message == "training queue lease recovered"
    finally:
        session_factory.engine.dispose()


def test_recovered_running_task_requires_latest_checkpoint(tmp_path: Path) -> None:
    """验证已有训练进度却没有 checkpoint 时不会从头覆盖旧输出。"""

    session_factory, _, task_service, runner = _build_runner_context(tmp_path)
    task_service.create_task(
        CreateTaskRequest(
            task_id="task-without-checkpoint",
            project_id="project-1",
            task_kind="yolov8-pose-training",
        )
    )
    claim = task_service.claim_task_execution(
        task_id="task-without-checkpoint",
        attempt_no=1,
        worker_id="worker-recovered",
        queue_name="trainings",
        queue_message_id="queue-task-2",
        queue_attempt_count=2,
        queue_leased_at="2026-08-24T00:00:00+00:00",
        lease_recovery_count=1,
    )
    assert claim.attempt is not None
    task = claim.task
    execution_fence = TaskExecutionFence(
        attempt_id=claim.attempt.attempt_id,
        worker_id="worker-recovered",
        heartbeat_at="2026-08-24T00:00:00+00:00",
        queue_message_id="queue-task-2",
        queue_attempt_count=2,
    )

    try:
        with pytest.raises(InvalidRequestError, match="latest checkpoint 不存在"):
            runner._restore_recovered_running_task(
                task=task,
                task_service=task_service,
                request=TrainingBackendRunRequest(
                    training_task_id=task.task_id,
                    metadata={"queue_lease_recovered": True},
                ),
                execution_fence=execution_fence,
            )
    finally:
        session_factory.engine.dispose()
