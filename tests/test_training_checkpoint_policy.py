"""共享训练 checkpoint 调度回归测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.training.checkpoint_policy import (
    TrainingPeriodicCheckpointRetention,
    read_training_checkpoint_interval,
    read_training_checkpoint_keep_periodic,
    resolve_training_checkpoint_decision,
)


def test_checkpoint_policy_does_not_serialize_an_ordinary_epoch() -> None:
    """非周期、非 best、非控制点的 epoch 不得序列化权重。"""

    decision = resolve_training_checkpoint_decision(
        completed_epoch=3,
        max_epochs=200,
        interval_epochs=5,
    )

    assert decision.should_serialize is False
    assert decision.reasons == ()


def test_checkpoint_policy_default_interval_is_five_epochs() -> None:
    """默认恢复边界固定为每 5 轮，不为小概率异常增加逐轮存盘。"""

    assert read_training_checkpoint_interval(None) == 5
    assert [
        resolve_training_checkpoint_decision(
            completed_epoch=epoch,
            max_epochs=20,
            interval_epochs=read_training_checkpoint_interval(None),
        ).should_serialize
        for epoch in range(1, 6)
    ] == [False, False, False, False, True]


@pytest.mark.parametrize(
    ("kwargs", "expected_reason"),
    [
        ({"completed_epoch": 5}, "periodic"),
        ({"completed_epoch": 3, "best_improved": True}, "best"),
        ({"completed_epoch": 3, "manual_save_requested": True}, "manual"),
        ({"completed_epoch": 3, "pause_requested": True}, "pause"),
        ({"completed_epoch": 3, "terminate_requested": True}, "terminate"),
        ({"completed_epoch": 200}, "final"),
    ],
)
def test_checkpoint_policy_serializes_every_required_boundary(
    kwargs: dict[str, object],
    expected_reason: str,
) -> None:
    """所有明确的恢复和产物边界都必须生成 checkpoint。"""

    decision = resolve_training_checkpoint_decision(
        max_epochs=200,
        interval_epochs=5,
        **kwargs,
    )

    assert decision.should_serialize is True
    assert expected_reason in decision.reasons


def test_checkpoint_policy_combines_reasons_without_losing_control_semantics() -> None:
    """周期和暂停重叠时保留全部原因。"""

    decision = resolve_training_checkpoint_decision(
        completed_epoch=10,
        max_epochs=200,
        interval_epochs=5,
        best_improved=True,
        pause_requested=True,
    )

    assert decision.reasons == ("periodic", "best", "pause")
    assert decision.is_control_checkpoint is True


@pytest.mark.parametrize("value", [0, -1, 1.5, True, "5"])
def test_checkpoint_interval_rejects_invalid_values(value: object) -> None:
    """禁止把无效周期静默归一化。"""

    with pytest.raises(InvalidRequestError):
        read_training_checkpoint_interval({"checkpoint_interval": value})


@pytest.mark.parametrize("value", [0, -1, 101, 1.5, True, "3"])
def test_checkpoint_keep_periodic_rejects_invalid_values(value: object) -> None:
    """周期历史保留数必须遵守公开 execution schema。"""

    with pytest.raises(InvalidRequestError):
        read_training_checkpoint_keep_periodic({"checkpoint_keep_periodic": value})


def test_periodic_checkpoint_retention_keeps_only_configured_history(
    tmp_path: Path,
) -> None:
    """周期 checkpoint 必须按 epoch 命名、有界保留并同步索引。"""

    class _Storage:
        def resolve(self, relative_path: str) -> Path:
            return tmp_path.joinpath(*relative_path.split("/"))

        def write_bytes(self, relative_path: str, content: bytes) -> None:
            path = self.resolve(relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        def write_json(self, relative_path: str, payload: object) -> None:
            path = self.resolve(relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")

        def delete_tree(self, relative_path: str) -> None:
            self.resolve(relative_path).unlink(missing_ok=True)

    storage = _Storage()
    retention = TrainingPeriodicCheckpointRetention(
        storage=storage,
        output_prefix="task-runs/task-1",
        interval_epochs=5,
        keep_periodic=2,
    )

    assert retention.persist(epoch=4, checkpoint_bytes=b"ignored") == ()
    retention.persist(epoch=5, checkpoint_bytes=b"epoch-5")
    retention.persist(epoch=10, checkpoint_bytes=b"epoch-10")
    retained = retention.persist(epoch=15, checkpoint_bytes=b"epoch-15")

    assert retained == (
        "task-runs/task-1/output-files/checkpoints/epoch-000010.pt",
        "task-runs/task-1/output-files/checkpoints/epoch-000015.pt",
    )
    assert not storage.resolve(
        "task-runs/task-1/output-files/checkpoints/epoch-000005.pt"
    ).exists()
    assert storage.resolve(retained[0]).read_bytes() == b"epoch-10"
    index = json.loads(storage.resolve(retention.index_object_key).read_text("utf-8"))
    assert index["checkpoint_object_keys"] == list(retained)
