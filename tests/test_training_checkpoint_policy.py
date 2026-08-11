"""共享训练 checkpoint 调度回归测试。"""

from __future__ import annotations

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.training.checkpoint_policy import (
    read_training_checkpoint_interval,
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
