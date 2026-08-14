"""YOLO 主线 non-detection 训练 worker 轻量回归。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base
from backend.workers.training.yolo_training_queue_worker import (
    ClassificationTrainingQueueWorker,
    ObbTrainingQueueWorker,
    PoseTrainingQueueWorker,
    SegmentationTrainingQueueWorker,
    _build_training_run_metadata,
    _claim_next_training_queue,
    _read_model_type,
)
from backend.queue import QueueMessage
from backend.workers.training.training_lease_heartbeat import (
    TRAINING_LEASE_TIMEOUT_SECONDS,
)


class _KeywordOnlyQueueBackend:
    """模拟当前只接受关键字参数的队列后端。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def claim_next(self, *, queue_name: str, worker_id: str):
        self.calls.append((queue_name, worker_id))
        return None


class _RecoveringQueueBackend(_KeywordOnlyQueueBackend):
    """记录训练 worker 使用的 lease 恢复超时。"""

    def __init__(self, queue_message: QueueMessage) -> None:
        super().__init__()
        self.queue_message = queue_message
        self.recovery_calls: list[tuple[str, float]] = []

    def recover_expired_leases(
        self,
        *,
        queue_name: str,
        lease_timeout_seconds: float,
    ) -> int:
        self.recovery_calls.append((queue_name, lease_timeout_seconds))
        return 1

    def claim_next(self, *, queue_name: str, worker_id: str):
        super().claim_next(queue_name=queue_name, worker_id=worker_id)
        return self.queue_message


def test_read_model_type_requires_explicit_supported_task_mapping() -> None:
    """验证 worker 不再把缺失或错误的模型类型静默回退到 YOLOv8。"""

    assert (
        _read_model_type({"model_type": "rfdetr"}, task_type="segmentation") == "rfdetr"
    )
    with pytest.raises(InvalidRequestError, match="缺少 model_type"):
        _read_model_type({}, task_type="segmentation")
    with pytest.raises(InvalidRequestError, match="模型分类与任务类型不匹配"):
        _read_model_type({"model_type": "rfdetr"}, task_type="classification")


@pytest.mark.parametrize(
    ("worker_cls", "worker_id", "expected_queue_count"),
    [
        (ClassificationTrainingQueueWorker, "classification-training-worker", 3),
        (SegmentationTrainingQueueWorker, "segmentation-training-worker", 3),
        (PoseTrainingQueueWorker, "pose-training-worker", 3),
        (ObbTrainingQueueWorker, "obb-training-worker", 3),
    ],
)
def test_yolo_training_workers_use_keyword_only_claim_next(
    tmp_path: Path,
    worker_cls: type,
    worker_id: str,
    expected_queue_count: int,
) -> None:
    """验证 non-detection 训练 worker 使用 QueueBackend 新签名。"""

    session_factory = SessionFactory(
        DatabaseSettings(url=f"sqlite:///{(tmp_path / 'worker.db').as_posix()}")
    )
    Base.metadata.create_all(session_factory.engine)
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    queue_backend = _KeywordOnlyQueueBackend()

    worker = worker_cls(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        worker_id=worker_id,
    )

    try:
        assert worker.run_once() is False
        assert len(queue_backend.calls) == expected_queue_count
        assert {call[1] for call in queue_backend.calls} == {worker_id}
    finally:
        session_factory.engine.dispose()


def test_training_queue_claim_recovers_stale_lease_with_training_timeout() -> None:
    """验证训练队列不再沿用普通任务的一天 lease 恢复超时。"""

    queue_message = QueueMessage(
        queue_name="pose-trainings",
        task_id="queue-task-1",
        payload={"task_id": "task-1"},
        status="leased",
        worker_id="worker-b",
        attempt_count=2,
        metadata={"lease_recovery_count": 1},
    )
    queue_backend = _RecoveringQueueBackend(queue_message)

    claimed = _claim_next_training_queue(
        queue_backend,
        queue_names=("pose-trainings",),
        worker_id="worker-b",
    )

    assert claimed is queue_message
    assert queue_backend.recovery_calls == [
        ("pose-trainings", TRAINING_LEASE_TIMEOUT_SECONDS)
    ]
    assert _build_training_run_metadata(queue_message) == {
        "queue_task_id": "queue-task-1",
        "queue_attempt_count": 2,
        "queue_lease_recovery_count": 1,
        "queue_lease_recovered": True,
    }
