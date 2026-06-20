"""YOLO11 detection 训练 savepoint 组装规则。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.service.application.models.yolo11_core.training.epoch import (
    serialize_yolo11_detection_best_metric_value,
)


@dataclass(frozen=True)
class Yolo11DetectionTrainingSavepointPayload:
    """描述 YOLO11 detection 在 epoch 边界需要交给应用层保存的数据。"""

    epoch: int
    latest_checkpoint_bytes: bytes
    best_checkpoint_bytes: bytes
    best_metric_name: str
    best_metric_value: float | None


def build_yolo11_detection_training_savepoint_payload(
    *,
    epoch: int,
    latest_checkpoint_bytes: bytes,
    best_checkpoint_bytes: bytes | None,
    best_metric_name: str,
    best_metric_value: float,
    has_validation: bool,
) -> Yolo11DetectionTrainingSavepointPayload:
    """把 YOLO11 detection 内部 checkpoint 状态转换成 savepoint payload。"""

    resolved_best_checkpoint_bytes = (
        best_checkpoint_bytes if best_checkpoint_bytes else latest_checkpoint_bytes
    )
    return Yolo11DetectionTrainingSavepointPayload(
        epoch=int(epoch),
        latest_checkpoint_bytes=latest_checkpoint_bytes,
        best_checkpoint_bytes=resolved_best_checkpoint_bytes,
        best_metric_name=best_metric_name,
        best_metric_value=serialize_yolo11_detection_best_metric_value(
            has_validation=has_validation,
            best_metric_value=best_metric_value,
        ),
    )


__all__ = [
    "Yolo11DetectionTrainingSavepointPayload",
    "build_yolo11_detection_training_savepoint_payload",
]
