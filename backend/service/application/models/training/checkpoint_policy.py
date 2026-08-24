"""所有模型共享的训练 checkpoint 调度规则。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Protocol

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class TrainingCheckpointPersistenceDecision:
    """描述一个 completed epoch checkpoint 是否需要持久化。"""

    should_persist: bool
    reasons: tuple[str, ...]

    @property
    def is_control_checkpoint(self) -> bool:
        """判断是否由保存、暂停或终止命令触发。"""

        return any(
            reason in {"manual", "pause", "terminate"}
            for reason in self.reasons
        )


class _CheckpointStorage(Protocol):
    """约束周期 checkpoint 保留器需要的对象存储最小接口。"""

    def resolve(self, relative_path: str) -> Path:
        """解析 object key。"""

    def write_bytes(self, relative_path: str, content: bytes) -> None:
        """写入 checkpoint。"""

    def write_json(self, relative_path: str, payload: object) -> None:
        """写入 checkpoint 索引。"""

    def delete_tree(self, relative_path: str) -> None:
        """删除过期 checkpoint。"""


_PERIODIC_CHECKPOINT_PATTERN = re.compile(r"^epoch-(?P<epoch>[0-9]{6})\.pt$")


class TrainingPeriodicCheckpointRetention:
    """统一保存并有界保留训练周期 checkpoint。

    ``latest`` 和 ``best`` 仍由各训练服务维护；这里仅负责用户配置的周期历史，
    避免把同一轮因 best/manual 等多个原因触发的 savepoint 重复写入磁盘。
    """

    def __init__(
        self,
        *,
        storage: _CheckpointStorage,
        output_prefix: str,
        interval_epochs: int,
        keep_periodic: int,
    ) -> None:
        self.storage = storage
        self.output_prefix = str(output_prefix).rstrip("/")
        self.interval_epochs = _validate_checkpoint_interval(interval_epochs)
        self.keep_periodic = _validate_checkpoint_keep_periodic(keep_periodic)
        self.directory_object_key = (
            f"{self.output_prefix}/output-files/checkpoints"
        )
        self.index_object_key = (
            f"{self.output_prefix}/output-files/checkpoints/index.json"
        )

    def persist(self, *, epoch: int, checkpoint_bytes: bytes) -> tuple[str, ...]:
        """在周期边界写入一次 checkpoint，并删除超出保留数的旧文件。"""

        completed_epoch = int(epoch)
        if completed_epoch < 1:
            raise InvalidRequestError("checkpoint epoch 必须大于等于 1")
        if completed_epoch % self.interval_epochs != 0:
            return self.list_object_keys()
        object_key = self._object_key(completed_epoch)
        self.storage.write_bytes(object_key, checkpoint_bytes)
        keys = list(self.list_object_keys())
        while len(keys) > self.keep_periodic:
            self.storage.delete_tree(keys.pop(0))
        self.storage.write_json(
            self.index_object_key,
            {
                "contract_version": 1,
                "interval_epochs": self.interval_epochs,
                "keep_periodic": self.keep_periodic,
                "checkpoint_object_keys": keys,
            },
        )
        return tuple(keys)

    def list_object_keys(self) -> tuple[str, ...]:
        """返回已存在的周期 checkpoint，按 epoch 升序排列。"""

        directory = self.storage.resolve(self.directory_object_key)
        if not directory.is_dir():
            return ()
        entries: list[tuple[int, str]] = []
        for path in directory.iterdir():
            if not path.is_file():
                continue
            match = _PERIODIC_CHECKPOINT_PATTERN.fullmatch(path.name)
            if match is None:
                continue
            entries.append(
                (
                    int(match.group("epoch")),
                    f"{self.directory_object_key}/{path.name}",
                )
            )
        entries.sort(key=lambda item: item[0])
        return tuple(object_key for _epoch, object_key in entries)

    def _object_key(self, epoch: int) -> str:
        """构造固定宽度 epoch 文件名，保证字典序与轮次一致。"""

        return f"{self.directory_object_key}/epoch-{int(epoch):06d}.pt"


def resolve_training_checkpoint_persistence_decision(
    *,
    completed_epoch: int,
    max_epochs: int,
    interval_epochs: int,
    best_improved: bool = False,
    manual_save_requested: bool = False,
    pause_requested: bool = False,
    terminate_requested: bool = False,
) -> TrainingCheckpointPersistenceDecision:
    """解析训练 epoch 边界的 checkpoint 持久化条件。

    ``completed_epoch`` 使用一基轮数。内存 completed-epoch snapshot 每轮都必须
    生成；本决策只控制何时把现有不可变 bytes 写入持久存储。
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
    return TrainingCheckpointPersistenceDecision(
        should_persist=bool(reasons),
        reasons=tuple(reasons),
    )


def read_training_checkpoint_interval(
    extra_options: dict[str, object] | None,
    *,
    default: int = 5,
) -> int:
    """从训练 option 读取并严格校验 checkpoint 周期。"""

    raw_value = (extra_options or {}).get("checkpoint_interval", default)
    return _validate_checkpoint_interval(raw_value)


def read_training_checkpoint_keep_periodic(
    extra_options: dict[str, object] | None,
    *,
    default: int = 2,
) -> int:
    """从训练 option 读取并严格校验周期 checkpoint 保留数。"""

    raw_value = (extra_options or {}).get("checkpoint_keep_periodic", default)
    return _validate_checkpoint_keep_periodic(raw_value)


def build_training_periodic_checkpoint_retention(
    *,
    storage: _CheckpointStorage,
    output_prefix: str,
    extra_options: dict[str, object] | None,
) -> TrainingPeriodicCheckpointRetention:
    """按公开 execution 配置构造统一周期 checkpoint 保留器。"""

    return TrainingPeriodicCheckpointRetention(
        storage=storage,
        output_prefix=output_prefix,
        interval_epochs=read_training_checkpoint_interval(extra_options),
        keep_periodic=read_training_checkpoint_keep_periodic(extra_options),
    )


def _validate_checkpoint_interval(value: object) -> int:
    """校验 checkpoint 周期。"""

    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidRequestError(
            "checkpoint_interval 必须是整数",
            details={"checkpoint_interval": value},
        )
    if value < 1:
        raise InvalidRequestError(
            "checkpoint_interval 必须大于等于 1",
            details={"checkpoint_interval": value},
        )
    return int(value)


def _validate_checkpoint_keep_periodic(value: object) -> int:
    """校验周期 checkpoint 保留数。"""

    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidRequestError(
            "checkpoint_keep_periodic 必须是整数",
            details={"checkpoint_keep_periodic": value},
        )
    if value < 1 or value > 100:
        raise InvalidRequestError(
            "checkpoint_keep_periodic 必须在 1..100 范围内",
            details={"checkpoint_keep_periodic": value},
        )
    return int(value)


__all__ = [
    "TrainingPeriodicCheckpointRetention",
    "build_training_periodic_checkpoint_retention",
    "TrainingCheckpointPersistenceDecision",
    "read_training_checkpoint_interval",
    "read_training_checkpoint_keep_periodic",
    "resolve_training_checkpoint_persistence_decision",
]
