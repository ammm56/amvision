"""YOLO 主线 non-detection 训练 worker 轻量回归。"""

from __future__ import annotations

from pathlib import Path

import pytest

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
)


class _KeywordOnlyQueueBackend:
    """模拟当前只接受关键字参数的队列后端。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def claim_next(self, *, queue_name: str, worker_id: str):
        self.calls.append((queue_name, worker_id))
        return None


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

    session_factory = SessionFactory(DatabaseSettings(url=f"sqlite:///{(tmp_path / 'worker.db').as_posix()}"))
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
