"""从训练产物的原始记录读取轮次。"""

from collections.abc import Mapping
from typing import Literal


def read_training_output_epoch(payload: Mapping[str, object]) -> int | None:
    """返回产物记录覆盖的最后一轮，兼容指标历史和训练摘要。"""
    if payload.get("available") is False:
        return None
    for key in ("epoch", "completed_epoch", "latest_checkpoint_epoch"):
        value = _read_epoch(payload.get(key))
        if value is not None:
            return value
    epoch_index = payload.get("epoch_index")
    if type(epoch_index) is int and epoch_index >= 0:
        return epoch_index + 1

    history_epochs = (
        _read_epoch(point.get("epoch"))
        for key in ("epoch_history", "runtime_history", "history")
        if isinstance(history := payload.get(key), list)
        for point in history
        if isinstance(point, dict)
    )
    epochs = [epoch for epoch in history_epochs if epoch is not None]
    evaluated = payload.get("evaluated_epochs")
    if isinstance(evaluated, list):
        epochs.extend(epoch for value in evaluated if (epoch := _read_epoch(value)) is not None)
    for key in ("metrics_payload", "validation_metrics_payload"):
        report = payload.get(key)
        if isinstance(report, dict) and (epoch := read_training_output_epoch(report)) is not None:
            epochs.append(epoch)
    return max(epochs, default=None)


def _read_epoch(value: object) -> int | None:
    """排除非轮次值和未开始训练时的零轮。"""
    return value if type(value) is int and value > 0 else None


def read_training_checkpoint_role(payload: Mapping[str, object]) -> Literal["best", "latest"] | None:
    """读取评估类产物明确使用的检查点。"""
    role = payload.get("checkpoint_role")
    if role == "best":
        return "best"
    if role == "latest":
        return "latest"
    return None
