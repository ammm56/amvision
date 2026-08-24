"""训练控制探针与 completed-epoch 内存 checkpoint 契约测试。"""

from __future__ import annotations

import pytest

from backend.service.application.models.training.completed_epoch_checkpoint import (
    CompletedEpochCheckpointCoordinator,
)
from backend.service.application.models.training.training_control_probe import (
    TrainingControlDecision,
    TrainingControlProbe,
)


def test_training_control_probe_throttles_persistent_reads() -> None:
    """任意数量 batch 不得变成每 batch 数据库读取。"""

    now = [10.0]
    reads: list[float] = []

    def read_control() -> TrainingControlDecision:
        reads.append(now[0])
        return TrainingControlDecision()

    probe = TrainingControlProbe(
        read_control=read_control,
        poll_interval_seconds=0.25,
        monotonic_clock=lambda: now[0],
    )

    for _ in range(100):
        assert probe.observe().action == "none"
    assert reads == [10.0]

    now[0] = 10.249
    probe.observe()
    assert reads == [10.0]
    now[0] = 10.25
    probe.observe()
    assert reads == [10.0, 10.25]


def test_training_control_probe_latches_pause_between_polls() -> None:
    """暂停一经观察，在下一次持久读取前不能因 batch 调用而丢失。"""

    now = [1.0]
    probe = TrainingControlProbe(
        read_control=lambda: TrainingControlDecision(
            action="pause",
            requested_at="2026-08-24T00:00:00+00:00",
        ),
        monotonic_clock=lambda: now[0],
    )

    first = probe.observe()
    now[0] = 1.1
    second = probe.observe()
    assert first.pause_requested is True
    assert second == first


def test_training_control_probe_invalidate_clears_one_shot_save_cache() -> None:
    """手动保存被确认后，下一 batch 必须立即重新读取而不是重复保存。"""

    decisions = iter(
        [TrainingControlDecision(action="save"), TrainingControlDecision()]
    )
    probe = TrainingControlProbe(
        read_control=lambda: next(decisions),
        monotonic_clock=lambda: 1.0,
    )

    assert probe.observe().save_requested is True
    probe.invalidate()
    assert probe.observe().action == "none"


def test_completed_epoch_checkpoint_replaces_only_after_validation() -> None:
    """新快照构造失败时保留上一完整 epoch，不能污染恢复点。"""

    coordinator = CompletedEpochCheckpointCoordinator(attempt_id="attempt-1")
    baseline = coordinator.replace(completed_epoch=0, checkpoint_bytes=b"baseline")

    with pytest.raises(ValueError, match="不能为空"):
        coordinator.replace(completed_epoch=1, checkpoint_bytes=b"")

    assert coordinator.current == baseline
    epoch_one = coordinator.replace(completed_epoch=1, checkpoint_bytes=b"epoch-1")
    assert coordinator.current == epoch_one
    assert epoch_one.checkpoint_bytes == b"epoch-1"


def test_completed_epoch_checkpoint_persists_once_per_content_and_role() -> None:
    """暂停复用同一完整 checkpoint，不产生重复 ObjectStore 写入。"""

    coordinator = CompletedEpochCheckpointCoordinator(attempt_id="attempt-1")
    coordinator.replace(completed_epoch=5, checkpoint_bytes=b"epoch-5")
    writes: list[int] = []

    def persist(snapshot) -> str:
        writes.append(snapshot.completed_epoch)
        return "task-runs/task-1/checkpoints/latest.pt"

    first = coordinator.persist_or_reuse(role="resume", persist=persist)
    second = coordinator.persist_or_reuse(role="resume", persist=persist)

    assert first == second
    assert writes == [5]
    assert first.completed_epoch == 5


def test_completed_epoch_checkpoint_rejects_epoch_rollback() -> None:
    """同一 Attempt 的 completed epoch 只能单调推进。"""

    coordinator = CompletedEpochCheckpointCoordinator(attempt_id="attempt-1")
    coordinator.replace(completed_epoch=3, checkpoint_bytes=b"epoch-3")

    with pytest.raises(ValueError, match="不能回退"):
        coordinator.replace(completed_epoch=2, checkpoint_bytes=b"epoch-2")
