"""所有模型共享的训练 checkpoint 调度规则。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class TrainingCheckpointDecision:
    """描述一个 epoch 边界是否需要序列化并发布 checkpoint。"""

    should_serialize: bool
    reasons: tuple[str, ...]

    @property
    def is_control_checkpoint(self) -> bool:
        """判断是否由保存、暂停或终止命令触发。"""

        return any(
            reason in {"manual", "pause", "terminate"}
            for reason in self.reasons
        )


def resolve_training_checkpoint_decision(
    *,
    completed_epoch: int,
    max_epochs: int,
    interval_epochs: int,
    best_improved: bool = False,
    manual_save_requested: bool = False,
    pause_requested: bool = False,
    terminate_requested: bool = False,
) -> TrainingCheckpointDecision:
    """解析训练 epoch 边界的完整 checkpoint 生成条件。

    ``completed_epoch`` 使用一基轮数。调用方每轮仍可更新轻量内存状态，但只有
    返回 ``should_serialize=True`` 时才允许执行 ``torch.save`` 或写入对象存储。
    """

    resolved_epoch = int(completed_epoch)
    resolved_max_epochs = int(max_epochs)
    resolved_interval = int(interval_epochs)
    if resolved_epoch < 1:
        raise InvalidRequestError("completed_epoch 必须大于等于 1")
    if resolved_max_epochs < 1:
        raise InvalidRequestError("max_epochs 必须大于等于 1")
    if resolved_epoch > resolved_max_epochs:
        raise InvalidRequestError("completed_epoch 不能大于 max_epochs")
    if resolved_interval < 1:
        raise InvalidRequestError("checkpoint interval_epochs 必须大于等于 1")

    reasons: list[str] = []
    if resolved_epoch % resolved_interval == 0:
        reasons.append("periodic")
    if best_improved:
        reasons.append("best")
    if resolved_epoch == resolved_max_epochs:
        reasons.append("final")
    if manual_save_requested:
        reasons.append("manual")
    if pause_requested:
        reasons.append("pause")
    if terminate_requested:
        reasons.append("terminate")
    return TrainingCheckpointDecision(
        should_serialize=bool(reasons),
        reasons=tuple(reasons),
    )


def read_training_checkpoint_interval(
    extra_options: dict[str, object] | None,
    *,
    default: int = 5,
) -> int:
    """从训练 option 读取并严格校验 checkpoint 周期。"""

    raw_value = (extra_options or {}).get("checkpoint_interval", default)
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(
            "checkpoint_interval 必须是整数",
            details={"checkpoint_interval": raw_value},
        )
    if raw_value < 1:
        raise InvalidRequestError(
            "checkpoint_interval 必须大于等于 1",
            details={"checkpoint_interval": raw_value},
        )
    return int(raw_value)


__all__ = [
    "TrainingCheckpointDecision",
    "read_training_checkpoint_interval",
    "resolve_training_checkpoint_decision",
]
